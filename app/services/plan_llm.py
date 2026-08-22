"""계획서의 문장 생성과 수정 (Layer 2).

LLM 은 두 곳에서만 쓴다.
  1) assisted 섹션: 담당자가 준 재료를 서식 톤의 문장으로 다듬는다.
  2) revise: 수정 지시문을 반영해 섹션 본문을 다시 쓴다.

키가 없거나 호출이 실패하면 템플릿으로 폴백한다. auto 섹션 채움과 manual 구획 생성은
LLM 과 무관하게 그대로 동작한다. 어느 경로든 결과는 수치 가드를 거친다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.data.plan_sections import PlanSection, SECTIONS
from app.services.llm import display_round
from app.services.plan_store import StoredPlan

logger = logging.getLogger(__name__)

_llm_used = False

SYSTEM = """너는 지방자치단체의 지방소멸대응기금 투자계획서 작성을 돕는 편집자다.

절대 규칙:
1. 숫자는 제공된 도구 결과(JSON)나 담당자 입력에 실재하는 값만 쓴다. 새로 계산하거나 추정하지 않는다.
2. 도구 결과에 없는 사실을 지어내지 않는다. 담당자가 주지 않은 사업명, 금액, 일정, 기관명을 만들지 않는다.
3. 기금 투입이 인구 유출을 막았다는 식으로 인과효과를 단정하지 않는다.
   1차 이중차분 추정은 통계적으로 유의하지 않다.
4. 집행률은 투입 진행률이며 성과 지표가 아니다. 성과 지표는 청년 순이동률이다.
5. 공문서 문체로 쓴다. 개조식(○, -)을 쓰고 과장 표현을 넣지 않는다.
6. 담당자가 준 재료 밖으로 내용을 늘리지 않는다. 재료가 부족하면 부족한 채로 짧게 쓴다."""


def llm_used() -> bool:
    return _llm_used


def _client():  # noqa: ANN202
    from anthropic import Anthropic

    settings = get_settings()
    return Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=float(settings.llm_timeout_seconds),
        max_retries=1,
    )


def _context(plan: StoredPlan, limit: int = 6) -> list[dict]:
    """LLM 에 넘길 도구 결과. 표시용으로 반올림해 원본 정밀도가 새어나가지 않게 한다."""
    return display_round([
        {"endpoint": call["endpoint"], "data": call["data"]}
        for call in plan.tool_results[:limit]
    ])


def _template_assisted(section: PlanSection, content: str, values: dict | None) -> str:
    """LLM 없이 만드는 문장. 담당자 입력을 서식 구조에 배치만 한다."""
    lines: list[str] = []
    if values:
        for key, raw in values.items():
            lines.append(f"○ ({key}) {raw}")
    for block in content.strip().splitlines():
        block = block.strip()
        if not block:
            continue
        lines.append(block if block.startswith(("○", "-", "·", "※")) else f"○ {block}")
    return "\n".join(lines)


def compose_assisted(
    section: PlanSection,
    content: str,
    values: dict | None,
    plan: StoredPlan,
) -> str:
    """assisted 섹션 본문 생성. 실패하면 템플릿으로 떨어진다."""
    global _llm_used
    _llm_used = False
    fallback = _template_assisted(section, content, values)

    settings = get_settings()
    if not settings.llm_active:
        return fallback

    payload = {
        "section": {
            "number": section.number,
            "title": section.title,
            "writing_guide": section.writing_guide,
            "evaluation_focus": section.evaluation_focus,
            "reference_note": section.reference_note,
        },
        "담당자_입력": content,
        "담당자_입력_값": values or {},
        "기존_본문": (plan.sections[section.section_id].content or ""),
        "도구_결과": _context(plan),
    }
    try:
        response = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=1500,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "아래 항목의 본문을 작성하세요. 담당자 입력을 기준으로 하고, "
                        "도구 결과에 있는 숫자만 인용하세요. 개조식으로 15줄 이내.\n\n"
                        + json.dumps(payload, ensure_ascii=False)
                    ),
                }
            ],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if text:
            _llm_used = True
            return text
    except Exception as exc:
        logger.warning("계획서 문장 생성 실패, 템플릿으로 폴백합니다: %s", exc)
    return fallback


# ── 수정 대상 판별 ──────────────────────────────────────────────

NUMBER_TOKENS = {
    "Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5", "Ⅵ": "6",
    "I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6",
}


def resolve_targets(instruction: str, plan: StoredPlan) -> list[str]:
    """지시문에서 수정 대상 섹션을 찾는다. 못 찾으면 빈 목록."""
    text = instruction.strip()
    normalized = text
    for roman, arabic in NUMBER_TOKENS.items():
        normalized = normalized.replace(roman, arabic)
    normalized = normalized.replace("－", "-").replace("–", "-")

    hits: list[str] = []
    for section in SECTIONS:
        number_plain = section.number
        for roman, arabic in NUMBER_TOKENS.items():
            number_plain = number_plain.replace(roman, arabic)
        number_plain = number_plain.replace("-①", "-1").replace("-②", "-2").replace(
            "-③", "-3").replace("-④", "-4").replace("-⑤", "-5")
        if number_plain and number_plain in normalized.replace(" ", ""):
            hits.append(section.section_id)
            continue
        if section.title.split("(")[0].strip() in text:
            hits.append(section.section_id)
    # 제목 키워드로도 한 번 더
    if not hits:
        for section in SECTIONS:
            keywords = [w for w in section.title.replace("·", " ").split() if len(w) >= 3]
            if any(word in text for word in keywords):
                hits.append(section.section_id)
    return list(dict.fromkeys(hits))


def revise_section(
    section: PlanSection,
    current: str | None,
    instruction: str,
    plan: StoredPlan,
) -> tuple[str, str]:
    """섹션 본문을 수정 지시에 맞게 다시 쓴다. (새 본문, 변경 요약)"""
    global _llm_used
    _llm_used = False
    settings = get_settings()

    if not settings.llm_active:
        marker = "※ 담당자 수정 지시"
        body = (current or "").rstrip()
        lines = [line for line in body.splitlines() if not line.startswith(marker)]
        lines.append(f"{marker}: {instruction.strip()}")
        return (
            "\n".join(lines).strip(),
            "LLM 이 비활성 상태라 지시문을 본문에 지시사항으로 남겼습니다. 문장 재작성은 하지 않았습니다.",
        )

    payload = {
        "section": {
            "number": section.number,
            "title": section.title,
            "writing_guide": section.writing_guide,
            "evaluation_focus": section.evaluation_focus,
        },
        "현재_본문": current or "",
        "수정_지시": instruction,
        "도구_결과": _context(plan),
    }
    try:
        response = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=1800,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "아래 항목의 본문을 수정 지시에 맞게 고쳐 주세요. "
                        "JSON 없이 두 부분으로만 답하세요.\n"
                        "첫 줄: '요약: ' 뒤에 무엇을 왜 바꿨는지 한 문장.\n"
                        "그다음 줄부터: 수정된 본문 전체.\n\n"
                        + json.dumps(payload, ensure_ascii=False)
                    ),
                }
            ],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if text:
            _llm_used = True
            first, _, rest = text.partition("\n")
            summary = first.replace("요약:", "").strip() or "수정 지시를 반영했습니다."
            body = rest.strip() or (current or "")
            return body, summary
    except Exception as exc:
        logger.warning("계획서 수정 실패, 본문을 유지합니다: %s", exc)

    return (current or ""), "수정 요청을 처리하지 못해 본문을 그대로 두었습니다."
