"""투자계획서 작성 지원 엔드포인트.

완성본을 만드는 도구가 아니다. 데이터로 채울 수 있는 곳을 채우고, 사람이 결정해야 하는
곳은 구획과 작성 지침으로 남겨 넘긴다. 서식은 한국지방재정공제회 '2026년 지방소멸대응기금
투자계획서 작성 안내서'를 따르며, 서식에 없는 항목은 만들지 않는다.
"""

from __future__ import annotations

import difflib
from typing import Literal

from fastapi import APIRouter, Path as PathParam, Response
from pydantic import BaseModel, Field

from app.data.plan_sections import SECTIONS, TEMPLATE_SOURCE, get_section
from app.errors import ApiError
from app.schemas.envelope import Envelope, Meta
from app.schemas.plan import (
    DataPoint,
    ExportRequest,
    PlanDetailData,
    PlanDraftData,
    PlanProgress,
    PlanSummaryData,
    PlanVersionEntry,
    ReviseData,
    ReviseRequest,
    SectionChange,
    SectionGuidance,
    SectionState,
    SectionUpdateData,
    SectionUpdateRequest,
)
from app.services import plan_builder, plan_docx, plan_llm, plan_store
from app.services.plan_store import StoredPlan, now_iso

router = APIRouter(prefix="/api/plan", tags=["투자계획서 작성 지원"])

PLAN_SOURCE = "plan_template + Layer 1 endpoints"


class DraftRequest(BaseModel):
    region: str = Field(description="충북 11개 시군 중 하나", examples=["제천시"])
    year: int = Field(
        default=2026, ge=2000, le=2100, description="계획 대상 연도. 패널 종료 연도 이후만 받는다.", examples=[2026]
    )


def _section_state(plan: StoredPlan, section_id: str) -> SectionState:
    spec = get_section(section_id)
    stored = plan.sections[section_id]
    return SectionState(
        section_id=spec.section_id,
        number=spec.number,
        chapter=spec.chapter,
        title=spec.title,
        fill_mode=spec.fill_mode,
        status=stored.status,  # type: ignore[arg-type]
        content=stored.content,
        source=stored.source,  # type: ignore[arg-type]
        data_points=[DataPoint(**p) for p in stored.data_points],
        warnings=stored.warnings,
        guidance=SectionGuidance(
            writing_guide=spec.writing_guide,
            evaluation_focus=spec.evaluation_focus,
            reference_note=spec.reference_note,
            source_page=spec.source_page,
        ),
        manual_remainder=spec.manual_remainder,
        version=stored.version,
        updated_at=stored.updated_at,
    )


def _all_sections(plan: StoredPlan) -> list[SectionState]:
    return [_section_state(plan, spec.section_id) for spec in SECTIONS]


def _meta(plan: StoredPlan, notes: list[str] | None = None) -> Meta:
    base = [
        "완성본이 아니라 초안이다. 회색 구획은 담당자가 작성해야 한다.",
        plan_builder.GUARD_POLICY,
        plan_builder.NOT_CAUSAL_NOTE,
        f"서식 출처: {TEMPLATE_SOURCE}",
    ]
    if not plan.persisted:
        base.append("계획서를 파일로 저장하지 못했다. 프로세스가 재시작되면 사라진다.")
    return Meta(source=PLAN_SOURCE, as_of="2024-12", data_status="derived", notes=base + (notes or []))


