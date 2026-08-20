"""7단계 완료 기준:
- 예시 질문 네 개가 모두 올바른 의도로 라우팅
- LLM 비활성 상태에서도 응답이 나옴
- 답변의 숫자가 도구 결과에 없으면 거부됨
"""

from __future__ import annotations

import pytest

from app.services import chat as chat_service
from app.services.nlu import (
    INTENT_CAUSAL,
    INTENT_COMPARISON,
    INTENT_EVIDENCE,
    INTENT_FUND,
    INTENT_OUT_OF_SCOPE,
    INTENT_PROPOSAL,
    INTENT_TIMESERIES,
    route_with_rules,
)


def ask(client, question: str, history=None) -> dict:
    payload = {"question": question}
    if history:
        payload["history"] = history
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ── 프론트 예시 질문 네 개 ────────────────────────────────────────


@pytest.mark.parametrize(
    ("question", "expected_intent"),
    [
        ("제천시 집행률", INTENT_FUND),
        ("가장 효과 좋은 사업 유형", INTENT_CAUSAL),
        ("충북 소멸위험 시군 총 배분액", INTENT_FUND),
        ("집행률과 인구 유출의 관계", INTENT_CAUSAL),
    ],
)
def test_mockup_example_questions_route_correctly(client, question, expected_intent):
    data = ask(client, question)
    assert data["routing"]["intent"] == expected_intent
    assert data["answer"]
    assert data["called_endpoints"]


def test_works_without_llm(client):
    """LLM 비활성 상태에서도 전체 파이프라인이 돈다."""
    data = ask(client, "제천시 집행률")
    assert data["llm_enabled"] is False
    assert data["routing"]["router"] == "rules"
    assert data["narrator"] == "rules"
    assert data["numeric_guard"]["passed"] is True


def test_jecheon_execution_rate_matches_layer1(client):
    data = ask(client, "제천시 집행률")
    regions_call = next(
        call for call in data["tool_results"] if call["endpoint"].endswith("/regions")
    )
    row = next(r for r in regions_call["data"]["regions"] if r["region"] == "제천시")
    assert f"{row['execution_rate_pct']:.1f}" in data["answer"]
    assert "성과 지표가 아닙니다" in data["answer"]


def test_total_allocation_answer_uses_dedup_total(client, panel):
    data = ask(client, "충북 소멸위험 시군 총 배분액")
    summary = next(
        call for call in data["tool_results"] if call["endpoint"].endswith("/summary")
    )
    expected = panel.fund_year_frame(2024)["fund_allocation_million_krw"].sum()
    assert summary["data"]["total_allocation_million_krw"] == pytest.approx(expected)
    assert f"{expected:,.0f}" in data["answer"]


def test_causal_answer_never_claims_significance(client):
    """p=0.4631 을 유의한 결과처럼 서술하지 않는다."""
    for question in ("가장 효과 좋은 사업 유형", "집행률과 인구 유출의 관계", "기금 효과가 있었나요"):
        data = ask(client, question)
        answer = data["answer"]
        assert "유의하지" in answer or "말할 수 없" in answer
        assert "유의합니다" not in answer
        assert "효과가 있었습니다" not in answer
        assert "%p" not in answer  # 목업의 +2.3%p 표기를 따르지 않는다


def test_project_type_question_says_type_effect_not_estimated(client):
    data = ask(client, "가장 효과 좋은 사업 유형")
    assert "사업 유형별 효과는 아직 추정되지 않았습니다" in data["answer"]


# ── 라우팅 세부 ─────────────────────────────────────────────────


def test_region_aliases(client):
    for alias in ("제천", "제천시", "제천 시"):
        data = ask(client, f"{alias} 집행률")
        assert data["routing"]["regions"] == ["제천시"]


def test_intent_coverage(client):
    cases = {
        "제천시 청년 순이동률 추이": INTENT_TIMESERIES,
        "청주시와 제천시 청년 순이동률 비교": INTENT_COMPARISON,
        "청년 주거 사업 근거 문서 보여줘": INTENT_EVIDENCE,
        "2026년 어디에 투자해야 하나요": INTENT_PROPOSAL,
        "오늘 서울 날씨 알려줘": INTENT_OUT_OF_SCOPE,
    }
    for question, expected in cases.items():
        assert ask(client, question)["routing"]["intent"] == expected


