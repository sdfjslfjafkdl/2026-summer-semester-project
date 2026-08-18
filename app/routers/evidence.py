"""근거 검색 엔드포인트.

검색 결과에는 항상 등급이 함께 나간다. purpose=performance_2017_2024 로 조회하면
등급 C(2025년 이후 시작) 사업은 결과에서 제외된다. 과거 성과의 근거로 오용되는 것을 막기 위함이다.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.data.evidence import GRADE_MEANING, GRADE_USAGE, PERFORMANCE_WINDOW, get_corpus
from app.errors import ApiError
from app.schemas.envelope import Envelope, Meta
from app.services import evidence_search

router = APIRouter(prefix="/api/evidence", tags=["근거 검색"])

PURPOSES = ("all", "performance_2017_2024", "proposal_2026")
GRADES = ("A", "B", "C")

PERFORMANCE_GUARD_NOTE = (
    f"purpose=performance_2017_2024 조회이므로 등급 C 사업(2025년 이후 시작)은 제외했다. "
    f"성과 평가창은 {PERFORMANCE_WINDOW} 이다."
)


class ProjectItem(BaseModel):
    project_id: str
    region: str
    project_name: str
    grade: str = Field(description="A, B, C 중 하나", examples=["A"])
    grade_meaning: str = Field(description="등급 판정 기준 문장")
    grade_usage: str = Field(description="모델에서의 사용 판정")
    fund_million_krw: float | None = Field(description="기금액(백만원)", examples=[1600.0])
    official_period: str = Field(description="공식 사업기간 원문", examples=["2023.04~지속"])
    period_start: str | None = Field(description="사업 시작(YYYY-MM)", examples=["2023-04"])
    period_end: str | None = Field(description="사업 종료(YYYY-MM). 지속이면 null")
    evidence_note: str = Field(description="확인된 추진근거")
    usage_note: str = Field(description="등록부의 사용 판정 원문")
    usable_for_performance_2017_2024: bool = Field(
        description="2017~2024 성과 근거로 인용해도 되는지. 등급 C는 false."
    )
    usable_for_proposal_2026: bool
    source_document: str | None = Field(description="원본 PDF 파일명")


class ProjectsData(BaseModel):
    projects: list[ProjectItem]
    grade_criteria: dict[str, str] = Field(description="등급별 판정 기준")
    grade_usage: dict[str, str] = Field(description="등급별 사용 판정")


class SearchHit(BaseModel):
    chunk_id: str
    project_id: str | None
    project_name: str | None
    region: str | None
    grade: str | None
    grade_usage: str | None
    usable_for_performance_2017_2024: bool | None
    document: str = Field(description="문서명", examples=["지방소멸대응기금_(2026-5)(미래정책과)제천시 고려인 등 재외동포 이주정착 지원사업.pdf"])
    document_kind: str = Field(description="pdf 또는 register")
    page: int | None = Field(description="PDF 쪽 번호. 등록부 청크는 null")
    excerpt: str = Field(description="원문 발췌")
    score: float = Field(description="하이브리드 최종 점수(0~1 부근)")
    keyword_score: float = Field(description="BM25 레인 점수(정규화)")
    vector_score: float = Field(description="문자 2-gram 코사인 레인 점수")


class SearchData(BaseModel):
    query: str
    purpose: str
    grades: list[str]
    top_k: int
    hits: list[SearchHit]
    excluded_grade_c_count: int = Field(
        description="성과 목적 조회에서 등급 C 때문에 제외된 후보 청크 수"
    )


@router.get(
    "/projects",
    response_model=Envelope[ProjectsData],
    summary="등록된 사업 목록과 등급",
    description=(
        "사업 등록부(project_evidence_register_ko.md)를 파싱해 사업명, 등급, 기금액, "
        "사업기간, 사용 판정을 반환한다. 등급 C 사업은 2017~2024 성과 근거로 쓰지 않는다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "projects": [
                                {
                                    "project_id": "제천시-01-고려인-등-재외동포-이주정착-지원사업",
                                    "region": "제천시",
                                    "project_name": "고려인 등 재외동포 이주정착 지원사업",
                                    "grade": "A",
                                    "grade_meaning": "공식 사업내역서에 기금액·사업기간이 있고, 2022~2024 평가창 내 실제 추진 기록이 확인됨",
                                    "grade_usage": "사업별 사례분석 및 착수시점 후보로 사용",
                                    "fund_million_krw": 1600.0,
                                    "official_period": "2023.04~지속",
                                    "period_start": "2023-04",
                                    "period_end": None,
                                    "evidence_note": "2024.02.06 행정지원단 운영계획 등 평가창 내 추진 기록 확인",
                                    "usage_note": "2023-04를 사업 착수월 후보로 기록",
                                    "usable_for_performance_2017_2024": True,
                                    "usable_for_proposal_2026": True,
                                    "source_document": "지방소멸대응기금_(2026-5)(미래정책과)제천시 고려인 등 재외동포 이주정착 지원사업.pdf",
                                }
                            ],
                            "grade_criteria": GRADE_MEANING,
                            "grade_usage": GRADE_USAGE,
                        },
                        "meta": {
                            "source": "project_evidence_register_ko.md",
                            "as_of": "2024-12",
                            "data_status": "actual",
                            "notes": [],
                        },
                    }
                }
            }
        }
    },
)
def projects() -> Envelope[ProjectsData]:
    corpus = get_corpus()
    return Envelope[ProjectsData](
        data=ProjectsData(
            projects=[
                ProjectItem(
                    project_id=p.project_id,
                    region=p.region,
                    project_name=p.project_name,
                    grade=p.grade,
                    grade_meaning=p.grade_meaning,
                    grade_usage=p.grade_usage,
                    fund_million_krw=p.fund_million_krw,
                    official_period=p.official_period,
                    period_start=p.period_start,
                    period_end=p.period_end,
                    evidence_note=p.evidence_note,
                    usage_note=p.usage_note,
                    usable_for_performance_2017_2024=p.usable_for_performance_2017_2024,
                    usable_for_proposal_2026=p.usable_for_proposal_2026,
                    source_document=p.source_document,
                )
                for p in corpus.projects
            ],
            grade_criteria=GRADE_MEANING,
            grade_usage=GRADE_USAGE,
        ),
        meta=Meta(
            source=corpus.register_path.name,
            as_of="2024-12",
            data_status="actual",
            notes=[
                "등급 C 사업은 2025년 이후 시작이라 2017~2024 효과추정에서 제외하고 2026 제안 근거로만 쓴다.",
                "현재 등록부는 제천시 3건이며, 다른 시군 사업은 아직 등록되지 않았다.",
            ],
        ),
    )


@router.get(
    "/search",
    response_model=Envelope[SearchData],
    summary="근거 문서 하이브리드 검색",
    description=(
        "사업내역서 PDF와 등록부를 함께 검색해 사업명, 등급, 원문 발췌, 문서명, 페이지를 반환한다. "
        "키워드(BM25)와 문자 2-gram 벡터 유사도를 절반씩 섞으며, 외부 임베딩 API 없이 동작한다.\n\n"
        "`purpose=performance_2017_2024` 로 조회하면 등급 C 사업이 결과에서 빠진다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "query": "청년 주거",
                            "purpose": "all",
                            "grades": ["A", "B", "C"],
                            "top_k": 5,
                            "hits": [
                                {
                                    "chunk_id": "(2026-53)(농촌상생과)제천시 청년농촌보금자리조성사업.pdf::p1::0",
                                    "project_id": "제천시-03-청년농촌보금자리조성사업",
                                    "project_name": "청년농촌보금자리조성사업",
                                    "region": "제천시",
                                    "grade": "C",
                                    "grade_usage": "2017~2024 효과추정에서 제외. 2026 제안·RAG 참고자료로만 사용",
                                    "usable_for_performance_2017_2024": False,
                                    "document": "(2026-53)(농촌상생과)제천시 청년농촌보금자리조성사업.pdf",
                                    "document_kind": "pdf",
                                    "page": 1,
                                    "excerpt": "농촌 청년가구의 주거부담을 완화하고 …",
                                    "score": 0.71,
                                    "keyword_score": 1.0,
                                    "vector_score": 0.42,
                                }
                            ],
                            "excluded_grade_c_count": 0,
                        },
                        "meta": {
                            "source": "data/raw/evidence/pdf + project_evidence_register_ko.md",
                            "as_of": "2024-12",
                            "data_status": "actual",
                            "notes": [],
                        },
                    }
                }
            }
        }
    },
)
def search(
    q: str = Query(description="검색어", examples=["청년 주거"]),
    grade: str | None = Query(
        default=None,
        description="콤마로 구분한 등급 필터. 예: A,C. 생략하면 전체.",
        examples=["A,C"],
    ),
    top_k: int = Query(default=5, ge=1, le=50, description="반환할 청크 수"),
    purpose: str = Query(
        default="all",
        description=(
            "all | performance_2017_2024 | proposal_2026. "
            "performance_2017_2024 는 등급 C를 자동 제외한다."
        ),
        examples=["all"],
    ),
) -> Envelope[SearchData]:
    if not q.strip():
        raise ApiError(
            status_code=422, code="empty_query", message="검색어 q 가 비어 있습니다.", field="q"
        )
    if purpose not in PURPOSES:
        raise ApiError(
            status_code=422,
            code="invalid_purpose",
            message=f"purpose 는 {', '.join(PURPOSES)} 중 하나여야 합니다.",
            field="purpose",
            allowed_values=list(PURPOSES),
        )

    requested_grades = (
        [g.strip().upper() for g in grade.split(",") if g.strip()] if grade else list(GRADES)
    )
    invalid = [g for g in requested_grades if g not in GRADES]
    if invalid:
        raise ApiError(
            status_code=422,
            code="invalid_grade",
            message=f"등급은 {', '.join(GRADES)} 중 하나여야 합니다. 받은 값: {invalid}",
            field="grade",
            allowed_values=list(GRADES),
        )

    corpus = get_corpus()
    index = evidence_search.get_index()
    performance_only = purpose == "performance_2017_2024"
    effective_grades = [g for g in requested_grades if not (performance_only and g == "C")]

    usable_by_project = {
        p.project_id: p.usable_for_performance_2017_2024 for p in corpus.projects
    }

    allowed: list[int] = []
    excluded_c = 0
    for position, chunk in enumerate(index.chunks):
        chunk_grade = chunk.grade
        if performance_only and chunk_grade == "C":
            excluded_c += 1
            continue
        if chunk_grade is not None and chunk_grade not in effective_grades:
            continue
        allowed.append(position)

    results = index.search(q, allowed_indices=allowed, top_k=top_k)
    hits = []
    for entry in results:
        chunk = index.chunks[entry["index"]]
        hits.append(
            SearchHit(
                chunk_id=chunk.chunk_id,
                project_id=chunk.project_id,
                project_name=chunk.project_name,
                region=chunk.region,
                grade=chunk.grade,
                grade_usage=GRADE_USAGE.get(chunk.grade or "", None),
                usable_for_performance_2017_2024=usable_by_project.get(chunk.project_id or ""),
                document=chunk.document,
                document_kind=chunk.document_kind,
                page=chunk.page,
                excerpt=re.sub(r"\s+", " ", chunk.text).strip(),
                score=round(entry["score"], 6),
                keyword_score=round(entry["keyword_score_normalized"], 6),
                vector_score=round(entry["vector_score"], 6),
            )
        )

    notes = [
        "검색 결과에는 항상 등급이 함께 나간다. 등급 C는 2017~2024 성과 근거로 인용하지 않는다.",
        "하이브리드 점수 = 0.5 × BM25(정규화) + 0.5 × 문자 2-gram 코사인. 외부 임베딩 API를 쓰지 않는다.",
    ]
    if performance_only:
        notes.insert(0, PERFORMANCE_GUARD_NOTE)

    return Envelope[SearchData](
        data=SearchData(
            query=q,
            purpose=purpose,
            grades=effective_grades,
            top_k=top_k,
            hits=hits,
            excluded_grade_c_count=excluded_c,
        ),
        meta=Meta(
            source="data/raw/evidence/pdf + project_evidence_register_ko.md",
            as_of="2024-12",
            data_status="actual" if hits else "unavailable",
            notes=notes if hits else [*notes, f"'{q}' 에 대한 근거 문서 검색 결과가 없다."],
        ),
    )