DRAFT_EXAMPLE = {
    "data": {
        "plan_id": "plan_제천시_2026_01",
        "region": "제천시",
        "year": 2026,
        "version": 1,
        "created_at": "2026-08-22T11:00:00+09:00",
        "template_source": TEMPLATE_SOURCE,
        "sections": [
            {
                "section_id": "1-1",
                "number": "Ⅰ-1",
                "chapter": "Ⅰ",
                "title": "지역 여건 및 현황분석",
                "fill_mode": "auto",
                "status": "filled",
                "content": "○ 인구현황 (2024년 기준)\n  - 주민등록 총인구 129,362명\n  - 20–39세 청년인구 25,073명",
                "source": "layer1",
                "data_points": [
                    {
                        "label": "2024년 총인구",
                        "value": 129362,
                        "unit": "명",
                        "source_endpoint": "/api/panel/timeseries",
                    }
                ],
                "warnings": [],
                "guidance": {
                    "writing_guide": "인구현황, 인구변동 요인 및 전망, 지방소멸 영향요인…",
                    "evaluation_focus": "지역 고유의 특성과 문제의 원인을 파악할 수 있도록 구체적으로 기술.",
                    "reference_note": "그림이나 도표, 위치도, 지형도, 사진 등 활용.",
                    "source_page": 10,
                },
                "manual_remainder": "입지·면적·교통접근성·주거·산업형태는 패널에 없으므로 담당자가 작성한다.",
                "version": 1,
                "updated_at": "2026-08-22T11:00:00+09:00",
            }
        ],
        "progress": {
            "total_sections": 27,
            "auto_filled": 2,
            "assisted_pending": 5,
            "manual_pending": 20,
            "awaiting_human": 25,
            "filled": 2,
            "completion_pct": 7.41,
        },
        "called_endpoints": [
            "/api/funds/local-extinction/regions",
            "/api/funds/local-extinction/trend",
            "/api/panel/timeseries",
            "/api/proposal",
            "/api/evidence/projects",
            "internal:plan_goal_targets",
        ],
    },
    "meta": {
        "source": PLAN_SOURCE,
        "as_of": "2024-12",
        "data_status": "derived",
        "notes": ["완성본이 아니라 초안이다. 회색 구획은 담당자가 작성해야 한다."],
    },
}


@router.post(
    "/draft",
    response_model=Envelope[PlanDraftData],
    summary="투자계획서 초안 생성",
    description=(
        "지역과 연도를 받아 서식 구조대로 초안을 만든다.\n\n"
        "- **auto** 섹션(Ⅰ-1 인구현황·인구변동 추이, Ⅵ-2-① 연도별 소계)은 Layer 1 결과로 채운다.\n"
        "- **assisted** 섹션(Ⅰ-2, Ⅲ-1, Ⅲ-3, Ⅲ-4-①, Ⅲ-별첨)은 데이터로 뒷받침되는 초안 문장을 넣고 "
        "담당자 입력을 기다린다. 특히 Ⅲ-3 은 청년 순이동률을 지표 후보로 제시하고 측정방법과 "
        "연차별 목표값 후보를 패널에서 도출해 함께 준다.\n"
        "- **manual** 섹션(Ⅱ 전체, Ⅲ-2, Ⅲ-4-⑤, Ⅲ-5, Ⅳ, Ⅴ, Ⅵ-1 등)은 채우지 않고 "
        "안내서의 【작성내용】과 【기술 방향과 평가의 주안점】만 넣는다.\n\n"
        "계획서에 들어간 숫자는 모두 `called_endpoints` 의 결과에 실재한다."
    ),
    responses={
        200: {"content": {"application/json": {"example": DRAFT_EXAMPLE}}},
        404: {"description": "없는 지역"},
        422: {"description": "패널 종료 연도 이전을 계획 연도로 요청한 경우"},
    },
)
def create_draft(request: DraftRequest) -> Envelope[PlanDraftData]:
    plan, notes = plan_builder.build_draft(request.region, request.year)
    return Envelope[PlanDraftData](
        data=PlanDraftData(
            plan_id=plan.plan_id,
            region=plan.region,
            year=plan.year,
            version=plan.version,
            created_at=plan.created_at,
            template_source=TEMPLATE_SOURCE,
            sections=_all_sections(plan),
            progress=PlanProgress(**plan_builder.progress(plan)),
            called_endpoints=plan.called_endpoints,
        ),
        meta=_meta(plan, notes),
    )


@router.get(
    "/{plan_id}",
    response_model=Envelope[PlanDetailData],
    summary="계획서 현재본 조회",
    description="최신본과 섹션별 상태, 버전 이력을 반환한다.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            **DRAFT_EXAMPLE["data"],
                            "history": [
                                {
                                    "version": 1,
                                    "created_at": "2026-08-22T11:00:00+09:00",
                                    "action": "draft",
                                    "changed_sections": [],
                                    "note": "초안 생성",
                                },
                                {
                                    "version": 2,
                                    "created_at": "2026-08-22T11:20:00+09:00",
                                    "action": "section_update",
                                    "changed_sections": ["3-2"],
                                    "note": "Ⅲ-2 갱신",
                                },
                            ],
                        },
                        "meta": DRAFT_EXAMPLE["meta"],
                    }
                }
            }
        },
        404: {"description": "없는 plan_id"},
    },
)
def get_plan(plan_id: str = PathParam(examples=["plan_제천시_2026_01"])) -> Envelope[PlanDetailData]:
    plan = plan_store.get(plan_id)
    return Envelope[PlanDetailData](
        data=PlanDetailData(
            plan_id=plan.plan_id,
            region=plan.region,
            year=plan.year,
            version=plan.version,
            created_at=plan.created_at,
            template_source=TEMPLATE_SOURCE,
            sections=_all_sections(plan),
            progress=PlanProgress(**plan_builder.progress(plan)),
            called_endpoints=plan.called_endpoints,
            history=[PlanVersionEntry(**h) for h in plan.history],
        ),
        meta=_meta(plan),
    )


