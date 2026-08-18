"""기금 대시보드 계산 (Layer 1).

집계 규칙 하나만 지키면 된다: 기금 금액은 지역-연도 단위로 중복 제거한 뒤 합산한다.
패널이 연도값을 12개월에 반복 결합해 두었기 때문에, 월 단위 합산은 12배 과대계상이 된다.
"""

from __future__ import annotations

import math

import pandas as pd

from app.data.panel import FUND_YEARS, Panel
from app.errors import unknown_fund
from app.schemas.envelope import DataStatus, Meta
from app.schemas.funds import (
    FundInfo,
    FundRegionRow,
    FundRegionsData,
    FundSummaryData,
    FundTrendData,
    FundTrendPoint,
)

FUND_SOURCE = "chungbuk_monthly_model_panel_2017_2024.csv"

DEDUP_NOTE = (
    "기금 금액은 지역-연도 단위로 중복 제거한 뒤 합산했다. "
    "패널은 연도값을 12개월에 반복 결합한 구조여서 월별 합산 시 12배로 부풀려진다."
)
RATE_NOTE = "집행률은 총 집행액 ÷ 총 배분액으로 계산했다. 시군별 집행률의 단순평균이 아니다."
NOT_PERFORMANCE_NOTE = (
    "집행률은 투입 진행률이며 성과 지표가 아니다. "
    "이 서비스의 성과 평가 지표는 청년 순이동률(youth_net_migration_rate_per_1000)이다."
)
PER_CAPITA_NOTE = "1인당 지표는 해당 연도 연말(12월) 주민등록 총인구를 분모로 계산했다."
NON_RECIPIENT_NOTE = (
    "비교군 5개 시군(청주시, 충주시, 증평군, 진천군, 음성군)은 배분액이 0이어서 "
    "집행률이 정의되지 않는다(null)."
)


FUNDS: dict[str, FundInfo] = {
    "local-extinction": FundInfo(
        fund_id="local-extinction",
        name_ko="지방소멸대응기금",
        first_year=min(FUND_YEARS),
        last_year=max(FUND_YEARS),
    )
}


def get_fund(fund_id: str) -> FundInfo:
    fund = FUNDS.get(fund_id)
    if fund is None:
        raise unknown_fund(fund_id, list(FUNDS))
    return fund


def fund_years(fund: FundInfo) -> list[int]:
    return [y for y in FUND_YEARS if fund.first_year <= y <= fund.last_year]


def _f(value: object) -> float | None:
    """NaN 을 None 으로 바꿔 JSON 직렬화와 프론트 분기를 단순하게 한다."""
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    return None if math.isnan(number) else number


def _rate(execution: float, allocation: float) -> float | None:
    return execution / allocation if allocation > 0 else None


def _totals(frame: pd.DataFrame) -> dict[str, float]:
    allocation = float(frame["fund_allocation_million_krw"].sum())
    execution = float(frame["fund_execution_million_krw"].sum())
    return {
        "allocation": allocation,
        "execution": execution,
        "unexecuted": allocation - execution,
        "projects": float(frame["fund_project_count"].sum()),
        "recipients": int((frame["fund_allocation_million_krw"] > 0).sum()),
    }


def unavailable_meta(fund: FundInfo, year: int, panel: Panel) -> Meta:
    return Meta(
        source=FUND_SOURCE,
        as_of=str(fund.last_year),
        data_status="unavailable",
        notes=[
            f"{year}년 {fund.name_ko} 데이터는 이 패널에 없다. "
            f"수록 연도는 {fund.first_year}~{fund.last_year} 이다.",
            f"패널 전체 수록 기간은 {panel.period_start}~{panel.period_end} 이며, "
            "그 밖의 연도 값은 추정해 채우지 않는다.",
        ],
    )


def actual_meta(year: int | None, notes: list[str]) -> Meta:
    return Meta(
        source=FUND_SOURCE,
        as_of=str(year) if year is not None else str(max(FUND_YEARS)),
        data_status="derived",
        notes=notes,
    )


