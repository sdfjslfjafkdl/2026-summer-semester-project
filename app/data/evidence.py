"""근거 문서 파싱: 사업 등록부(Markdown 표)와 사업내역서 PDF.

등급의 뜻(project_evidence_register_ko.md 판정 기준):
  A - 공식 사업내역서에 기금액·사업기간이 있고 2022~2024 평가창 내 추진 기록이 있음
  B - 기금액·사업기간은 있으나 평가창 내 추진 기록이 불충분
  C - 사업 시작이 2025년 이후. 2017~2024 효과추정에서 제외하고 2026 제안 근거로만 사용

이 등급 규칙은 검색 응답에 항상 실려 나가며, 성과 질의에서 C등급이 근거로 인용되는 것을 막는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

GRADE_MEANING: dict[str, str] = {
    "A": "공식 사업내역서에 기금액·사업기간이 있고, 2022~2024 평가창 내 실제 추진 기록이 확인됨",
    "B": "공식 사업내역서에 기금액·사업기간은 있으나 평가창 내 실제 추진 기록이 불충분함",
    "C": "공식 계획·선정 자료는 있으나 사업 시작이 2025년 이후임",
}

GRADE_USAGE: dict[str, str] = {
    "A": "사업별 사례분석 및 착수시점 후보로 사용",
    "B": "설명·근거 카드로만 사용. 월별 처치시점 추정에는 사용하지 않음",
    "C": "2017~2024 효과추정에서 제외. 2026 제안·RAG 참고자료로만 사용",
}

# 성과 평가창(패널의 기금 투입 기간)
PERFORMANCE_WINDOW = "2017-01~2024-12"


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    region: str
    project_name: str
    grade: str
    fund_million_krw: float | None
    official_period: str
    period_start: str | None  # YYYY-MM
    period_end: str | None  # YYYY-MM 또는 None(지속)
    evidence_note: str
    usage_note: str
    usable_for_performance_2017_2024: bool
    usable_for_proposal_2026: bool
    source_document: str | None = None

    @property
    def grade_meaning(self) -> str:
        return GRADE_MEANING.get(self.grade, "")

    @property
    def grade_usage(self) -> str:
        return GRADE_USAGE.get(self.grade, "")


@dataclass
class EvidenceCorpus:
    projects: list[ProjectRecord]
    register_path: Path
    pdf_dir: Path
    documents: dict[str, Path] = field(default_factory=dict)

    def by_id(self, project_id: str) -> ProjectRecord | None:
        return next((p for p in self.projects if p.project_id == project_id), None)


def nfc(text: str) -> str:
    """macOS 파일명은 자모가 분리된 NFD로 저장된다. 비교·응답 전에 NFC로 합친다."""
    return unicodedata.normalize("NFC", text)


def _normalize(text: str) -> str:
    return re.sub(r"[\s·\-_()]", "", nfc(text))


def _parse_fund(cell: str) -> float | None:
    match = re.search(r"([\d,]+)\s*백만원", cell)
    return float(match.group(1).replace(",", "")) if match else None


def _parse_period(cell: str) -> tuple[str | None, str | None]:
    """'2023.04~지속', '2025.01~2028.12', '2025~2027' 형태를 YYYY-MM 범위로."""
    text = cell.replace(" ", "")
    parts = re.split(r"[~∼-]", text, maxsplit=1)

    def to_month(token: str, *, is_end: bool) -> str | None:
        token = token.strip().rstrip(".")
        if not token or "지속" in token:
            return None
        ym = re.match(r"^(\d{4})\.(\d{1,2})$", token)
        if ym:
            return f"{ym.group(1)}-{int(ym.group(2)):02d}"
        year = re.match(r"^(\d{4})$", token)
        if year:
            return f"{year.group(1)}-{'12' if is_end else '01'}"
        return None

    start = to_month(parts[0], is_end=False)
    end = to_month(parts[1], is_end=True) if len(parts) > 1 else None
    return start, end


def _slug(region: str, name: str, index: int) -> str:
    return f"{region}-{index + 1:02d}-" + re.sub(r"[^0-9A-Za-z가-힣]+", "-", name).strip("-")[:40]


def parse_register(path: Path) -> list[ProjectRecord]:
    """'## 등록 결과' 표를 사업 레코드로 변환한다."""
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## 등록 결과"):
            in_table = True
            continue
        if in_table:
            if stripped.startswith("## "):
                break
            if not stripped.startswith("|"):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 7:
                continue
            if cells[0] in {"지역", ""} or set(cells[0]) <= set("-: "):
                continue
            rows.append(cells)

    records: list[ProjectRecord] = []
    for index, cells in enumerate(rows):
        region, name, fund_cell, period_cell, evidence, grade_cell, usage = cells[:7]
        grade = re.sub(r"[^A-C]", "", grade_cell.upper())[:1] or "B"
        start, end = _parse_period(period_cell)
        # 시작이 2025년 이후면 2017~2024 성과 근거로 쓸 수 없다. 등급 C의 정의와 같다.
        starts_after_window = bool(start and start >= "2025-01")
        records.append(
            ProjectRecord(
                project_id=_slug(region, name, index),
                region=region,
                project_name=name,
                grade=grade,
                fund_million_krw=_parse_fund(fund_cell),
                official_period=period_cell,
                period_start=start,
                period_end=end,
                evidence_note=evidence,
                usage_note=re.sub(r"\*\*", "", usage),
                usable_for_performance_2017_2024=(grade != "C" and not starts_after_window),
                usable_for_proposal_2026=True,
            )
        )
    return records


def match_documents(records: list[ProjectRecord], pdf_dir: Path) -> list[ProjectRecord]:
    """사업명과 PDF 파일명을 정규화 후 부분일치로 연결한다."""
    pdfs = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    matched: list[ProjectRecord] = []
    for order, record in enumerate(records):
        target = _normalize(record.project_name)
        found = next((p for p in pdfs if target in _normalize(p.name)), None)
        if found is None and order < len(pdfs):
            found = None  # 순서 추정으로 잘못 연결하느니 비워 둔다
        matched.append(
            ProjectRecord(
                **{**record.__dict__, "source_document": nfc(found.name) if found else None}
            )
        )
    return matched


@lru_cache
def get_corpus() -> EvidenceCorpus:
    settings = get_settings()
    register_path = settings.resolve(settings.evidence_register_md)
    pdf_dir = settings.resolve(settings.evidence_pdf_dir)
    records = match_documents(parse_register(register_path), pdf_dir)
    documents = {nfc(p.name): p for p in sorted(pdf_dir.glob("*.pdf"))} if pdf_dir.exists() else {}
    return EvidenceCorpus(
        projects=records,
        register_path=register_path,
        pdf_dir=pdf_dir,
        documents=documents,
    )