@router.post(
    "/{plan_id}/sections/{section_id}",
    response_model=Envelope[SectionUpdateData],
    summary="섹션 채우기",
    description=(
        "담당자가 특정 섹션을 채운다.\n\n"
        "- **manual** 섹션은 입력을 그대로 저장하고 출처를 `human_input` 으로 표시한다.\n"
        "- **assisted** 섹션은 입력을 재료로 서식 톤의 문장을 만든다. LLM 이 꺼져 있으면 "
        "입력을 개조식으로 배치한 템플릿 문장이 된다.\n"
        "- Ⅵ-2 섹션에 `values` 로 사업별 합계를 넣으면(예: `{\"2022_배분액\": 4800}`) "
        "자동 집계된 연도별 소계와 대조해 어긋나면 경고를 낸다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "plan_id": "plan_제천시_2026_01",
                            "version": 2,
                            "section": {
                                "section_id": "6-2-1",
                                "number": "Ⅵ-2-①",
                                "chapter": "Ⅵ",
                                "title": "연도별 기금사업 추진 성과표",
                                "fill_mode": "auto",
                                "status": "filled",
                                "content": "○ 연도별 기금사업 추진 성과표 (단위: 백만원)…",
                                "source": "human_input",
                                "data_points": [
                                    {
                                        "label": "2022_배분액",
                                        "value": 4000,
                                        "unit": "",
                                        "source_endpoint": "human_input",
                                    }
                                ],
                                "warnings": [
                                    "2022년 배분액 불일치: 사업별 합계 4,000백만원, 자동 집계 소계 4,800백만원. 사업별 행이 누락되었거나 연도 구분이 어긋났을 수 있다."
                                ],
                                "guidance": {
                                    "writing_guide": "연도별 기금사업의 배분액·집행액·집행률(%)…",
                                    "evaluation_focus": "'22~'24년 기금사업 추진실적 및 성과는 1차 평가에 반영(가점 4점).",
                                    "reference_note": "사업 구분 / 배분액 / 집행액 / 집행률(%) / (완료·추진중) / 비고 표 형태.",
                                    "source_page": 35,
                                },
                                "manual_remainder": "사업별 행은 담당자가 작성한다.",
                                "version": 2,
                                "updated_at": "2026-08-22T11:20:00+09:00",
                            },
                            "progress": DRAFT_EXAMPLE["data"]["progress"],
                            "rejected_numbers": [],
                        },
                        "meta": DRAFT_EXAMPLE["meta"],
                    }
                }
            }
        },
        404: {"description": "없는 plan_id 또는 서식에 없는 section_id"},
    },
)
def update_section(
    request: SectionUpdateRequest,
    plan_id: str = PathParam(examples=["plan_제천시_2026_01"]),
    section_id: str = PathParam(description="서식 섹션 id", examples=["3-2"]),
) -> Envelope[SectionUpdateData]:
    plan = plan_store.get(plan_id)
    get_section(section_id)
    stored, rejected = plan_builder.update_section(plan, section_id, request.content, request.values)
    return Envelope[SectionUpdateData](
        data=SectionUpdateData(
            plan_id=plan.plan_id,
            version=plan.version,
            section=_section_state(plan, section_id),
            progress=PlanProgress(**plan_builder.progress(plan)),
            rejected_numbers=sorted(set(rejected)),
        ),
        meta=_meta(plan),
    )


