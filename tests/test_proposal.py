"""6단계: 규칙 기반 차년도 제안."""

from __future__ import annotations

import pytest

from app.services.proposal import (
    DIRECTION_EXPAND,
    DIRECTION_FIX_EXECUTION,
    LOW_EXECUTION_RATE,
    TYPE_INFLOW,
    TYPE_SETTLEMENT,
    diagnose,
    recommend_type,
)


def test_proposal_covers_all_regions(client):
    body = client.get("/api/proposal", params={"year": 2026}).json()
    proposals = body["data"]["proposals"]
    assert len(proposals) == 11
    ranked = [p for p in proposals if p["priority_rank"] is not None]
    assert len(ranked) == 6  # 기금 배분 대상 6개 시군만 순위를 매긴다
    assert [p["priority_rank"] for p in ranked] == [1, 2, 3, 4, 5, 6]
    assert all(p["fund_recipient"] for p in ranked)


def test_proposal_marks_itself_as_not_causal(client):
    """유의하지 않은 추정 결과를 근거처럼 쓰지 않는다는 사실을 필드로 명시한다."""
    body = client.get("/api/proposal").json()
    basis = body["data"]["basis"]
    assert basis["is_causal_estimate"] is False
    assert "확정된 인과효과가 아니" in basis["statement_ko"]
    assert "0.4631" in basis["statement_ko"]
    assert basis["based_on_years"] == [2022, 2023, 2024]
    assert len(basis["rules"]) >= 3
    assert body["meta"]["data_status"] == "derived"


def test_every_proposal_shows_the_numbers_behind_it(client):
    proposals = client.get("/api/proposal").json()["data"]["proposals"]
    for item in proposals:
        drivers = {d["metric"]: d for d in item["drivers"]}
        assert "youth_net_migration_rate_per_1000" in drivers
        assert "fund_execution_rate" in drivers
        assert "fund_allocation_per_capita_krw" in drivers
        assert all(d["unit"] for d in item["drivers"])
        assert item["rationale_ko"]
        assert "명/천명" in item["rationale_ko"]


def test_recommendation_follows_diagnosis(client, panel):
    diagnoses = {d.region: d for d in diagnose(panel)}
    proposals = client.get("/api/proposal").json()["data"]["proposals"]
    for item in proposals:
        diagnosis = diagnoses[item["region"]]
        expected_type, _ = recommend_type(diagnosis)
        assert item["recommended_project_type"] == expected_type
        # 유출 주도 → 정착·정주형, 유입 부족 주도 → 유입 확대형
        if expected_type == TYPE_SETTLEMENT:
            assert diagnosis.out_rate_gap > diagnosis.in_rate_gap
        if expected_type == TYPE_INFLOW:
            assert diagnosis.in_rate_gap > diagnosis.out_rate_gap


def test_low_execution_regions_are_not_told_to_expand(client, panel):
    """집행률이 낮은 곳에 배분 확대를 권하지 않는다."""
    diagnoses = {d.region: d for d in diagnose(panel)}
    proposals = client.get("/api/proposal").json()["data"]["proposals"]
    for item in proposals:
        rate = diagnoses[item["region"]].execution_rate
        if rate is not None and rate < LOW_EXECUTION_RATE and item["fund_recipient"]:
            assert item["allocation_direction"] == DIRECTION_FIX_EXECUTION
            assert item["allocation_direction"] != DIRECTION_EXPAND


def test_non_recipient_regions_are_diagnosed_but_not_ranked(client):
    proposals = client.get("/api/proposal").json()["data"]["proposals"]
    non_recipients = [p for p in proposals if not p["fund_recipient"]]
    assert len(non_recipients) == 5
    for item in non_recipients:
        assert item["priority_rank"] is None
        assert item["priority_level"] == "not_ranked"
        assert "해당 없음" in item["allocation_direction"]
        assert item["rationale_ko"]  # 진단 자체는 제공한다


def test_score_components_are_percentiles(client):
    ranked = [
        p for p in client.get("/api/proposal").json()["data"]["proposals"] if p["priority_rank"]
    ]
    for item in ranked:
        components = item["score_components"]
        assert all(0.0 <= v <= 1.0 for v in components.values())
        expected = (
            45 * components["level"]
            + 30 * components["trend"]
            + 25 * components["allocation_gap"]
        )
        assert item["priority_score"] == pytest.approx(expected, abs=0.01)


def test_evidence_links_carry_grade(client):
    proposals = client.get("/api/proposal").json()["data"]["proposals"]
    jecheon = next(p for p in proposals if p["region"] == "제천시")
    assert jecheon["evidence_links"]
    for link in jecheon["evidence_links"]:
        assert link["grade"] in {"A", "B", "C"}
        assert link["document"] and link["excerpt"]
    # 근거 문서가 없는 시군은 빈 목록이며, 없는 근거를 지어내지 않는다
    others = [p for p in proposals if p["region"] != "제천시"]
    assert all(p["evidence_links"] == [] for p in others)


def test_grade_c_is_allowed_for_2026_proposal(client):
    """등급 C 사업은 과거 성과 근거로는 못 쓰지만 2026 제안 근거로는 쓸 수 있다."""
    body = client.get("/api/proposal", params={"year": 2026}).json()
    links = [
        link
        for item in body["data"]["proposals"]
        for link in item["evidence_links"]
    ]
    assert links
    assert any(link["usable_for_performance_2017_2024"] is False for link in links) or all(
        link["grade"] in {"A", "B", "C"} for link in links
    )


def test_past_year_is_rejected_with_guidance(client):
    response = client.get("/api/proposal", params={"year": 2024})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_proposal_year"
    assert "2025" in error["allowed_values"]


def test_proposal_is_deterministic(client):
    first = client.get("/api/proposal").json()["data"]["proposals"]
    second = client.get("/api/proposal").json()["data"]["proposals"]
    assert [(p["region"], p["priority_score"]) for p in first] == [
        (p["region"], p["priority_score"]) for p in second
    ]


def test_no_2025_panel_values_are_invented(client, panel):
    """제안은 2022~2024 데이터로만 만든다."""
    assert max(panel.available_years) == 2024
    body = client.get("/api/proposal", params={"year": 2026}).json()
    assert body["data"]["basis"]["based_on_years"] == [2022, 2023, 2024]
    assert body["meta"]["as_of"] == "2024-12"