def summary(panel: Panel, fund: FundInfo, year: int) -> tuple[FundSummaryData, DataStatus, list[str]]:
    """연도별 총 배분액·집행액·집행률과 전년 대비 증감."""
    years = fund_years(fund)
    base = FundSummaryData(
        fund_id=fund.fund_id,
        fund_name=fund.name_ko,
        year=year,
        region_count=len(panel.regions),
        available_years=years,
    )
    if year not in years:
        return base, "unavailable", []

    current = _totals(panel.fund_year_frame(year))
    rate = _rate(current["execution"], current["allocation"])

    base.total_allocation_million_krw = current["allocation"]
    base.total_execution_million_krw = current["execution"]
    base.unexecuted_million_krw = current["unexecuted"]
    base.execution_rate = rate
    base.execution_rate_pct = None if rate is None else rate * 100
    base.recipient_region_count = current["recipients"]
    base.total_project_count = current["projects"]

    notes = [DEDUP_NOTE, RATE_NOTE, NOT_PERFORMANCE_NOTE, NON_RECIPIENT_NOTE]

    previous_year = year - 1
    if previous_year in years:
        previous = _totals(panel.fund_year_frame(previous_year))
        previous_rate = _rate(previous["execution"], previous["allocation"])
        base.previous_year = previous_year
        base.previous_execution_rate_pct = None if previous_rate is None else previous_rate * 100
        if rate is not None and previous_rate is not None:
            base.execution_rate_change_pp = (rate - previous_rate) * 100
        base.allocation_change_million_krw = current["allocation"] - previous["allocation"]
        base.execution_change_million_krw = current["execution"] - previous["execution"]
    else:
        notes.append(
            f"{previous_year}년은 이 기금의 수록 범위 밖이라 전년 대비 증감을 계산하지 않았다."
        )

    return base, "derived", notes


def by_region(panel: Panel, fund: FundInfo, year: int) -> tuple[FundRegionsData, DataStatus, list[str]]:
    years = fund_years(fund)
    base = FundRegionsData(
        fund_id=fund.fund_id,
        fund_name=fund.name_ko,
        year=year,
        available_years=years,
    )
    if year not in years:
        return base, "unavailable", []

    frame = panel.fund_year_frame(year)
    rows: list[FundRegionRow] = []
    for row in frame.itertuples():
        allocation = float(row.fund_allocation_million_krw)
        execution = float(row.fund_execution_million_krw)
        rate = _rate(execution, allocation)
        rows.append(
            FundRegionRow(
                region=str(row.region),
                region_role=str(row.region_role),
                is_treated=bool(row.is_treated),
                allocation_million_krw=allocation,
                execution_million_krw=execution,
                unexecuted_million_krw=allocation - execution,
                execution_rate=rate,
                execution_rate_pct=None if rate is None else rate * 100,
                project_count=float(row.fund_project_count),
                job_youth_project_count=float(row.fund_job_youth_project_count),
                settlement_service_project_count=float(row.fund_settlement_service_project_count),
                job_youth_share=float(row.fund_job_youth_share),
                settlement_service_share=float(row.fund_settlement_service_share),
                population_total=float(row.population_total),
                allocation_per_capita_krw=_f(row.fund_allocation_per_capita_krw) or 0.0,
                execution_per_capita_krw=_f(row.fund_execution_per_capita_krw) or 0.0,
            )
        )

    # 집행률 내림차순, 미배분 시군은 뒤로 보낸다.
    rows.sort(key=lambda r: (r.execution_rate is None, -(r.execution_rate or 0.0)))
    base.regions = rows
    return base, "derived", [DEDUP_NOTE, PER_CAPITA_NOTE, NON_RECIPIENT_NOTE, NOT_PERFORMANCE_NOTE]


def trend(panel: Panel, fund: FundInfo) -> tuple[FundTrendData, DataStatus, list[str]]:
    years = fund_years(fund)
    points: list[FundTrendPoint] = []
    previous_rate: float | None = None
    for year in years:
        totals = _totals(panel.fund_year_frame(year))
        rate = _rate(totals["execution"], totals["allocation"])
        change = (
            (rate - previous_rate) * 100
            if rate is not None and previous_rate is not None
            else None
        )
        points.append(
            FundTrendPoint(
                year=year,
                total_allocation_million_krw=totals["allocation"],
                total_execution_million_krw=totals["execution"],
                execution_rate=rate,
                execution_rate_pct=None if rate is None else rate * 100,
                execution_rate_change_pp=change,
                recipient_region_count=totals["recipients"],
                total_project_count=totals["projects"],
            )
        )
        previous_rate = rate

    data = FundTrendData(
        fund_id=fund.fund_id,
        fund_name=fund.name_ko,
        points=points,
        available_years=years,
    )
    return data, "derived", [DEDUP_NOTE, RATE_NOTE, NOT_PERFORMANCE_NOTE]