@router.post(
    "/{plan_id}/revise",
    response_model=Envelope[ReviseData],
    summary="자연어 수정",
    description=(
        "수정 지시문을 받아 개정본을 만든다. 응답에 변경된 섹션, 섹션별 변경 요약, "
        "변경 전후 diff 가 들어간다.\n\n"
        "지시문에서 대상 섹션을 판별하지 못하면 임의로 전체를 고치지 않고 되묻는다"
        "(`resolved: false`, `clarification_question`)."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "대상을 찾은 경우": {
                            "value": {
                                "data": {
                                    "plan_id": "plan_제천시_2026_01",
                                    "version": 3,
                                    "instruction": "Ⅲ-3 사업목표의 연차별 목표값을 더 보수적으로 잡아줘",
                                    "resolved": True,
                                    "clarification_question": None,
                                    "candidate_sections": [],
                                    "changed_sections": ["3-3"],
                                    "changes": [
                                        {
                                            "section_id": "3-3",
                                            "number": "Ⅲ-3",
                                            "title": "사업 목표",
                                            "summary": "연차별 목표값을 최근 3년 평균 수준으로 낮췄습니다.",
                                            "before": "  - 1차년 -3.51",
                                            "after": "  - 1차년 -4.22",
                                            "diff": ["--- 3-3 (before)", "+++ 3-3 (after)", "-  - 1차년 -3.51", "+  - 1차년 -4.22"],
                                        }
                                    ],
                                    "progress": DRAFT_EXAMPLE["data"]["progress"],
                                },
                                "meta": DRAFT_EXAMPLE["meta"],
                            }
                        },
                        "되묻는 경우": {
                            "value": {
                                "data": {
                                    "plan_id": "plan_제천시_2026_01",
                                    "version": 2,
                                    "instruction": "좀 더 설득력 있게 고쳐줘",
                                    "resolved": False,
                                    "clarification_question": "어느 항목을 고칠까요? 지시문에서 대상 섹션을 찾지 못했습니다.",
                                    "candidate_sections": ["Ⅰ-2 지역 여건 및 현황분석 시사점", "Ⅲ-1 추진 배경 및 목적"],
                                    "changed_sections": [],
                                    "changes": [],
                                    "progress": None,
                                },
                                "meta": DRAFT_EXAMPLE["meta"],
                            }
                        },
                    }
                }
            }
        }
    },
)
def revise(
    request: ReviseRequest,
    plan_id: str = PathParam(examples=["plan_제천시_2026_01"]),
) -> Envelope[ReviseData]:
    plan = plan_store.get(plan_id)
    targets = plan_llm.resolve_targets(request.instruction, plan)

    if not targets:
        candidates = [
            f"{spec.number} {spec.title}"
            for spec in SECTIONS
            if plan.sections[spec.section_id].content
        ][:8]
        return Envelope[ReviseData](
            data=ReviseData(
                plan_id=plan.plan_id,
                version=plan.version,
                instruction=request.instruction,
                resolved=False,
                clarification_question=(
                    "어느 항목을 고칠까요? 지시문에서 대상 섹션을 찾지 못했습니다. "
                    "항목 번호(예: Ⅲ-3)나 항목 이름을 함께 적어 주세요."
                ),
                candidate_sections=candidates,
            ),
            meta=_meta(plan, ["대상 섹션을 판별하지 못해 아무것도 고치지 않았다."]),
        )

    from app.services.chat import ToolCall, allowed_numbers

    allowed = allowed_numbers([ToolCall(**c) for c in plan.tool_results]) | set(plan.human_numbers)
    changes: list[SectionChange] = []
    notes: list[str] = []

    for section_id in targets:
        spec = get_section(section_id)
        stored = plan.sections[section_id]
        before = stored.content
        new_content, summary = plan_llm.revise_section(spec, before, request.instruction, plan)

        if stored.source != "human_input":
            new_content, rejected = plan_builder.scrub(new_content, allowed)
            if rejected:
                notes.append(
                    f"{spec.number} 에서 근거 없는 숫자가 있어 해당 문장을 제거했다: "
                    + ", ".join(sorted(set(rejected)))
                )
        if new_content == (before or ""):
            continue

        stored.content = new_content or None
        stored.version += 1
        stored.updated_at = now_iso()
        if new_content:
            stored.status = "filled"

        diff = list(
            difflib.unified_diff(
                (before or "").splitlines(),
                new_content.splitlines(),
                fromfile=f"{section_id} (before)",
                tofile=f"{section_id} (after)",
                lineterm="",
                n=1,
            )
        )
        changes.append(
            SectionChange(
                section_id=section_id,
                number=spec.number,
                title=spec.title,
                summary=summary,
                before=before,
                after=new_content or None,
                diff=diff,
            )
        )

    if changes:
        plan.version += 1
        plan_store.record_history(
            plan, "revise", [c.section_id for c in changes], request.instruction[:80]
        )
        plan_store.save(plan)

    return Envelope[ReviseData](
        data=ReviseData(
            plan_id=plan.plan_id,
            version=plan.version,
            instruction=request.instruction,
            resolved=True,
            changed_sections=[c.section_id for c in changes],
            changes=changes,
            progress=PlanProgress(**plan_builder.progress(plan)),
        ),
        meta=_meta(plan, notes),
    )


