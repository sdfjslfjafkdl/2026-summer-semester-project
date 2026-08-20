"""자연어 질의 오케스트레이션 (Layer 2).

흐름: 라우팅(LLM 또는 규칙) → Layer 1 엔드포인트 호출 → 서술 → 수치 검증.

핵심 제약: 에이전트는 숫자를 만들지 않는다. 서술에 등장한 모든 숫자는 도구 호출 결과에
실재해야 하며, 그렇지 않으면 그 답변을 버리고 수치 없는 안내 문장으로 대체한다.
LLM이 만든 문장도 같은 검증을 통과해야만 사용된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.data.panel import FUND_YEARS, get_panel
from app.routers import analysis as analysis_router
from app.routers import evidence as evidence_router
from app.routers import funds as funds_router
from app.routers import panel as panel_router
from app.routers import proposal as proposal_router
from app.services import nlu
from app.services.nlu import (
    INTENT_CAUSAL,
    INTENT_COMPARISON,
    INTENT_EVIDENCE,
    INTENT_FUND,
    INTENT_OUT_OF_SCOPE,
    INTENT_PROPOSAL,
    INTENT_TIMESERIES,
    SCOPE_STATEMENT,
    Route,
)

DEFAULT_FUND = "local-extinction"
DEFAULT_METRIC = "youth_net_migration_rate_per_1000"
PROPOSAL_YEAR = 2026

# 프론트가 이동시킬 화면 키. path 는 참고용 제안이며 화면 키가 계약이다.
SCREENS = {
    INTENT_FUND: ("fund_dashboard", "/dashboard"),
    INTENT_TIMESERIES: ("causal_analysis", "/analysis"),
    INTENT_COMPARISON: ("causal_analysis", "/analysis"),
    INTENT_CAUSAL: ("causal_analysis", "/analysis"),
    INTENT_EVIDENCE: ("evidence", "/evidence"),
    INTENT_PROPOSAL: ("proposal", "/proposal"),
    INTENT_OUT_OF_SCOPE: ("chat", "/"),
}

NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")

GUARD_FALLBACK_ANSWER = (
    "죄송합니다. 답변 초안에 데이터로 확인되지 않은 숫자가 있어 그대로 내보내지 않았습니다. "
    "아래 조회 결과 카드의 값을 직접 확인해 주세요. 모든 수치는 조회된 엔드포인트에서만 인용합니다."
)


@dataclass
class ToolCall:
    endpoint: str
    params: dict[str, Any]
    data: dict[str, Any]
    meta: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "params": self.params,
            "data": self.data,
            "meta": self.meta,
        }


@dataclass
class ChatResult:
    route: Route
    tool_calls: list[ToolCall]
    answer: str
    citations: list[dict]
    navigation: dict
    numeric_guard: dict
    narrator: str
    notes: list[str] = field(default_factory=list)


# ── 도구 호출 ────────────────────────────────────────────────────


def _envelope_to_call(endpoint: str, params: dict, envelope) -> ToolCall:  # noqa: ANN001
    payload = envelope.model_dump()
    return ToolCall(endpoint=endpoint, params=params, data=payload["data"], meta=payload["meta"])


def _scope_call() -> ToolCall:
    panel = get_panel()
    return ToolCall(
        endpoint="internal:data_scope",
        params={},
        data={
            "region_count": len(panel.regions),
            "period_start": panel.period_start,
            "period_end": panel.period_end,
            "month_count": int(panel.df["year_month"].nunique()),
            "panel_rows": panel.row_count,
            "fund_count": 1,
            "fund_years": list(FUND_YEARS),
            "proposal_year": PROPOSAL_YEAR,
            "treated_region_count": len(panel.treated_regions),
            "control_region_count": len(panel.control_regions),
        },
        meta={"source": "chungbuk_monthly_model_panel_2017_2024.csv", "data_status": "actual"},
    )


def _fund_year(route: Route) -> int:
    if route.year and route.year in FUND_YEARS:
        return route.year
    return max(FUND_YEARS)


_FUND_WORDS = re.compile(r"집행|기금|배분|돈|예산|투입|썼|쓴")


def _is_fund_question(question: str) -> bool:
    """비교 질문이 기금·집행률에 관한 것인지 원문 질문으로 판단한다."""
    return bool(_FUND_WORDS.search(question))


def run_tools(route: Route, question: str = "") -> tuple[list[ToolCall], list[str]]:
    calls: list[ToolCall] = [_scope_call()]
    notes: list[str] = []
    panel = get_panel()

    if route.intent == INTENT_FUND:
        year = _fund_year(route)
        if route.year and route.year not in FUND_YEARS:
            notes.append(
                f"{route.year}년 기금 데이터는 없어 {year}년 기준으로 답했습니다. "
                f"기금 수록 연도는 {FUND_YEARS[0]}~{FUND_YEARS[-1]} 입니다."
            )
        params = {"fund_id": DEFAULT_FUND, "year": year}
        calls.append(
            _envelope_to_call(
                f"/api/funds/{DEFAULT_FUND}/summary",
                params,
                funds_router.fund_summary(fund_id=DEFAULT_FUND, year=year),
            )
        )
        calls.append(
            _envelope_to_call(
                f"/api/funds/{DEFAULT_FUND}/regions",
                params,
                funds_router.fund_regions(fund_id=DEFAULT_FUND, year=year),
            )
        )

    elif route.intent in (INTENT_TIMESERIES, INTENT_COMPARISON):
        # 지역 간 비교인데 질문이 기금·집행률에 관한 것이면, 패널 지표가 아니라
        # 지역별 기금 집행 현황을 함께 넘긴다. 새 계산 없이 기존 funds/regions 를 재사용한다.
        if route.intent == INTENT_COMPARISON and _is_fund_question(question):
            year = _fund_year(route)
            params = {"fund_id": DEFAULT_FUND, "year": year}
            calls.append(
                _envelope_to_call(
                    f"/api/funds/{DEFAULT_FUND}/regions",
                    params,
                    funds_router.fund_regions(fund_id=DEFAULT_FUND, year=year),
                )
            )
            notes.append(
                "지역 간 기금 비교이므로 집행률은 지역별 집행액÷배분액이며, "
                "성과 지표가 아니라 투입 진행률이다."
            )

        metric = route.metric or DEFAULT_METRIC
        regions = route.regions or (
            panel.treated_regions if route.region_group == "treatment" else panel.region_names
        )
        params = {
            "regions": ",".join(regions),
            "metric": metric,
            "from": "2017-01",
            "to": panel.period_end,
            "freq": "year",
        }
        calls.append(
            _envelope_to_call(
                "/api/panel/timeseries",
                params,
                panel_router.timeseries(
                    regions=params["regions"],
                    metric=metric,
                    from_="2017-01",
                    to=panel.period_end,
                    freq="year",
                ),
            )
        )

    elif route.intent == INTENT_CAUSAL:
        calls.append(_envelope_to_call("/api/analysis/did", {}, analysis_router.did()))
        calls.append(
            _envelope_to_call(
                "/api/analysis/diagnostics", {}, analysis_router.diagnostics()
            )
        )
        calls.append(
            _envelope_to_call(
                "/api/panel/group-timeseries",
                {"metric": DEFAULT_METRIC, "freq": "year"},
                panel_router.group_timeseries(
                    metric=DEFAULT_METRIC, from_="2017-01", to=panel.period_end, freq="year"
                ),
            )
        )

    elif route.intent == INTENT_EVIDENCE:
        query = route.metric or ""
        calls.append(
            _envelope_to_call(
                "/api/evidence/projects", {}, evidence_router.projects()
            )
        )

    elif route.intent == INTENT_PROPOSAL:
        calls.append(
            _envelope_to_call(
                "/api/proposal",
                {"year": PROPOSAL_YEAR},
                proposal_router.proposal(year=PROPOSAL_YEAR, include_evidence=True),
            )
        )

    return calls, notes


def run_evidence_search(question: str, route: Route) -> ToolCall:
    """근거 검색은 원문 질문을 검색어로 쓴다. 성과 질의면 등급 C를 제외한다."""
    purpose = "all"
    if re.search(r"20(1[7-9]|2[0-4])|과거|성과|효과", question):
        purpose = "performance_2017_2024"
    params = {"q": question, "purpose": purpose, "top_k": 5}
    return _envelope_to_call(
        "/api/evidence/search",
        params,
        evidence_router.search(q=question, grade=None, top_k=5, purpose=purpose),
    )


# ── 수치 검증 ────────────────────────────────────────────────────


def _collect_numbers(node: Any, sink: set[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        sink.add(float(node))
    elif isinstance(node, str):
        for token in NUMBER_PATTERN.findall(node):
            try:
                sink.add(float(token.replace(",", "")))
            except ValueError:
                continue
    elif isinstance(node, dict):
        for value in node.values():
            _collect_numbers(value, sink)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_numbers(value, sink)


def _as_float(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def question_numbers(question: str) -> set[float]:
    """질문에 등장한 숫자.

    사용자가 물은 값을 그대로 되받아 인용하는 것은 날조가 아니다. 오히려 이걸 막으면
    "2025년 데이터는 없습니다" 처럼 우리가 가장 원하는 답변이 '2025' 때문에 폐기된다.
    도구 결과에 없는 수치를 새로 주장하는 것은 여전히 걸린다.
    """
    numbers: set[float] = set()
    for token in NUMBER_PATTERN.findall(question):
        try:
            numbers.add(float(token.replace(",", "")))
        except ValueError:
            continue
    return numbers


def allowed_numbers(tool_calls: list[ToolCall]) -> set[float]:
    """도구 결과에 실재하는 숫자와, 그 값의 반올림·백분율 표기 변형."""
    raw: set[float] = set()
    for call in tool_calls:
        _collect_numbers(call.data, raw)
        _collect_numbers(call.meta, raw)

    allowed: set[float] = set()
    for value in raw:
        variants = [value, -value]
        for base in list(variants):
            for digits in range(0, 5):
                variants.append(round(base, digits))
            # 비율(0~1)을 퍼센트로 표기하는 경우
            variants.extend(round(base * 100, digits) for digits in range(0, 3))
        allowed.update(variants)
    return allowed


def verify_numbers(answer: str, allowed: set[float]) -> list[str]:
    """답변에 등장하지만 도구 결과에 없는 숫자를 돌려준다."""
    offending: list[str] = []
    for token in NUMBER_PATTERN.findall(answer):
        cleaned = token.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if not any(abs(value - candidate) < 1e-6 for candidate in allowed):
            offending.append(token)
    return offending


# ── 규칙 기반 서술 ──────────────────────────────────────────────


def _fmt(value: float | None, digits: int = 2, *, sign: bool = False) -> str:
    if value is None:
        return "값 없음"
    formatted = f"{value:+,.{digits}f}" if sign else f"{value:,.{digits}f}"
    return formatted


def _find(calls: list[ToolCall], endpoint: str) -> ToolCall | None:
    return next((c for c in calls if c.endpoint == endpoint), None)


def narrate_with_rules(question: str, route: Route, calls: list[ToolCall]) -> str:
    if route.intent == INTENT_OUT_OF_SCOPE:
        reason = route.out_of_scope_reason or "이 질문은 현재 데이터로 답할 수 없습니다."
        return (
            f"{reason} "
            "기금 집행 현황, 청년 순이동률 시계열, 시군 간 비교, 1차 인과분석 결과, "
            f"사업 근거 문서, {PROPOSAL_YEAR}년 투자 제안을 물어보실 수 있습니다."
        )

    if route.intent == INTENT_FUND:
        summary = _find(calls, f"/api/funds/{DEFAULT_FUND}/summary")
        regions_call = _find(calls, f"/api/funds/{DEFAULT_FUND}/regions")
        if not summary:
            return GUARD_FALLBACK_ANSWER
        data = summary.data
        year = data["year"]
        if summary.meta["data_status"] == "unavailable":
            return (
                f"{year}년 지방소멸대응기금 데이터는 이 패널에 없습니다. "
                f"수록 연도는 {', '.join(str(y) for y in data['available_years'])} 입니다."
            )

        if route.regions and regions_call:
            region = route.regions[0]
            row = next(
                (r for r in regions_call.data["regions"] if r["region"] == region), None
            )
            if row is None:
                return GUARD_FALLBACK_ANSWER
            if row["execution_rate_pct"] is None:
                return (
                    f"{region}은 {year}년 지방소멸대응기금 배분 대상이 아니어서 "
                    "배분액과 집행액이 0이고 집행률은 정의되지 않습니다. "
                    "이 기금은 인구감소지역으로 지정된 시군에 배분됩니다."
                )
            return (
                f"{region}의 {year}년 지방소멸대응기금 집행률은 "
                f"{_fmt(row['execution_rate_pct'], 1)}%입니다. "
                f"배분액 {_fmt(row['allocation_million_krw'], 0)}백만원 중 "
                f"{_fmt(row['execution_million_krw'], 0)}백만원을 집행했고 "
                f"미집행액은 {_fmt(row['unexecuted_million_krw'], 0)}백만원입니다. "
                f"같은 해 사업 수는 {_fmt(row['project_count'], 0)}건입니다. "
                "집행률은 투입 진행률이며 성과 지표가 아닙니다."
            )

        scope = "인구감소지역 6개 시군" if route.region_group == "treatment" else "충북 전체"
        return (
            f"{year}년 지방소멸대응기금 총 배분액은 "
            f"{_fmt(data['total_allocation_million_krw'], 0)}백만원, 집행액은 "
            f"{_fmt(data['total_execution_million_krw'], 0)}백만원으로 집행률은 "
            f"{_fmt(data['execution_rate_pct'], 1)}%입니다({scope} 기준). "
            f"배분을 받은 시군은 {data['recipient_region_count']}개이며, "
            "나머지 시군은 배분액이 0이라 집행률이 정의되지 않습니다. "
            "집행률은 투입 진행률이며 이 서비스의 성과 지표는 청년 순이동률입니다."
        )

    if route.intent in (INTENT_TIMESERIES, INTENT_COMPARISON):
        call = _find(calls, "/api/panel/timeseries")
        if not call or not call.data["series"]:
            return GUARD_FALLBACK_ANSWER
        metric = call.data["metric"]
        series = call.data["series"]

        if route.intent == INTENT_COMPARISON or len(series) > 2:
            ranked = sorted(
                (s for s in series if s["last_value"] is not None),
                key=lambda s: s["last_value"],
                reverse=True,
            )
            if not ranked:
                return GUARD_FALLBACK_ANSWER
            best, worst = ranked[0], ranked[-1]
            middle = ", ".join(
                f"{s['region']} {_fmt(s['last_value'], 2, sign=True)}" for s in ranked[1:-1][:3]
            )
            return (
                f"2024년 {metric['label_ko']}({metric['unit']}) 기준으로 "
                f"가장 높은 시군은 {best['region']}({_fmt(best['last_value'], 2, sign=True)}), "
                f"가장 낮은 시군은 {worst['region']}({_fmt(worst['last_value'], 2, sign=True)})입니다."
                + (f" 그 사이는 {middle} 순입니다." if middle else "")
            )

        first = series[0]
        return (
            f"{first['region']}의 {metric['label_ko']}은 2017년 연평균 "
            f"{_fmt(first['first_value'], 2, sign=True)}{metric['unit']}에서 2024년 "
            f"{_fmt(first['last_value'], 2, sign=True)}{metric['unit']}로 나타납니다. "
            f"전체 기간 평균은 {_fmt(first['mean'], 2, sign=True)}{metric['unit']}입니다."
        )

    if route.intent == INTENT_CAUSAL:
        did = _find(calls, "/api/analysis/did")
        if not did:
            return GUARD_FALLBACK_ANSWER
        effect = did.data["effect"]
        significance = did.data["significance"]
        design = did.data["design"]
        base = (
            f"1차 이중차분(DID) 추정에서 처치군 {design['treated_region_count']}개 시군의 "
            f"청년 순이동률은 비교군 {design['control_region_count']}개 시군 대비 "
            f"{_fmt(effect['coefficient'], 4, sign=True)}{effect['unit']}로 추정됐습니다. "
            f"{significance['statement_ko']} "
            f"군집 수가 {design['n_clusters']}개로 작아 이 추정은 탐색적 1차 결과입니다."
        )
        if "사업" in question and ("유형" in question or "종류" in question):
            base += (
                " 사업 유형별 효과는 아직 추정되지 않았습니다. 사업별 착수월이 확보되지 않아 "
                "유형별 비교가 불가능하며, 유형 권장은 /api/proposal 의 규칙 기반 진단으로 제공합니다."
            )
        if "집행률" in question:
            base += (
                " 집행률은 투입 진행률이라 성과 지표로 쓰지 않습니다. "
                "이 서비스는 청년 순이동률로 성과를 평가합니다."
            )
        return base

    if route.intent == INTENT_EVIDENCE:
        search = _find(calls, "/api/evidence/search")
        if not search or not search.data["hits"]:
            return (
                "질문과 맞는 근거 문서를 찾지 못했습니다. 현재 등록된 근거 문서는 "
                "제천시 사업내역서 3건과 사업 추진근거 등록부입니다."
            )
        top = search.data["hits"][0]
        excluded = search.data["excluded_grade_c_count"]
        text = (
            f"가장 관련 있는 근거는 '{top['project_name'] or top['document']}'"
            f"(등급 {top['grade']})이며, 출처는 {top['document']}"
            + (f" {top['page']}쪽" if top["page"] else "")
            + "입니다. 발췌: "
            + top["excerpt"][:120]
            + "…"
        )
        if excluded:
            text += (
                " 이 답변은 2017~2024 성과 근거 조회이므로 2025년 이후 시작한 등급 C 사업은 "
                "제외했습니다."
            )
        return text

    if route.intent == INTENT_PROPOSAL:
        call = _find(calls, "/api/proposal")
        if not call:
            return GUARD_FALLBACK_ANSWER
        ranked = [p for p in call.data["proposals"] if p["priority_rank"]][:3]
        parts = [
            f"{p['region']}(우선순위 {p['priority_rank']}위, {p['recommended_project_type']}, "
            f"배분 방향 {p['allocation_direction']})"
            for p in ranked
        ]
        return (
            f"{call.data['year']}년 투자 우선순위 상위는 " + ", ".join(parts) + "입니다. "
            "이 제안은 확정된 인과효과가 아니라 최근 3년 청년 순이동 지표와 집행 현황에 근거한 "
            "참고안입니다."
        )

    return GUARD_FALLBACK_ANSWER


# ── 인용 ────────────────────────────────────────────────────────


def build_citations(calls: list[ToolCall]) -> list[dict]:
    citations: list[dict] = []
    for call in calls:
        if call.endpoint == "internal:data_scope":
            continue
        citation = {
            "endpoint": call.endpoint,
            "source": call.meta.get("source", ""),
            "as_of": call.meta.get("as_of"),
            "data_status": call.meta.get("data_status"),
            "document": None,
            "page": None,
            "grade": None,
        }
        citations.append(citation)
        if call.endpoint == "/api/evidence/search":
            for hit in call.data.get("hits", [])[:3]:
                citations.append(
                    {
                        "endpoint": call.endpoint,
                        "source": hit["document"],
                        "as_of": call.meta.get("as_of"),
                        "data_status": call.meta.get("data_status"),
                        "document": hit["document"],
                        "page": hit["page"],
                        "grade": hit["grade"],
                    }
                )
    return citations


def build_navigation(route: Route) -> dict:
    screen, path = SCREENS.get(route.intent, ("chat", "/"))
    params: dict[str, Any] = {}
    if route.intent == INTENT_FUND:
        params = {"fund_id": DEFAULT_FUND, "year": _fund_year(route)}
        if route.regions:
            params["region"] = route.regions[0]
    elif route.intent in (INTENT_TIMESERIES, INTENT_COMPARISON):
        params = {"metric": route.metric or DEFAULT_METRIC}
        if route.regions:
            params["regions"] = route.regions
    elif route.intent == INTENT_PROPOSAL:
        params = {"year": PROPOSAL_YEAR}
    return {"screen": screen, "path": path, "params": params}


# ── 오케스트레이션 ──────────────────────────────────────────────


def answer_question(question: str, history: list[dict] | None = None) -> ChatResult:
    from app.services import llm

    route = llm.route_question(question)
    calls, notes = run_tools(route, question)
    if route.intent == INTENT_EVIDENCE:
        calls.append(run_evidence_search(question, route))

    fallback_answer = narrate_with_rules(question, route, calls)
    from_tools = allowed_numbers(calls)
    asked = question_numbers(question)
    allowed = from_tools | asked

    narrator = "rules"
    answer = fallback_answer
    llm_answer = llm.narrate(question, route, calls, history=history)
    guard_rejected: list[str] = []
    if llm_answer:
        offending = verify_numbers(llm_answer, allowed)
        if offending:
            guard_rejected = offending
            notes.append(
                "LLM이 만든 문장에 도구 결과에 없는 숫자가 있어 규칙 기반 서술로 대체했습니다."
            )
        else:
            answer = llm_answer
            narrator = "llm"

    offending_final = verify_numbers(answer, allowed)
    guard_passed = not offending_final
    if not guard_passed:
        # 규칙 서술조차 검증을 통과하지 못하면 수치 없는 안내로 대체한다.
        answer = GUARD_FALLBACK_ANSWER
        narrator = "guard_fallback"

    # 도구 결과가 아니라 질문에서 인용한 숫자는 따로 드러낸다. 어떤 수치가 어디서 왔는지
    # 추적할 수 있어야 하므로, 허용했다는 사실 자체를 응답에 남긴다.
    echoed = sorted(
        {
            token
            for token in NUMBER_PATTERN.findall(answer)
            if _as_float(token) is not None
            and any(abs(_as_float(token) - value) < 1e-6 for value in asked)
            and not any(abs(_as_float(token) - value) < 1e-6 for value in from_tools)
        }
    )

    return ChatResult(
        route=route,
        tool_calls=calls,
        answer=answer,
        citations=build_citations(calls),
        navigation=build_navigation(route),
        numeric_guard={
            "passed": guard_passed,
            "checked_numbers_in_answer": len(NUMBER_PATTERN.findall(answer)),
            "rejected_numbers": guard_rejected + offending_final,
            "numbers_echoed_from_question": echoed,
            "policy": (
                "답변의 모든 숫자는 호출된 Layer 1 엔드포인트 결과에 실재해야 한다. "
                "예외적으로 질문에 있던 숫자를 되받아 인용하는 것은 허용하며, "
                "그 숫자는 numbers_echoed_from_question 에 남긴다."
            ),
        },
        narrator=narrator,
        notes=notes,
    )
