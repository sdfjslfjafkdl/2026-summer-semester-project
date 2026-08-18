"""기금 대시보드 엔드포인트.

패널에 없는 연도(예: 2025)를 요청하면 값을 추정하지 않고
meta.data_status = "unavailable" 로 명시해 반환한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query

from app.data.panel import FUND_YEARS, get_panel
from app.schemas.envelope import Envelope, Meta
from app.schemas.funds import FundRegionsData, FundSummaryData, FundTrendData
from app.services import funds as service

router = APIRouter(prefix="/api/funds", tags=["기금 대시보드"])

FUND_ID = Path(
    description="기금 식별자. 현재는 local-extinction(지방소멸대응기금) 1종.",
    examples=["local-extinction"],
)
YEAR = Query(
    default=max(FUND_YEARS),
    ge=2000,
    le=2100,
    description="조회 연도. 수록 범위 밖이면 data_status=unavailable 로 반환한다.",
    examples=[2024],
)

SUMMARY_EXAMPLE = {
    "data": {
        "fund_id": "local-extinction",
        "fund_name": "지방소멸대응기금",
        "year": 2024,
        "total_allocation_million_krw": 46400.0,
        "total_execution_million_krw": 18960.0,
        "unexecuted_million_krw": 27440.0,
        "execution_rate": 0.4086,
        "execution_rate_pct": 40.86,
        "previous_year": 2023,
        "previous_execution_rate_pct": 52.98,
        "execution_rate_change_pp": -12.12,
        "allocation_change_million_krw": -800.0,
        "execution_change_million_krw": -6049.0,
        "region_count": 11,
        "recipient_region_count": 6,
        "total_project_count": 19.0,
        "available_years": [2022, 2023, 2024],
    },
    "meta": {
        "source": "chungbuk_monthly_model_panel_2017_2024.csv",
        "as_of": "2024",
        "data_status": "derived",
        "notes": ["기금 금액은 지역-연도 단위로 중복 제거한 뒤 합산했다."],
    },
}

UNAVAILABLE_EXAMPLE = {
    "data": {
        "fund_id": "local-extinction",
        "fund_name": "지방소멸대응기금",
        "year": 2025,
        "total_allocation_million_krw": None,
        "execution_rate_pct": None,
        "region_count": 11,
        "available_years": [2022, 2023, 2024],
    },
    "meta": {
        "source": "chungbuk_monthly_model_panel_2017_2024.csv",
        "as_of": "2024",
        "data_status": "unavailable",
        "notes": ["2025년 지방소멸대응기금 데이터는 이 패널에 없다. 수록 연도는 2022~2024 이다."],
    },
}


@router.get(
    "/{fund_id}/summary",
    response_model=Envelope[FundSummaryData],
    summary="연도별 기금 총괄",
    description=(
        "총 배분액, 집행액, 집행률, 전년 대비 증감을 반환한다. "
        "금액은 지역-연도 중복 제거 후 합산하며, 집행률은 총액 대비 비율이다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "2024년": {"value": SUMMARY_EXAMPLE},
                        "패널 범위 밖(2025년)": {"value": UNAVAILABLE_EXAMPLE},
                    }
                }
            }
        }
    },
)
def fund_summary(fund_id: str = FUND_ID, year: int = YEAR) -> Envelope[FundSummaryData]:
    panel = get_panel()
    fund = service.get_fund(fund_id)
    data, status, notes = service.summary(panel, fund, year)
    meta = (
        service.unavailable_meta(fund, year, panel)
        if status == "unavailable"
        else service.actual_meta(year, notes)
    )
    return Envelope[FundSummaryData](data=data, meta=meta)


@router.get(
    "/{fund_id}/regions",
    response_model=Envelope[FundRegionsData],
    summary="시군별 기금 집행 현황",
    description=(
        "시군별 배분액, 집행액, 집행률, 사업수, 1인당 배분액을 집행률 내림차순으로 반환한다. "
        "배분액이 0인 비교군 5개 시군은 집행률이 null 이며 목록 뒤쪽에 온다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "fund_id": "local-extinction",
                            "fund_name": "지방소멸대응기금",
                            "year": 2024,
                            "regions": [
                                {
                                    "region": "보은군",
                                    "region_role": "treatment",
                                    "is_treated": True,
                                    "allocation_million_krw": 8000.0,
                                    "execution_million_krw": 5477.0,
                                    "unexecuted_million_krw": 2523.0,
                                    "execution_rate": 0.685,
                                    "execution_rate_pct": 68.5,
                                    "project_count": 4.0,
                                    "job_youth_project_count": 2.0,
                                    "settlement_service_project_count": 0.0,
                                    "job_youth_share": 0.5,
                                    "settlement_service_share": 0.0,
                                    "population_total": 30573.0,
                                    "allocation_per_capita_krw": 261674.0,
                                    "execution_per_capita_krw": 179177.0,
                                }
                            ],
                            "available_years": [2022, 2023, 2024],
                        },
                        "meta": {
                            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                            "as_of": "2024",
                            "data_status": "derived",
                            "notes": ["1인당 지표는 해당 연도 연말(12월) 주민등록 총인구를 분모로 계산했다."],
                        },
                    }
                }
            }
        }
    },
)
def fund_regions(fund_id: str = FUND_ID, year: int = YEAR) -> Envelope[FundRegionsData]:
    panel = get_panel()
    fund = service.get_fund(fund_id)
    data, status, notes = service.by_region(panel, fund, year)
    meta: Meta = (
        service.unavailable_meta(fund, year, panel)
        if status == "unavailable"
        else service.actual_meta(year, notes)
    )
    return Envelope[FundRegionsData](data=data, meta=meta)


@router.get(
    "/{fund_id}/trend",
    response_model=Envelope[FundTrendData],
    summary="연도별 집행률 추이",
    description="2022~2024 연도별 총 배분액, 집행액, 집행률과 전년 대비 증감을 반환한다.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "fund_id": "local-extinction",
                            "fund_name": "지방소멸대응기금",
                            "points": [
                                {
                                    "year": 2022,
                                    "total_allocation_million_krw": 35400.0,
                                    "total_execution_million_krw": 26131.0,
                                    "execution_rate": 0.7382,
                                    "execution_rate_pct": 73.82,
                                    "execution_rate_change_pp": None,
                                    "recipient_region_count": 6,
                                    "total_project_count": 17.0,
                                }
                            ],
                            "available_years": [2022, 2023, 2024],
                        },
                        "meta": {
                            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                            "as_of": "2024",
                            "data_status": "derived",
                            "notes": ["집행률은 총 집행액 ÷ 총 배분액으로 계산했다."],
                        },
                    }
                }
            }
        }
    },
)
def fund_trend(fund_id: str = FUND_ID) -> Envelope[FundTrendData]:
    panel = get_panel()
    fund = service.get_fund(fund_id)
    data, _, notes = service.trend(panel, fund)
    return Envelope[FundTrendData](data=data, meta=service.actual_meta(fund.last_year, notes))