@router.get(
    "/{plan_id}/summary",
    response_model=Envelope[PlanSummaryData],
    summary="비전문가용 요약",
    description=(
        "이 계획서가 무엇을 제안하고 근거가 무엇인지 다섯 문장 이내로 설명한다. "
        "아직 비어 있는 필수 섹션이 있으면 함께 알린다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "plan_id": "plan_제천시_2026_01",
                            "region": "제천시",
                            "year": 2026,
                            "summary_sentences": [
                                "이 문서는 제천시의 2026년 지방소멸대응기금 투자계획서 초안입니다.",
                                "제천시의 최근 3년 청년 순이동률은 평균 -4.21명/천명으로 청년 인구가 순유출되고 있습니다.",
                                "2024년 기금은 배분액 6,400백만원 중 4,093백만원이 집행되어 집행률은 63.95%입니다.",
                                "진단 결과 권장 사업 유형은 정착·정주형이며, 이는 확정된 인과효과가 아니라 기술통계에 근거한 참고안입니다.",
                                "27개 항목 중 2개가 자동으로 채워졌고 25개는 담당자 작성이 필요합니다.",
                            ],
                            "evidence": [
                                {
                                    "label": "2024년 집행률",
                                    "value": 63.95,
                                    "unit": "%",
                                    "source_endpoint": "/api/funds/local-extinction/regions",
                                }
                            ],
                            "missing_required_sections": ["Ⅰ-2", "Ⅱ-1", "Ⅲ-1"],
                            "is_submittable": False,
                        },
                        "meta": DRAFT_EXAMPLE["meta"],
                    }
                }
            }
        }
    },
)
def summary(plan_id: str = PathParam(examples=["plan_제천시_2026_01"])) -> Envelope[PlanSummaryData]:
    plan = plan_store.get(plan_id)
    data = plan_builder.summarize(plan)
    return Envelope[PlanSummaryData](
        data=PlanSummaryData(
            plan_id=plan.plan_id,
            region=plan.region,
            year=plan.year,
            summary_sentences=data["sentences"],
            evidence=[DataPoint(**p) for p in data["evidence"]],
            missing_required_sections=data["missing"],
            is_submittable=not data["missing"],
        ),
        meta=_meta(plan, data["notes"]),
    )


@router.post(
    "/{plan_id}/export",
    summary="docx / pdf 내보내기",
    description=(
        "계획서를 파일로 내보낸다. 응답은 봉투가 아니라 파일 자체이며, "
        "글꼴 대체 등 알림은 `X-Plan-Notes` 응답 헤더에 담긴다.\n\n"
        "- docx: 안내서의 목차(Ⅰ~Ⅵ)와 형식 규정(본문 휴먼명조 15pt, 참고사항 중고딕 13pt, "
        "여백 15/15/20/20mm, 쪽번호)을 반영한다. manual 섹션은 회색 음영과 "
        "`[담당자 작성 필요]` 표시, 그리고 안내서의 【작성내용】·【기술 방향과 평가의 주안점】이 들어간다.\n"
        "- pdf: 확인·공유용. 제출용 서식은 docx 를 hwp 로 변환해 맞춘다."
    ),
    responses={
        200: {
            "description": "파일 바이너리",
            "content": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/pdf": {},
            },
        }
    },
    response_class=Response,
)
def export(
    request: ExportRequest,
    plan_id: str = PathParam(examples=["plan_제천시_2026_01"]),
) -> Response:
    plan = plan_store.get(plan_id)
    if request.format == "docx":
        payload, notes = plan_docx.build_docx(plan)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"{plan.year}년도_지방소멸대응기금_투자계획서_초안_{plan.region}.docx"
    else:
        payload, notes = plan_docx.build_pdf(plan)
        media = "application/pdf"
        filename = f"{plan.year}년도_지방소멸대응기금_투자계획서_초안_{plan.region}.pdf"

    from urllib.parse import quote

    return Response(
        content=payload,
        media_type=media,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Plan-Notes": quote(" | ".join(notes)) if notes else "",
            "X-Plan-Version": str(plan.version),
        },
    )