def test_year_and_metric_slots(client):
    data = ask(client, "2023년 제천시 집행률")
    assert data["routing"]["year"] == 2023
    summary = next(c for c in data["tool_results"] if c["endpoint"].endswith("/summary"))
    assert summary["data"]["year"] == 2023

    series = ask(client, "제천시 고령화율 추이")
    assert series["routing"]["metric"] == "aged_population_ratio_pct"


def test_out_of_scope_states_coverage(client):
    data = ask(client, "부산 아파트 시세 알려줘")
    assert data["routing"]["intent"] == INTENT_OUT_OF_SCOPE
    assert "충북 11개 시군" in data["answer"]
    assert "2017-01~2024-12" in data["answer"]
    assert "지방소멸대응기금 1종" in data["answer"]
    assert data["numeric_guard"]["passed"] is True


def test_year_outside_fund_range_is_explained(client):
    data = ask(client, "2025년 집행률 알려줘")
    summary = next(c for c in data["tool_results"] if c["endpoint"].endswith("/summary"))
    assert summary["data"]["year"] == 2024  # 2025 값을 지어내지 않는다
    assert data["answer"]


def test_navigation_targets(client):
    assert ask(client, "제천시 집행률")["navigation"]["screen"] == "fund_dashboard"
    assert ask(client, "기금 효과 인과분석")["navigation"]["screen"] == "causal_analysis"
    assert ask(client, "2026년 투자 제안")["navigation"]["screen"] == "proposal"
    assert ask(client, "사업 근거 문서")["navigation"]["screen"] == "evidence"


def test_citations_reference_called_endpoints(client):
    data = ask(client, "제천시 집행률")
    endpoints = set(data["called_endpoints"])
    assert data["citations"]
    for citation in data["citations"]:
        assert citation["endpoint"] in endpoints
        assert citation["source"]


def test_evidence_citations_include_document_and_grade(client):
    data = ask(client, "고려인 이주정착 사업 근거 문서")
    document_citations = [c for c in data["citations"] if c["document"]]
    assert document_citations
    assert all(c["grade"] in {"A", "B", "C"} for c in document_citations)


def test_evidence_performance_question_excludes_grade_c(client):
    """2017~2024 성과 근거를 물으면 등급 C 사업을 인용하지 않는다."""
    data = ask(client, "2023년 성과의 근거 문서를 보여줘")
    search = next(c for c in data["tool_results"] if c["endpoint"] == "/api/evidence/search")
    assert search["data"]["purpose"] == "performance_2017_2024"
    assert all(hit["grade"] != "C" for hit in search["data"]["hits"])


def test_history_is_accepted(client):
    data = ask(
        client,
        "집행률은?",
        history=[
            {"role": "user", "content": "제천시에 대해 알려줘"},
            {"role": "assistant", "content": "제천시는 처치군입니다."},
        ],
    )
    assert data["answer"]


# ── 수치 검증 ───────────────────────────────────────────────────


def test_guard_accepts_numbers_present_in_tool_results():
    calls = [
        chat_service.ToolCall(
            endpoint="/api/test",
            params={},
            data={"execution_rate_pct": 40.86123, "total": 46400.0},
            meta={"as_of": "2024"},
        )
    ]
    allowed = chat_service.allowed_numbers(calls)
    assert chat_service.verify_numbers("집행률은 40.9%이고 총액은 46,400백만원입니다.", allowed) == []


def test_guard_allows_numbers_echoed_from_the_question():
    """질문에 있던 숫자를 되받는 것은 날조가 아니다.

    이걸 막으면 '2025년 데이터는 없습니다' 처럼 우리가 가장 원하는 답변이 폐기된다.
    """
    from app.services import llm

    calls = [
        chat_service.ToolCall(endpoint="/api/test", params={}, data={"year": 2024}, meta={})
    ]
    allowed = chat_service.allowed_numbers(calls) | chat_service.question_numbers(
        "2025년 제천시 집행률"
    )
    assert chat_service.verify_numbers("2025년 데이터는 없고 2024년까지만 있습니다.", allowed) == []


