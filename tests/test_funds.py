"""2단계 완료 기준:
- 지역-연도 중복 제거 집계 테스트 통과
- 2025 요청이 unavailable 로 반환
"""

from __future__ import annotations

import pytest

FUND = "local-extinction"


def test_dedup_aggregation_is_not_twelve_times(panel):
    """월별 합산은 지역-연도 합산의 정확히 12배가 된다. 우리는 후자를 쓴다."""
    year = 2024
    monthly_sum = panel.df.loc[panel.df["year"] == year, "fund_allocation_million_krw"].sum()
    dedup_sum = panel.fund_year_frame(year)["fund_allocation_million_krw"].sum()
    assert monthly_sum == pytest.approx(dedup_sum * 12)
    assert dedup_sum == pytest.approx(46400.0)


def test_fund_year_frame_has_one_row_per_region(panel):
    for year in (2022, 2023, 2024):
        frame = panel.fund_year_frame(year)
        assert len(frame) == 11
        assert frame["region"].is_unique


def test_summary_matches_manual_dedup_totals(client, panel):
    response = client.get(f"/api/funds/{FUND}/summary", params={"year": 2024})
    assert response.status_code == 200
    body = response.json()
    data, meta = body["data"], body["meta"]

    frame = panel.fund_year_frame(2024)
    expected_allocation = float(frame["fund_allocation_million_krw"].sum())
    expected_execution = float(frame["fund_execution_million_krw"].sum())

    assert data["total_allocation_million_krw"] == pytest.approx(expected_allocation)
    assert data["total_execution_million_krw"] == pytest.approx(expected_execution)
    assert data["execution_rate"] == pytest.approx(expected_execution / expected_allocation)
    assert data["execution_rate_pct"] == pytest.approx(data["execution_rate"] * 100)
    assert data["recipient_region_count"] == 6
    assert data["region_count"] == 11
    assert meta["data_status"] == "derived"


def test_summary_year_over_year_change(client, panel):
    current = client.get(f"/api/funds/{FUND}/summary", params={"year": 2024}).json()["data"]
    previous = client.get(f"/api/funds/{FUND}/summary", params={"year": 2023}).json()["data"]
    assert current["previous_year"] == 2023
    assert current["previous_execution_rate_pct"] == pytest.approx(previous["execution_rate_pct"])
    assert current["execution_rate_change_pp"] == pytest.approx(
        current["execution_rate_pct"] - previous["execution_rate_pct"]
    )
    assert current["allocation_change_million_krw"] == pytest.approx(
        current["total_allocation_million_krw"] - previous["total_allocation_million_krw"]
    )


def test_first_fund_year_has_no_previous_year(client):
    data = client.get(f"/api/funds/{FUND}/summary", params={"year": 2022}).json()["data"]
    assert data["previous_year"] is None
    assert data["execution_rate_change_pp"] is None


def test_2025_is_unavailable_not_estimated(client):
    """목업 대시보드는 2025를 표시하지만 패널은 2024까지다. 값을 만들어내지 않는다."""
    response = client.get(f"/api/funds/{FUND}/summary", params={"year": 2025})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["data_status"] == "unavailable"
    assert body["data"]["total_allocation_million_krw"] is None
    assert body["data"]["execution_rate_pct"] is None
    assert body["data"]["available_years"] == [2022, 2023, 2024]
    assert any("2025" in note for note in body["meta"]["notes"])


def test_2025_regions_is_unavailable(client):
    body = client.get(f"/api/funds/{FUND}/regions", params={"year": 2025}).json()
    assert body["meta"]["data_status"] == "unavailable"
    assert body["data"]["regions"] == []


def test_pre_fund_year_is_unavailable(client):
    """기금은 2022년부터다. 2021년은 0원이 아니라 데이터 없음으로 다룬다."""
    body = client.get(f"/api/funds/{FUND}/summary", params={"year": 2021}).json()
    assert body["meta"]["data_status"] == "unavailable"


def test_regions_endpoint_shape(client):
    body = client.get(f"/api/funds/{FUND}/regions", params={"year": 2024}).json()
    rows = body["data"]["regions"]
    assert len(rows) == 11
    treated = [r for r in rows if r["is_treated"]]
    assert len(treated) == 6
    # 배분액 0인 비교군은 집행률이 정의되지 않는다
    control = [r for r in rows if not r["is_treated"]]
    assert all(r["allocation_million_krw"] == 0 for r in control)
    assert all(r["execution_rate"] is None for r in control)
    # 집행률 내림차순, null 은 뒤로
    rates = [r["execution_rate"] for r in rows if r["execution_rate"] is not None]
    assert rates == sorted(rates, reverse=True)
    assert [r["execution_rate"] for r in rows[-5:]] == [None] * 5


def test_region_per_capita_uses_year_end_population(client, panel):
    rows = client.get(f"/api/funds/{FUND}/regions", params={"year": 2024}).json()["data"]["regions"]
    row = next(r for r in rows if r["region"] == "제천시")
    december_population = panel.df.loc[
        (panel.df["region"] == "제천시") & (panel.df["year_month"] == "2024-12"),
        "population_total",
    ].iloc[0]
    assert row["population_total"] == pytest.approx(december_population)
    assert row["allocation_per_capita_krw"] == pytest.approx(
        row["allocation_million_krw"] * 1_000_000 / december_population
    )


def test_trend_covers_fund_years_only(client):
    body = client.get(f"/api/funds/{FUND}/trend").json()
    points = body["data"]["points"]
    assert [p["year"] for p in points] == [2022, 2023, 2024]
    assert points[0]["execution_rate_change_pp"] is None
    assert points[1]["execution_rate_change_pp"] == pytest.approx(
        points[1]["execution_rate_pct"] - points[0]["execution_rate_pct"]
    )
    assert all(p["recipient_region_count"] == 6 for p in points)


def test_trend_totals_match_summary(client):
    trend = client.get(f"/api/funds/{FUND}/trend").json()["data"]["points"]
    for point in trend:
        summary = client.get(
            f"/api/funds/{FUND}/summary", params={"year": point["year"]}
        ).json()["data"]
        assert point["total_allocation_million_krw"] == pytest.approx(
            summary["total_allocation_million_krw"]
        )
        assert point["execution_rate_pct"] == pytest.approx(summary["execution_rate_pct"])


def test_unknown_fund_returns_allowed_values(client):
    response = client.get("/api/funds/no-such-fund/summary", params={"year": 2024})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "unknown_fund"
    assert error["allowed_values"] == ["local-extinction"]


def test_meta_regions(client):
    body = client.get("/api/meta/regions").json()
    assert len(body["data"]["regions"]) == 11
    assert len(body["data"]["treated_regions"]) == 6
    assert "제천시" in body["data"]["treated_regions"]
    assert "청주시" in body["data"]["control_regions"]


def test_meta_metrics_have_definitions(client):
    body = client.get("/api/meta/metrics").json()
    metrics = body["data"]["metrics"]
    assert body["data"]["primary_outcome_key"] == "youth_net_migration_rate_per_1000"
    assert all(m["definition"] and m["unit"] and m["label_ko"] for m in metrics)
    keys = {m["key"] for m in metrics}
    assert "youth_net_migration_rate_per_1000" in keys
    assert "fund_execution_rate" in keys
    # 기금 지표는 월 시계열 대상이 아니다
    fund_metric = next(m for m in metrics if m["key"] == "fund_execution_rate")
    assert fund_metric["timeseries_available"] is False
