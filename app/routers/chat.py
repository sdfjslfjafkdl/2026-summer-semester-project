"""자연어 질의 엔드포인트 (Layer 2).

응답에는 라우팅 결과, 호출한 내부 엔드포인트와 그 결과, 서술 답변, 프론트 이동 정보,
근거 인용, 그리고 수치 검증 결과가 함께 담긴다. 발표·심사에서 수치의 출처를 추적할 수 있어야
하므로, 어떤 숫자가 어느 엔드포인트에서 나왔는지 항상 응답에 남긴다.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas.envelope import Envelope, panel_meta
from app.services import chat as chat_service

router = APIRouter(prefix="/api", tags=["자연어 질의"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(
        description="자연어 질문", examples=["제천시 집행률이 어떻게 되나요?"], min_length=1
    )
    history: list[ChatTurn] | None = Field(
        default=None, description="이전 대화 이력(선택). 최근 6턴만 사용한다."
    )


class RoutingResult(BaseModel):
    intent: str = Field(description="판정된 의도", examples=["fund_execution"])
    intent_label_ko: str = Field(examples=["기금 집행 현황 조회"])
    regions: list[str]
    region_group: str | None = Field(description="treatment | control | all | null")
    year: int | None
    metric: str | None
    fund_id: str | None
    confidence: float
    router: str = Field(description="rules 또는 llm. LLM 실패 시 rules 로 폴백한다.")
    matched_keywords: list[str]
    out_of_scope_reason: str | None


class ToolCallResult(BaseModel):
    endpoint: str = Field(description="호출한 내부 엔드포인트", examples=["/api/funds/local-extinction/summary"])
    params: dict[str, Any]
    data: dict[str, Any] = Field(description="그 엔드포인트가 반환한 data")
    meta: dict[str, Any] = Field(description="그 엔드포인트가 반환한 meta")


class Citation(BaseModel):
    endpoint: str
    source: str
    as_of: str | None
    data_status: str | None
    document: str | None = Field(description="근거 문서명(근거 검색일 때만)")
    page: int | None
    grade: str | None = Field(description="근거 등급(근거 검색일 때만)")


class Navigation(BaseModel):
    screen: str = Field(
        description="프론트가 이동할 화면 키. fund_dashboard | causal_analysis | evidence | proposal | chat",
        examples=["fund_dashboard"],
    )
    path: str = Field(description="제안 경로. 실제 라우팅 경로는 프론트가 정한다.", examples=["/dashboard"])
    params: dict[str, Any]


class NumericGuard(BaseModel):
    passed: bool = Field(description="답변의 모든 숫자가 도구 결과에 실재하는지")
    checked_numbers_in_answer: int
    rejected_numbers: list[str] = Field(description="도구 결과에 없어 거부된 숫자")
    policy: str


class ChatData(BaseModel):
    question: str
    routing: RoutingResult
    called_endpoints: list[str] = Field(description="호출한 내부 엔드포인트 목록")
    tool_results: list[ToolCallResult]
    answer: str = Field(description="서술 답변")
    narrator: str = Field(description="rules | llm | guard_fallback")
    navigation: Navigation
    citations: list[Citation]
    numeric_guard: NumericGuard
    llm_enabled: bool


CHAT_EXAMPLE = {
    "data": {
        "question": "제천시 집행률",
        "routing": {
            "intent": "fund_execution",
            "intent_label_ko": "기금 집행 현황 조회",
            "regions": ["제천시"],
            "region_group": None,
            "year": None,
            "metric": None,
            "fund_id": "local-extinction",
            "confidence": 1.0,
            "router": "rules",
            "matched_keywords": ["집행률", "집행"],
            "out_of_scope_reason": None,
        },
        "called_endpoints": [
            "internal:data_scope",
            "/api/funds/local-extinction/summary",
            "/api/funds/local-extinction/regions",
        ],
        "tool_results": [
            {
                "endpoint": "/api/funds/local-extinction/summary",
                "params": {"fund_id": "local-extinction", "year": 2024},
                "data": {"execution_rate_pct": 40.86},
                "meta": {"source": "chungbuk_monthly_model_panel_2017_2024.csv", "data_status": "derived"},
            }
        ],
        "answer": "제천시의 2024년 지방소멸대응기금 집행률은 64.0%입니다. 배분액 6,400백만원 중 4,093백만원을 집행했고 미집행액은 2,307백만원입니다. 집행률은 투입 진행률이며 성과 지표가 아닙니다.",
        "narrator": "rules",
        "navigation": {
            "screen": "fund_dashboard",
            "path": "/dashboard",
            "params": {"fund_id": "local-extinction", "year": 2024, "region": "제천시"},
        },
        "citations": [
            {
                "endpoint": "/api/funds/local-extinction/regions",
                "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                "as_of": "2024",
                "data_status": "derived",
                "document": None,
                "page": None,
                "grade": None,
            }
        ],
        "numeric_guard": {
            "passed": True,
            "checked_numbers_in_answer": 6,
            "rejected_numbers": [],
            "policy": "답변의 모든 숫자는 호출된 Layer 1 엔드포인트 결과에 실재해야 한다.",
        },
        "llm_enabled": False,
    },
    "meta": {
        "source": "layer2_agent",
        "as_of": "2024-12",
        "data_status": "derived",
        "notes": ["답변의 수치는 모두 called_endpoints 의 결과에서 인용했다."],
    },
}


@router.post(
    "/chat",
    response_model=Envelope[ChatData],
    summary="자연어 질의",
    description=(
        "질문을 의도와 슬롯으로 라우팅해 Layer 1 엔드포인트를 호출하고, 그 결과만 인용해 답한다.\n\n"
        "- **라우팅**: LLM_ENABLED=true 이고 키가 있으면 LLM이 구조화된 JSON으로 판정하고, "
        "실패하면 규칙 라우터로 폴백한다. 키 없이도 전 과정이 동작한다.\n"
        "- **수치 검증**: 답변에 등장한 숫자가 도구 결과에 없으면 그 답변을 버리고 수치 없는 안내 문장으로 "
        "대체한다(`numeric_guard`).\n"
        "- **화면 이동**: `navigation.screen` 이 계약이고 `path` 는 제안이다.\n"
        "- **범위 밖 질문**: 충북 11개 시군, 2017-01~2024-12, 지방소멸대응기금 1종만 다룬다는 사실을 답한다."
    ),
    responses={200: {"content": {"application/json": {"example": CHAT_EXAMPLE}}}},
)
def chat(request: ChatRequest) -> Envelope[ChatData]:
    history = [turn.model_dump() for turn in request.history] if request.history else None
    result = chat_service.answer_question(request.question, history=history)
    settings = get_settings()

    notes = [
        "답변의 수치는 모두 called_endpoints 의 결과에서 인용했다.",
        *result.notes,
    ]
    if not settings.llm_active:
        notes.append(
            "LLM이 비활성 상태라 규칙 기반 라우터와 서술로 응답했다. 결과는 결정적이다."
        )

    return Envelope[ChatData](
        data=ChatData(
            question=request.question,
            routing=RoutingResult(**result.route.to_dict()),
            called_endpoints=[call.endpoint for call in result.tool_calls],
            tool_results=[ToolCallResult(**call.to_dict()) for call in result.tool_calls],
            answer=result.answer,
            narrator=result.narrator,
            navigation=Navigation(**result.navigation),
            citations=[Citation(**c) for c in result.citations],
            numeric_guard=NumericGuard(**result.numeric_guard),
            llm_enabled=settings.llm_active,
        ),
        meta=panel_meta(source="layer2_agent", data_status="derived", notes=notes),
    )
