"""근거 문서 하이브리드 검색 (Layer 1).

두 레인을 합친다.
  keyword lane : 어절 토큰 BM25. '청년', '주거' 같은 정확한 용어가 있는 청크를 끌어올린다.
  vector  lane : 문자 2-gram TF-IDF 코사인. 조사·띄어쓰기가 달라도 걸리게 하는 유사도 레인.

문서가 3건뿐이고 외부 임베딩 API 없이도 데모가 돌아가야 하므로 벡터 레인은 로컬에서
결정적으로 계산한다. 같은 질의에 항상 같은 순위가 나온다. 임베딩 제공자가 생기면
vector lane 만 교체하면 된다.

PDF 파싱 결과(청크)는 data/index/ 에 캐싱하고 원본 파일 지문이 바뀔 때만 다시 만든다.
기동 시에는 아무것도 하지 않고 첫 검색 요청에서 지연 로딩한다.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import get_settings
from app.data.evidence import EvidenceCorpus, get_corpus

logger = logging.getLogger(__name__)

INDEX_VERSION = 3
INDEX_FILENAME = "evidence_chunks.json"

CHUNK_SIZE = 450
CHUNK_OVERLAP = 80

BM25_K1 = 1.5
BM25_B = 0.75
KEYWORD_WEIGHT = 0.5
VECTOR_WEIGHT = 0.5

TOKEN_PATTERN = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+")


@dataclass
class Chunk:
    chunk_id: str
    project_id: str | None
    project_name: str | None
    region: str | None
    grade: str | None
    document: str
    document_kind: str  # pdf | register
    page: int | None
    text: str


def _tokens(text: str) -> list[str]:
    """어절 토큰. 한국어는 접미 조사가 붙으므로 앞 2~4글자 접두형도 함께 넣는다."""
    tokens: list[str] = []
    for raw in TOKEN_PATTERN.findall(text):
        tokens.append(raw)
        if re.fullmatch(r"[가-힣]+", raw) and len(raw) > 2:
            tokens.extend(raw[:n] for n in (2, 3) if len(raw) > n)
    return tokens


def _bigrams(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text)
    return [compact[i : i + 2] for i in range(len(compact) - 1)]


def _split_text(text: str) -> list[str]:
    cleaned = re.sub(r"[ \t]+", " ", text).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for start in range(0, len(cleaned), step):
        piece = cleaned[start : start + CHUNK_SIZE].strip()
        if len(piece) >= 40 or not chunks:
            chunks.append(piece)
        if start + CHUNK_SIZE >= len(cleaned):
            break
    return chunks


def _fingerprint(corpus: EvidenceCorpus) -> dict[str, list[float]]:
    files = [corpus.register_path, *sorted(corpus.documents.values())]
    return {
        p.name: [p.stat().st_mtime, p.stat().st_size] for p in files if p.exists()
    }


def _build_chunks(corpus: EvidenceCorpus) -> list[Chunk]:
    from pypdf import PdfReader

    chunks: list[Chunk] = []

    # 등록부: 사업 1건당 1청크. 등급 판정 근거 자체가 검색 대상이 된다.
    for record in corpus.projects:
        text = (
            f"{record.region} {record.project_name}. "
            f"등급 {record.grade}. 기금액 {record.fund_million_krw or 0:,.0f}백만원. "
            f"공식 사업기간 {record.official_period}. "
            f"확인된 추진근거: {record.evidence_note} 사용 판정: {record.usage_note}"
        )
        chunks.append(
            Chunk(
                chunk_id=f"register::{record.project_id}",
                project_id=record.project_id,
                project_name=record.project_name,
                region=record.region,
                grade=record.grade,
                document=corpus.register_path.name,
                document_kind="register",
                page=None,
                text=text,
            )
        )

    document_owner = {
        record.source_document: record
        for record in corpus.projects
        if record.source_document
    }

    for name, path in corpus.documents.items():
        record = document_owner.get(name)
        reader = PdfReader(str(path))
        for page_number, page in enumerate(reader.pages, start=1):
            for order, piece in enumerate(_split_text(page.extract_text() or "")):
                chunks.append(
                    Chunk(
                        chunk_id=f"{name}::p{page_number}::{order}",
                        project_id=record.project_id if record else None,
                        project_name=record.project_name if record else None,
                        region=record.region if record else "제천시",
                        grade=record.grade if record else None,
                        document=name,
                        document_kind="pdf",
                        page=page_number,
                        text=piece,
                    )
                )
    return chunks


def _index_path() -> Path:
    """캐시 파일 경로. 디렉터리를 만들지 못해도 예외를 올리지 않는다.

    배포 환경에서는 이 경로가 마운트된 볼륨(Railway 등)이라 처음엔 비어 있고,
    권한에 따라 쓰기가 막힐 수도 있다. 캐시는 원본에서 언제든 다시 만들 수 있는
    부가물이므로, 캐시 때문에 검색 요청이 실패해서는 안 된다.
    """
    settings = get_settings()
    directory = settings.resolve(settings.index_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("인덱스 캐시 디렉터리를 만들지 못했습니다(%s). 메모리에서만 사용합니다.", exc)
    return directory / INDEX_FILENAME


class EvidenceIndex:
    """청크 + 두 레인의 통계. 프로세스당 1회 구성한다."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._token_counts = [Counter(_tokens(c.text)) for c in chunks]
        self._lengths = [sum(tc.values()) for tc in self._token_counts]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        document_frequency: Counter[str] = Counter()
        for counts in self._token_counts:
            document_frequency.update(counts.keys())
        total = max(len(chunks), 1)
        self._idf = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

        bigram_counts = [Counter(_bigrams(c.text)) for c in chunks]
        bigram_df: Counter[str] = Counter()
        for counts in bigram_counts:
            bigram_df.update(counts.keys())
        self._bigram_idf = {
            term: math.log(1 + total / (freq + 1)) for term, freq in bigram_df.items()
        }
        self._vectors = [self._vectorize(counts) for counts in bigram_counts]

    def _vectorize(self, counts: Counter[str]) -> dict[str, float]:
        vector = {
            term: (1 + math.log(count)) * self._bigram_idf.get(term, 1.0)
            for term, count in counts.items()
        }
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        return {term: value / norm for term, value in vector.items()}

    def _bm25(self, query_tokens: list[str], index: int) -> float:
        counts = self._token_counts[index]
        length = self._lengths[index] or 1
        score = 0.0
        for term in query_tokens:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            idf = self._idf.get(term, 0.0)
            denominator = frequency + BM25_K1 * (
                1 - BM25_B + BM25_B * length / (self._avg_length or 1)
            )
            score += idf * frequency * (BM25_K1 + 1) / denominator
        return score

    def search(
        self,
        query: str,
        *,
        allowed_indices: list[int] | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        query_tokens = _tokens(query)
        query_vector = self._vectorize(Counter(_bigrams(query)))
        candidates = allowed_indices if allowed_indices is not None else range(len(self.chunks))

        scored: list[dict] = []
        for index in candidates:
            keyword = self._bm25(query_tokens, index)
            vector = sum(
                weight * query_vector.get(term, 0.0)
                for term, weight in self._vectors[index].items()
            )
            scored.append({"index": index, "keyword_score": keyword, "vector_score": vector})

        max_keyword = max((s["keyword_score"] for s in scored), default=0.0) or 1.0
        for entry in scored:
            entry["keyword_score_normalized"] = entry["keyword_score"] / max_keyword
            entry["score"] = (
                KEYWORD_WEIGHT * entry["keyword_score_normalized"]
                + VECTOR_WEIGHT * entry["vector_score"]
            )

        scored.sort(key=lambda e: (-e["score"], self.chunks[e["index"]].chunk_id))
        return [entry for entry in scored[:top_k] if entry["score"] > 0]


_index: EvidenceIndex | None = None


def load_chunks(force_rebuild: bool = False) -> list[Chunk]:
    """캐시가 유효하면 읽고, 원본이 바뀌었으면 PDF를 다시 파싱한다."""
    corpus = get_corpus()
    fingerprint = _fingerprint(corpus)
    path = _index_path()

    if not force_rebuild and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                cached.get("index_version") == INDEX_VERSION
                and cached.get("fingerprint") == fingerprint
            ):
                return [Chunk(**c) for c in cached["chunks"]]
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass  # 캐시가 깨졌거나 읽을 수 없으면 조용히 다시 만든다

    chunks = _build_chunks(corpus)
    try:
        path.write_text(
            json.dumps(
                {
                    "index_version": INDEX_VERSION,
                    "fingerprint": fingerprint,
                    "chunks": [asdict(c) for c in chunks],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        # 캐시를 못 써도 검색은 그대로 동작한다. 다음 기동에서 다시 만들어 본다.
        logger.warning("인덱스 캐시를 저장하지 못했습니다(%s). 기동 시마다 새로 만듭니다.", exc)
    return chunks


def get_index(force_rebuild: bool = False) -> EvidenceIndex:
    global _index
    if _index is None or force_rebuild:
        _index = EvidenceIndex(load_chunks(force_rebuild=force_rebuild))
    return _index