def test_echoed_question_numbers_are_reported(monkeypatch):
    """되받은 숫자는 허용하되, 어디서 왔는지 응답에 남긴다."""
    from app.services import llm

    monkeypatch.setattr(
        llm,
        "narrate",
        lambda *args, **kwargs: "2025년 기금 데이터는 아직 없습니다. 확인 가능한 마지막 연도는 2024년입니다.",
    )
    result = chat_service.answer_question("2025년 제천시 집행률")
    assert result.narrator == "llm"
    assert result.numeric_guard["passed"] is True
    assert "2025" in result.numeric_guard["numbers_echoed_from_question"]
    # 도구 결과에도 있는 2024는 되받은 숫자로 세지 않는다
    assert "2024" not in result.numeric_guard["numbers_echoed_from_question"]


def test_invented_numbers_still_rejected_even_if_question_has_numbers(monkeypatch):
    """질문에 숫자가 있어도 없는 수치를 새로 주장하면 여전히 걸린다."""
    from app.services import llm

    monkeypatch.setattr(
        llm, "narrate", lambda *args, **kwargs: "2025년 제천시 집행률은 78.5%입니다."
    )
    result = chat_service.answer_question("2025년 제천시 집행률")
    assert result.narrator != "llm"
    assert "78.5" in result.numeric_guard["rejected_numbers"]


def test_guard_rejects_invented_numbers():
    calls = [
        chat_service.ToolCall(
            endpoint="/api/test", params={}, data={"execution_rate_pct": 40.86}, meta={}
        )
    ]
    allowed = chat_service.allowed_numbers(calls)
    offending = chat_service.verify_numbers("집행률은 78.5%입니다.", allowed)
    assert offending == ["78.5"]


def test_guard_replaces_answer_when_llm_invents_numbers(monkeypatch, client):
    """LLM이 만든 숫자가 도구 결과에 없으면 그 답변을 쓰지 않는다."""
    from app.services import llm

    monkeypatch.setattr(
        llm, "narrate", lambda *args, **kwargs: "제천시 집행률은 99.9%로 전국 1등인 123456원입니다."
    )
    result = chat_service.answer_question("제천시 집행률")
    assert result.narrator != "llm"
    assert "99.9" not in result.answer
    assert result.numeric_guard["rejected_numbers"]


def test_guard_accepts_clean_llm_answer(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(
        llm,
        "narrate",
        lambda *args, **kwargs: "충북 11개 시군을 대상으로 하며 자세한 값은 카드에서 확인하세요.",
    )
    result = chat_service.answer_question("제천시 집행률")
    assert result.narrator == "llm"
    assert result.numeric_guard["passed"] is True


def test_every_answer_passes_the_guard(client):
    """모든 예시 질문에서 답변 수치가 도구 결과로 추적된다."""
    questions = [
        "제천시 집행률",
        "가장 효과 좋은 사업 유형",
        "충북 소멸위험 시군 총 배분액",
        "집행률과 인구 유출의 관계",
        "청주시와 제천시 청년 순이동률 비교",
        "제천시 청년 순이동률 추이",
        "청년 주거 사업 근거",
        "2026년 투자 제안",
        "서울 날씨",
    ]
    for question in questions:
        data = ask(client, question)
        assert data["numeric_guard"]["passed"] is True, (question, data["answer"])
        assert data["numeric_guard"]["rejected_numbers"] == []


def test_answers_are_deterministic_without_llm(client):
    first = ask(client, "제천시 집행률")["answer"]
    second = ask(client, "제천시 집행률")["answer"]
    assert first == second


def test_rule_router_is_importable_standalone():
    """LLM 모듈 없이도 라우터가 동작한다."""
    route = route_with_rules("제천시 집행률")
    assert route.intent == INTENT_FUND
    assert route.regions == ["제천시"]
    assert route.router == "rules"


def test_empty_question_is_rejected(client):
    response = client.post("/api/chat", json={"question": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
