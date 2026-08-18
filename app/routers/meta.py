"""기준 정보: 지역 목록과 지표 카탈로그."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.data.metrics import METRIC_SOURCE_DOC, METRICS, TIMESERIES_METRIC_KEYS
from app.data.panel import get_panel
from app.schemas.envelope import Envelope, Meta, panel_meta
from app.services.funds import FUNDS

router = APIRouter(prefix="/api/meta", tags=["기준 정보"])


class RegionItem(BaseModel):
    region: str = Field(description="시군 이름", examples=["제천시"])
    is_treated: bool = Field(description="처치군 여부", examples=[True])
    region_role: str = Field(description="treatment 또는 control", examples=["treatment"])


class RegionsData(BaseModel):
    regions: list[RegionItem]
    treated_regions: list[str] = Field(description="처치군 6개 시군")
    control_regions: list[str] = Field(description="비교군 5개 시군")
    period_start: str
    period_end: str


class MetricItem(BaseModel):
    key: str = Field(description="API 파라미터로 넘기는 지표 키")
    label_ko: str = Field(description="화면에 표시할 한글 라벨")
    unit: str = Field(description="단위")
    definition: str = Field(description="지표 정의 문장")
    category: str = Field(description="지표 묶음", examples=["청년 이동"])
    frequency: str = Field(description="month 또는 year", examples=["month"])
    timeseries_available: bool = Field(
        description="/api/panel/timeseries 로 월 시계열 조회가 가능한지"
    )


class MetricsData(BaseModel):
    metrics: list[MetricItem]
    timeseries_metric_keys: list[str]
    primary_outcome_key: str = Field(
        description="이 서비스가 성과 평가에 쓰는 주 결과변수",
        examples=["youth_net_migration_rate_per_1000"],
    )


class FundItem(BaseModel):
    fund_id: str
    name_ko: str
    first_year: int
    last_year: int


class FundsData(BaseModel):
    funds: list[FundItem]


@router.get(
    "/regions",
    response_model=Envelope[RegionsData],
    summary="지역 목록과 처치 여부",
    description=(
        "충북 11개 시군과 각 시군의 처치군/비교군 역할을 반환한다. "
        "처치군은 인구감소지역 6개, 비교군은 비처치 5개이며 패널 설계 그대로다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "regions": [
                                {"region": "제천시", "is_treated": True, "region_role": "treatment"},
                                {"region": "청주시", "is_treated": False, "region_role": "control"},
                            ],
                            "treated_regions": ["괴산군", "단양군", "보은군", "영동군", "옥천군", "제천시"],
                            "control_regions": ["음성군", "증평군", "진천군", "청주시", "충주시"],
                            "period_start": "2017-01",
                            "period_end": "2024-12",
                        },
                        "meta": {
                            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                            "as_of": "2024-12",
                            "data_status": "actual",
                            "notes": [],
                        },
                    }
                }
            }
        }
    },
)
def regions() -> Envelope[RegionsData]:
    panel = get_panel()
    return Envelope[RegionsData](
        data=RegionsData(
            regions=[
                RegionItem(
                    region=info.region,
                    is_treated=info.is_treated,
                    region_role=info.region_role,
                )
                for info in panel.regions
            ],
            treated_regions=sorted(panel.treated_regions),
            control_regions=sorted(panel.control_regions),
            period_start=panel.period_start,
            period_end=panel.period_end,
        ),
        meta=panel_meta(
            as_of=panel.period_end,
            notes=[
                "처치군은 인구감소지역 6개 시군, 비교군은 비처치 5개 시군이다.",
                "청주 4구는 고용보험 원자료에서 합산해 청주시로 통일했다.",
            ],
        ),
    )


@router.get(
    "/metrics",
    response_model=Envelope[MetricsData],
    summary="조회 가능한 지표 카탈로그",
    description=(
        "지표 키, 한글 라벨, 단위, 정의 문장을 반환한다. "
        "정의 문장의 출처는 README_chungbuk_model_panel.md 이다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "metrics": [
                                {
                                    "key": "youth_net_migration_rate_per_1000",
                                    "label_ko": "청년 순이동률",
                                    "unit": "명/천명",
                                    "definition": "20–39세 순이동자 합계 / 20–39세 주민등록인구 합계 × 1,000.",
                                    "category": "청년 이동",
                                    "frequency": "month",
                                    "timeseries_available": True,
                                }
                            ],
                            "timeseries_metric_keys": ["youth_net_migration_rate_per_1000"],
                            "primary_outcome_key": "youth_net_migration_rate_per_1000",
                        },
                        "meta": {
                            "source": "README_chungbuk_model_panel.md",
                            "as_of": "2024-12",
                            "data_status": "actual",
                            "notes": [],
                        },
                    }
                }
            }
        }
    },
)
def metrics() -> Envelope[MetricsData]:
    panel = get_panel()
    return Envelope[MetricsData](
        data=MetricsData(
            metrics=[
                MetricItem(
                    key=m.key,
                    label_ko=m.label_ko,
                    unit=m.unit,
                    definition=m.definition,
                    category=m.category,
                    frequency=m.frequency,
                    timeseries_available=m.frequency == "month",
                )
                for m in METRICS
            ],
            timeseries_metric_keys=list(TIMESERIES_METRIC_KEYS),
            primary_outcome_key="youth_net_migration_rate_per_1000",
        ),
        meta=Meta(
            source=METRIC_SOURCE_DOC,
            as_of=panel.period_end,
            data_status="actual",
            notes=[
                "기금 변수는 연도 단위라 월 시계열로 조회할 수 없다.",
                "집행률은 투입 진행률이며 성과 지표가 아니다.",
            ],
        ),
    )


@router.get(
    "/funds",
    response_model=Envelope[FundsData],
    summary="등록된 기금 목록",
    description="fund_id 경로 파라미터에 넣을 수 있는 기금 목록. 현재는 지방소멸대응기금 1종이다.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "funds": [
                                {
                                    "fund_id": "local-extinction",
                                    "name_ko": "지방소멸대응기금",
                                    "first_year": 2022,
                                    "last_year": 2024,
                                }
                            ]
                        },
                        "meta": {
                            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                            "as_of": "2024-12",
                            "data_status": "actual",
                            "notes": ["현재 수록된 기금은 1종이다."],
                        },
                    }
                }
            }
        }
    },
)
def funds() -> Envelope[FundsData]:
    panel = get_panel()
    return Envelope[FundsData](
        data=FundsData(funds=[FundItem(**f.model_dump()) for f in FUNDS.values()]),
        meta=panel_meta(as_of=panel.period_end, notes=["현재 수록된 기금은 1종이다."]),
    )
