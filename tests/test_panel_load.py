"""1단계 완료 기준: 1,056행 적재, 지역 11개, 기간 2017-01~2024-12 확인."""

from __future__ import annotations

import pandas as pd
import pytest

from app.data.panel import (
    CONTROL_REGIONS,
    FUND_PER_CAPITA_COLUMNS,
    FUND_YEAR_CONSTANT_COLUMNS,
    STRUCTURAL_MISSING_YOY_ROWS,
    TREATED_REGIONS,
    PanelValidationError,
    _validate,
)


def test_panel_shape(panel):
    assert panel.row_count == 1056
    assert len(panel.regions) == 11
    assert panel.period_start == "2017-01"
    assert panel.period_end == "2024-12"
    assert panel.df["year_month"].nunique() == 96


def test_treatment_design_matches_readme(panel):
    assert set(panel.treated_regions) == set(TREATED_REGIONS)
    assert set(panel.control_regions) == set(CONTROL_REGIONS)
    assert len(panel.treated_regions) == 6
    assert len(panel.control_regions) == 5


def test_no_duplicate_region_month(panel):
    assert panel.df.duplicated(subset=["region", "year_month"]).sum() == 0


def test_structural_missing_is_preserved(panel):
    """employment_insured_yoy_pct 2017년 결측은 보간하지 않는다."""
    missing = panel.df["employment_insured_yoy_pct"].isna()
    assert int(missing.sum()) == STRUCTURAL_MISSING_YOY_ROWS
    assert set(panel.df.loc[missing, "year"].unique()) == {2017}


def test_fund_amount_columns_are_year_constant(panel):
    """기금 금액·사업수·비중은 지역-연도 내에서 12개월 동안 동일한 값이 반복된다."""
    grouped = panel.df.groupby(["region", "year"])
    for column in FUND_YEAR_CONSTANT_COLUMNS:
        varying = grouped[column].nunique(dropna=False)
        assert (varying <= 1).all(), f"{column} 이 지역-연도 안에서 변동합니다"


def test_per_capita_columns_vary_within_year(panel):
    """1인당 지표는 분모가 월별 인구라 지역-연도 안에서도 달라진다.

    따라서 원본 컬럼을 그대로 연도 대표값으로 쓰면 임의의 달을 집는 셈이 된다.
    fund_year_frame 은 연말 인구로 다시 계산한다.
    """
    grouped = panel.df[panel.df["year"] >= 2022].groupby(["region", "year"])
    for column in FUND_PER_CAPITA_COLUMNS:
        varying = grouped[column].nunique(dropna=False)
        assert (varying > 1).any(), f"{column} 이 월별로 변동하지 않습니다"


def test_fund_year_frame_recomputes_per_capita(panel):
    frame = panel.fund_year_frame(2023)
    assert len(frame) == 11
    row = frame.loc[frame["region"] == "제천시"].iloc[0]
    december_population = panel.df.loc[
        (panel.df["region"] == "제천시") & (panel.df["year_month"] == "2023-12"),
        "population_total",
    ].iloc[0]
    expected = row["fund_allocation_million_krw"] * 1_000_000 / december_population
    assert row["fund_allocation_per_capita_krw"] == pytest.approx(expected)


def test_validate_rejects_missing_column(panel):
    broken = panel.df.drop(columns=["fund_execution_rate"])
    with pytest.raises(PanelValidationError, match="필수 컬럼"):
        _validate(broken, panel.source_path)


def test_validate_rejects_interpolated_yoy(panel):
    """구조적 결측을 채운 데이터는 적재를 거부한다."""
    tampered = panel.df.copy()
    tampered["employment_insured_yoy_pct"] = tampered["employment_insured_yoy_pct"].fillna(0.0)
    with pytest.raises(PanelValidationError, match="구조적 결측"):
        _validate(tampered, panel.source_path)


def test_validate_rejects_wrong_row_count(panel):
    with pytest.raises(PanelValidationError, match="행 수"):
        _validate(pd.concat([panel.df, panel.df.head(1)]), panel.source_path)


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["panel_rows"] == 1056
    assert body["data"]["region_count"] == 11
    assert body["data"]["period_start"] == "2017-01"
    assert body["data"]["period_end"] == "2024-12"
    assert body["meta"]["data_status"] == "actual"
