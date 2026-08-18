"""차년도 투자계획 제안 엔드포인트."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.data.evidence import get_corpus
from app.data.panel import FUND_YEARS, get_panel
from app.errors import ApiError
from app.schemas.envelope import Envelope, panel_meta
from app.services import evidence_search
from app.services.proposal import BASIS_NOTE, RULES_SUMMARY, build_proposals

router = APIRouter(prefix="/api", tags=["차년도 제안"])

TYPE_QUERY_KEYWORDS = {
    "정착·정주형": "청년 정착 주거 생활 정주 여건",
    "유입 확대형": "청년 일자리 유입 창업 취업 이주",
    "혼합형": "청년 정착 일자리 주거",
    "현행 유지형": "청년 사업",
}


class Driver(BaseModel):
    metric: str = Field(description="판단에 쓰인 지표 키")
    label_ko: str
    value: float | None
    unit: str
    note: str


class EvidenceLink(BaseModel):
    project_name: str | None
    grade: str | None = Field(description="근거 등급. C는 2026 제안 근거로만 쓴다.")
    document: str
    page: int | None
    excerpt: str
    usable_for_performance_2017_2024: bool | None


class ProposalItem(BaseModel):
    region: str
    is_treated: bool
    fund_recipient: bool = Field(description="2022~2024 기금 배분 대상이었는지")
    priority_rank: int | None = Field(description="배분 대상 시군 안에서의 순위. 비대상은 null")
    priority_score: float | None = Field(description="0~100 점수")
    priority_level: str = Field(description="high | medium | low | not_ranked")
    score_components: dict[str, float | None] = Field(
        description="점수를 만든 세 항목의 백분위(0~1)"
    )
    recommended_project_type: str = Field(examples=["정착·정주형"])
    recommended_type_reason: str
    allocation_direction: str = Field(examples=["확대"])
    allocation_direction_reason: str
    composition_note: str | None
    rationale_ko: str = Field(description="화면에 그대로 쓸 수 있는 근거 문장")
    drivers: list[Driver]
    evidence_links: list[EvidenceLink] = Field(
        default_factory=list, description="등록부·사업내역서에서 찾은 근거 문서"
    )


class ProposalBasis(BaseModel):
    is_causal_estimate: bool = Field(
        description="이 제안이 확정된 인과효과에 근거하는지. 항상 false 다.", examples=[False]
    )
    statement_ko: str = Field(description="근거 성격을 밝히는 문장")
    based_on_years: list[int] = Field(description="제안 계산에 쓴 데이터 연도")
    rules: list[str] = Field(description="적용된 규칙 요약")


class ProposalData(BaseModel):
    year: int = Field(description="제안 대상 연도", examples=[2026])
    basis: ProposalBasis
    proposals: list[ProposalItem]


@router.get(
    "/proposal",
    response_model=Envelope[ProposalData],
    summary="차년도 투자계획 제안",
    description=(
        "시군별 우선순위, 권장 사업 유형, 배분 조정 방향, 근거 문장, 근거 문서 링크를 반환한다. "
        "규칙 기반이며 LLM을 쓰지 않는다. 규칙은 basis.rules 에 함께 실린다.\n\n"
        "**이 제안은 확정된 인과효과가 아니다.** 1차 DID 추정이 유의하지 않아 기술통계와 "
        "진단 지표에 근거한 참고안이며, `basis.is_causal_estimate` 는 항상 false 다.\n\n"
        "순위는 기금 배분 대상 6개 시군 안에서만 매기고, 비배분 5개 시군은 진단만 제공한다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "year": 2026,
                            "basis": {
                                "is_causal_estimate": False,
                                "statement_ko": BASIS_NOTE,
                                "based_on_years": [2022, 2023, 2024],
                                "rules": RULES_SUMMARY,
                            },
                            "proposals": [
                                {
                                    "region": "괴산군",
                                    "is_treated": True,
                                    "fund_recipient": True,
                                    "priority_rank": 1,
                                    "priority_score": 82.5,
                                    "priority_level": "high",
                                    "score_components": {
                                        "level": 0.8,
                                        "trend": 0.6,
                                        "allocation_gap": 0.2,
                                    },
                                    "recommended_project_type": "정착·정주형",
                                    "recommended_type_reason": "전출률이 중앙값보다 +2.10명/천명 높아 유출이 주 원인이다.",
                                    "allocation_direction": "집행 구조 개선 우선(배분 유지)",
                                    "allocation_direction_reason": "2024년 집행률이 12.9%로 50% 미만이라 배분 확대보다 집행 구조 개선이 먼저다.",
                                    "composition_note": "정착·정주형을 권장하지만 2024년 정주·생활서비스 사업 비중이 0%에 그쳐 구성 조정이 필요하다.",
                                    "rationale_ko": "괴산군의 최근 3년 청년 순이동률은 평균 -3.20명/천명이고 …",
                                    "drivers": [
                                        {
                                            "metric": "youth_net_migration_rate_per_1000",
                                            "label_ko": "최근 3년(2022~2024) 청년 순이동률 평균",
                                            "value": -3.2,
                                            "unit": "명/천명",
                                            "note": "값이 음수이면 청년이 순유출되고 있다는 뜻이다.",
                                        }
                                    ],
                                    "evidence_links": [],
                                }
                            ],
                        },
                        "meta": {
                            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                            "as_of": "2024-12",
                            "data_status": "derived",
                            "notes": [BASIS_NOTE],
                        },
                    }
                }
            }
        },
        422: {"description": "패널 종료 연도 이전을 제안 연도로 요청한 경우."},
    },
)
def proposal(
    year: int = Query(
        default=2026,
        ge=2000,
        le=2100,
        description="제안 대상 연도. 패널 종료 연도(2024) 이후만 받는다.",
        examples=[2026],
    ),
    include_evidence: bool = Query(
        default=True, description="근거 문서 링크를 함께 찾을지 여부"
    ),
) -> Envelope[ProposalData]:
    panel = get_panel()
    last_year = max(panel.available_years)
    if year <= last_year:
        raise ApiError(
            status_code=422,
            code="invalid_proposal_year",
            message=(
                f"{year}년은 이미 패널에 관측치가 있는 연도입니다. "
                f"제안은 {last_year + 1}년 이후를 대상으로 합니다. "
                f"과거 연도는 /api/funds/local-extinction/regions 로 조회하세요."
            ),
            field="year",
            allowed_values=[str(y) for y in range(last_year + 1, last_year + 6)],
        )

    proposals = build_proposals(panel)

    if include_evidence:
        corpus = get_corpus()
        index = evidence_search.get_index()
        # 2026 제안이므로 등급 C도 근거로 쓸 수 있다(2025년 이후 착수 사업).
        usable = {p.project_id: p.usable_for_performance_2017_2024 for p in corpus.projects}
        for item in proposals:
            region_chunks = [
                position
                for position, chunk in enumerate(index.chunks)
                if chunk.region == item["region"]
            ]
            if not region_chunks:
                item["evidence_links"] = []
                continue
            query = TYPE_QUERY_KEYWORDS.get(item["recommended_project_type"], "청년 사업")
            hits = index.search(query, allowed_indices=region_chunks, top_k=2)
            item["evidence_links"] = [
                {
                    "project_name": index.chunks[hit["index"]].project_name,
                    "grade": index.chunks[hit["index"]].grade,
                    "document": index.chunks[hit["index"]].document,
                    "page": index.chunks[hit["index"]].page,
                    "excerpt": index.chunks[hit["index"]].text[:300],
                    "usable_for_performance_2017_2024": usable.get(
                        index.chunks[hit["index"]].project_id or ""
                    ),
                }
                for hit in hits
            ]

    return Envelope[ProposalData](
        data=ProposalData(
            year=year,
            basis=ProposalBasis(
                is_causal_estimate=False,
                statement_ko=BASIS_NOTE,
                based_on_years=list(FUND_YEARS),
                rules=RULES_SUMMARY,
            ),
            proposals=[ProposalItem(**item) for item in proposals],
        ),
        meta=panel_meta(
            as_of=panel.period_end,
            data_status="derived",
            notes=[
                BASIS_NOTE,
                "순위는 2022~2024 기금 배분 대상 6개 시군 안에서만 매겼다. 비배분 5개 시군은 진단만 제공한다.",
                "근거 문서는 현재 제천시 3건만 등록되어 있어 다른 시군은 evidence_links 가 비어 있다.",
                *RULES_SUMMARY,
            ],
        ),
    )
