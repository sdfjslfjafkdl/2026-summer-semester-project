"""Anthropic 호출 (Layer 2).

두 군데에서만 LLM을 쓴다.
  1) 라우팅   : 질문 → 구조화된 JSON(의도·슬롯). 스키마를 강제하고, 실패하면 규칙 라우터로 폴백.
  2) 서술     : 도구 결과를 문장으로. 숫자는 도구 결과에 있는 값만 쓰도록 지시하고,
                호출부(chat.py)가 후처리로 다시 검증한다. 검증에 걸리면 규칙 서술로 대체된다.

LLM_ENABLED=false 이거나 키가 없으면 두 함수 모두 조용히 폴백한다.
API 키 없이도 전체 파이프라인이 동작해야 한다는 요구사항이다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.data.metrics import TIMESERIES_METRIC_KEYS
from app.data.panel import get_panel
from app.services import nlu
from app.services.nlu import INTENT_LABELS_KO, INTENTS, Route, route_with_rules

logger = logging.getLogger(__name__)

ROUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "regions": {"type": "array", "items": {"type": "string"}},
        "region_group": {"anyOf": [{"type": "string", "enum": ["treatment", "control", "all"]}, {"type": "null"}]},
        "year": {"type": ["integer", "null"]},
        "metric": {"type": ["string", "null"]},
        "reasoning_ko": {"type": "string"},
    },
    "required": ["intent", "regions", "region_group", "year", "metric", "reasoning_ko"],
    "additionalProperties": False,
}

ROUTER_SYSTEM = """너는 충북 지방소멸대응기금 성과분석 API의 질의 라우터다.
사용자 질문을 읽고 어떤 분석 기능을 호출해야 하는지만 판정한다. 숫자를 만들거나 답을 지어내지 않는다.

의도 정의:
- fund_execution: 기금 배분액·집행액·집행률 등 집행 현황 조회
- metric_timeseries: 특정 지표의 시간 흐름 조회
- region_comparison: 시군 간 비교나 순위
- causal_analysis: 기금의 효과·인과·유의성·지표 간 관계
- evidence_search: 사업 추진근거 문서, 사업내역서, 등급 조회
- proposal: 차년도(2025년 이후) 투자계획 제안, 권장 사업 유형
- out_of_scope: 충북 11개 시군, 2017-01~2024-12, 지방소멸대응기금 1종 밖의 질문

규칙:
- regions 에는 아래 목록에 있는 정확한 시군 이름만 넣는다. 없으면 빈 배열.
- region_group 은 처치군(인구감소지역 6개)이면 treatment, 비교군이면 control, 충북 전체면 all, 아니면 null.
- metric 은 아래 지표 키 목록에 있는 값이거나 null.
- year 는 질문에 연도가 있으면 정수, 없으면 null."""

NARRATOR_SYSTEM = """너는 충북 지방소멸대응기금 성과분석 API의 답변 작성자다.

절대 규칙:
1. 숫자는 제공된 도구 결과(JSON)에 실재하는 값만 쓴다. 계산하거나 추정한 숫자를 쓰지 않는다.
2. 도구 결과에 없는 사실을 덧붙이지 않는다.
3. p값이 유의수준보다 크면 절대로 효과가 있다고 서술하지 않는다.
4. 집행률은 투입 진행률이며 성과 지표가 아니라는 관점을 지킨다. 성과 지표는 청년 순이동률이다.
5. 2025년 이후 값은 데이터에 없다. 없으면 없다고 말한다.
6. 한국어 3~5문장, 존댓말, 불릿 없이 서술한다.
7. 지역 간 비교에서는 비교 대상 각각의 핵심 수치를 대칭적으로 제시한다. 한쪽만 상세히 설명하고 다른 쪽을 뭉뚱그리지 않는다."""


def _client():  # noqa: ANN202
    from anthropic import Anthropic

    settings = get_settings()
    return Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=float(settings.llm_timeout_seconds),
        max_retries=1,
    )


def route_question(question: str) -> Route:
    """LLM 라우팅을 시도하고, 비활성·실패·스키마 위반이면 규칙 라우터로 폴백한다."""
    settings = get_settings()
    fallback = route_with_rules(question)
    if not settings.llm_active:
        return fallback

    panel = get_panel()
    try:
        response = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=ROUTER_SYSTEM
            + f"\n\n시군 목록: {', '.join(panel.region_names)}"
            + f"\n지표 키 목록: {', '.join(TIMESERIES_METRIC_KEYS)}",
            messages=[{"role": "user", "content": question}],
            output_config={"format": {"type": "json_schema", "schema": ROUTE_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        payload = json.loads(text)
    except Exception as exc:  # 네트워크·인증·파싱 무엇이든 규칙 폴백
        logger.warning("LLM 라우팅 실패, 규칙 라우터로 폴백합니다: %s", exc)
        return fallback

    intent = payload.get("intent")
    if intent not in INTENTS:
        logger.warning("LLM이 알 수 없는 의도를 반환했습니다: %r", intent)
        return fallback

    known = set(panel.region_names)
    regions = [r for r in payload.get("regions") or [] if r in known]
    metric = payload.get("metric")
    if metric not in TIMESERIES_METRIC_KEYS:
        metric = fallback.metric

    return Route(
        intent=intent,
        intent_label_ko=INTENT_LABELS_KO[intent],
        regions=regions or fallback.regions,
        region_group=payload.get("region_group") or fallback.region_group,
        year=payload.get("year") or fallback.year,
        metric=metric,
        fund_id="local-extinction" if intent == nlu.INTENT_FUND else None,
        confidence=0.9,
        router="llm",
        matched_keywords=fallback.matched_keywords,
        out_of_scope_reason=(
            payload.get("reasoning_ko") if intent == nlu.INTENT_OUT_OF_SCOPE else None
        ),
    )


def narrate(
    question: str,
    route: Route,
    tool_calls: list,
    history: list[dict] | None = None,
) -> str | None:
    """LLM 서술. 비활성이거나 실패하면 None 을 돌려주고 호출부가 규칙 서술을 쓴다."""
    settings = get_settings()
    if not settings.llm_active:
        return None

    payload = {
        "question": question,
        "routing": route.to_dict(),
        "tool_results": [call.to_dict() for call in tool_calls],
    }
    messages: list[dict] = []
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    messages.append(
        {
            "role": "user",
            "content": (
                "아래 도구 결과만 근거로 질문에 답하세요. "
                "여기 없는 숫자는 절대 쓰지 마세요.\n\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        }
    )

    try:
        response = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=NARRATOR_SYSTEM,
            messages=messages,
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()
    except Exception as exc:
        logger.warning("LLM 서술 실패, 규칙 서술로 폴백합니다: %s", exc)
        return None
