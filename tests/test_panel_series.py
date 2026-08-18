"""3단계: 패널 시계열과 그룹 시계열."""

from __future__ import annotations

import pytest

METRIC = "youth_net_migration_rate_per_1000"


def test_timeseries_default_covers_all_regions_and_months(client):
    body = client.get("/api/panel/timeseries").json()
    series = body["data"]["series"]
    assert len(series) == 11
    assert all(s["point_count"] == 96 for s in series)
    assert body["meta"]["data_status"] == "actual"


def test_timeseries_values_match_panel(client, panel):
    body = client.get(
        "/api/panel/timeseries",
        params={"regions": "제천시", "metric": METRIC, "from": "2024-01", "to": "2024-03"},
    ).json()
    points = body["data"]["series"][0]["points"]
    assert [p["period"] for p in points] == ["2024-01", "2024-02", "2024-03"]
    expected = panel.df.loc[
        (panel.df["region"] == "제천시") & (panel.df["year_month"].between("2024-01", "2024-03")),
        METRIC,
    ].tolist()
    assert [p["value"] for p in points] == pytest.approx(expected)


def test_timeseries_multiple_regions_preserve_request_order(client):
    body = client.get(
        "/api/panel/timeseries", params={"regions": "제천시,청주시", "from": "2024-01", "to": "2024-02"}
    ).json()
    assert [s["region"] for s in body["data"]["series"]] == ["제천시", "청주시"]
    assert body["data"]["series"][0]["is_treated"] is True
    assert body["data"]["series"][1]["is_treated"] is False


def test_structural_missing_is_null_not_interpolated(client):
    body = client.get(
        "/api/panel/timeseries",
        params={
            "regions": "제천시",
            "metric": "employment_insured_yoy_pct",
            "from": "2017-01",
            "to": "2017-12",
        },
    ).json()
    values = [p["value"] for p in body["data"]["series"][0]["points"]]
    assert values == [None] * 12
    assert body["data"]["series"][0]["missing_count"] == 12


def test_yearly_aggregation_uses_sum_for_flow_metrics(client, panel):
    body = client.get(
        "/api/panel/timeseries",
        params={
            "regions": "제천시",
            "metric": "youth_net_migration_20_39",
            "from": "2024-01",
            "to": "2024-12",
            "freq": "year",
        },
    ).json()
    points = body["data"]["series"][0]["points"]
    assert len(points) == 1 and points[0]["period"] == "2024"
    expected = panel.df.loc[
        (panel.df["region"] == "제천시") & (panel.df["year"] == 2024), "youth_net_migration_20_39"
    ].sum()
    assert points[0]["value"] == pytest.approx(expected)
    assert body["data"]["metric"]["aggregation"] == "sum"
    assert body["meta"]["data_status"] == "derived"


def test_quarterly_aggregation_uses_mean_for_rate_metrics(client, panel):
    body = client.get(
        "/api/panel/timeseries",
        params={"regions": "제천시", "metric": METRIC, "from": "2024-01", "to": "2024-06", "freq": "quarter"},
    ).json()
    points = body["data"]["series"][0]["points"]
    assert [p["period"] for p in points] == ["2024-Q1", "2024-Q2"]
    expected = panel.df.loc[
        (panel.df["region"] == "제천시") & (panel.df["year_month"].between("2024-01", "2024-03")),
        METRIC,
    ].mean()
    assert points[0]["value"] == pytest.approx(expected)


def test_out_of_range_window_is_unavailable(client):
    """2025년은 패널에 없다. 빈 계열과 unavailable 로 답한다."""
    body = client.get(
        "/api/panel/timeseries", params={"regions": "제천시", "from": "2025-01", "to": "2025-12"}
    ).json()
    assert body["meta"]["data_status"] == "unavailable"
    assert body["data"]["series"][0]["points"] == []
    assert any("2025" in note for note in body["meta"]["notes"])


def test_unknown_region_lists_allowed_values(client):
    response = client.get("/api/panel/timeseries", params={"regions": "서울시"})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "unknown_region"
    assert len(error["allowed_values"]) == 11


def test_unknown_metric_lists_allowed_values(client):
    response = client.get("/api/panel/timeseries", params={"metric": "gdp"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_metric"


def test_fund_metric_rejected_for_timeseries(client):
    """기금 변수는 연도 단위라 월 시계열 대상이 아니다."""
    response = client.get("/api/panel/timeseries", params={"metric": "fund_execution_rate"})
    assert response.status_code == 404
    assert "fund_execution_rate" not in response.json()["error"]["allowed_values"]


def test_invalid_period_format(client):
    response = client.get("/api/panel/timeseries", params={"from": "2024"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_period"


def test_reversed_range_rejected(client):
    response = client.get("/api/panel/timeseries", params={"from": "2024-12", "to": "2017-01"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_period_range"


def test_group_timeseries_is_simple_region_average(client, panel):
    body = client.get("/api/panel/group-timeseries", params={"from": "2024-12", "to": "2024-12"}).json()
    point = body["data"]["points"][0]
    december = panel.df.loc[panel.df["year_month"] == "2024-12"]
    expected_treated = december.loc[december["is_treated"] == 1, METRIC].mean()
    expected_control = december.loc[december["is_treated"] == 0, METRIC].mean()
    assert point["treatment_mean"] == pytest.approx(expected_treated)
    assert point["control_mean"] == pytest.approx(expected_control)
    assert point["difference"] == pytest.approx(expected_treated - expected_control)
    assert point["treatment_region_count"] == 6
    assert point["control_region_count"] == 5


def test_group_timeseries_documents_calculation_and_design(client):
    body = client.get("/api/panel/group-timeseries", params={"freq": "year"}).json()
    notes = " ".join(body["meta"]["notes"])
    assert "단순평균" in notes
    assert "처치군 6개" in notes or "6개" in notes
    assert body["data"]["treatment_start_period"] == "2022-01"
    assert len(body["data"]["treatment_regions"]) == 6
    assert len(body["data"]["control_regions"]) == 5
    assert [p["period"] for p in body["data"]["points"]] == [str(y) for y in range(2017, 2025)]


def test_group_timeseries_not_population_weighted(client, panel):
    """청주시 인구가 커도 그룹 평균을 지배하지 않아야 한다."""
    body = client.get("/api/panel/group-timeseries", params={"from": "2024-12", "to": "2024-12"}).json()
    december = panel.df.loc[panel.df["year_month"] == "2024-12"]
    control = december.loc[december["is_treated"] == 0]
    weighted = (control[METRIC] * control["youth_population_20_39"]).sum() / control[
        "youth_population_20_39"
    ].sum()
    assert body["data"]["points"][0]["control_mean"] != pytest.approx(weighted)
