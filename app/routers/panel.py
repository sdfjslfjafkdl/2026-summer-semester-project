"""패널 시계열 엔드포인트."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.data.metrics import get_timeseries_metric
from app.data.panel import get_panel
from app.schemas.envelope import Envelope, panel_meta
from app.services import series as service

router = APIRouter(prefix="/api/panel", tags=["패널 시계열"])

DEFAULT_METRIC = "youth_net_migration_rate_per_1000"


class MetricRef(BaseModel):
    key: str
    label_ko: str
    unit: str
    definition: str
    aggregation: str = Field(
        description="월 → 분기·연 재집계 방식. sum(유량) 또는 mean(저량·비율)."
    )


class SeriesPoint(BaseModel):
    period: str = Field(description="freq 에 따라 YYYY-MM, YYYY-Qn, YYYY", examples=["2024-12"])
    value: float | None = Field(description="결측은 채우지 않고 null 로 둔다")


class RegionSeries(BaseModel):
    region: str
    region_role: str
    is_treated: bool
    points: list[SeriesPoint]
    point_count: int
    missing_count: int = Field(description="구간 내 결측 시점 수")
    mean: float | None = Field(description="구간 평균(결측 제외)")
    first_value: float | None
    last_value: float | None


class TimeseriesData(BaseModel):
    metric: MetricRef
    freq: str
    from_period: str = Field(description="요청 구간 시작(YYYY-MM)")
    to_period: str = Field(description="요청 구간 끝(YYYY-MM)")
    series: list[RegionSeries]


class GroupPoint(BaseModel):
    period: str
    treatment_mean: float | None
    control_mean: float | None
    difference: float | None = Field(description="처치군 평균 - 비교군 평균")
    treatment_region_count: int
    control_region_count: int


class GroupTimeseriesData(BaseModel):
    metric: MetricRef
    freq: str
    from_period: str
    to_period: str
    treatment_regions: list[str]
    control_regions: list[str]
    treatment_start_period: str = Field(
        description="기금 투입 시작 시점. 인과분석 화면의 세로선 위치.",
        examples=["2022-01"],
    )
    points: list[GroupPoint]


def _metric_ref(metric) -> MetricRef:  # noqa: ANN001
    return MetricRef(
        key=metric.key,
        label_ko=metric.label_ko,
        unit=metric.unit,
        definition=metric.definition,
        aggregation=metric.aggregation,
    )


REGIONS_QUERY = Query(
    default=None,
    description="콤마로 구분한 시군 이름. 생략하면 11개 시군 전체.",
    examples=["제천시,청주시"],
)
METRIC_QUERY = Query(
    default=DEFAULT_METRIC,
    description="/api/meta/metrics 의 timeseries_metric_keys 중 하나.",
    examples=[DEFAULT_METRIC],
)
FROM_QUERY = Query(default="2017-01", alias="from", description="시작 월(YYYY-MM)", examples=["2017-01"])
TO_QUERY = Query(default="2024-12", alias="to", description="끝 월(YYYY-MM)", examples=["2024-12"])
FREQ_QUERY = Query(
    default="month",
    description="month | quarter | year. 분기·연 재집계 방식은 지표의 aggregation 을 따른다.",
    examples=["month"],
)


@router.get(
    "/timeseries",
    response_model=Envelope[TimeseriesData],
    summary="시군별 지표 시계열",
    description=(
        "지역별 월 시계열을 반환한다. 결측은 보간하지 않고 null 로 남긴다. "
        "특히 employment_insured_yoy_pct 의 2017년 값은 구조적 결측이라 항상 null 이다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "metric": {
                                "key": "youth_net_migration_rate_per_1000",
                                "label_ko": "청년 순이동률",
                                "unit": "명/천명",
                                "definition": "20–39세 순이동자 합계 / 20–39세 주민등록인구 합계 × 1,000.",
                                "aggregation": "mean",
                            },
                            "freq": "month",
                            "from_period": "2024-01",
                            "to_period": "2024-03",
                            "series": [
                                {
                                    "region": "제천시",
                                    "region_role": "treatment",
                                    "is_treated": True,
                                    "points": [
                                        {"period": "2024-01", "value": -5.83},
                                        {"period": "2024-02", "value": -1.72},
                                        {"period": "2024-03", "value": 2.11},
                                    ],
                                    "point_count": 3,
                                    "missing_count": 0,
                                    "mean": -1.81,
                                    "first_value": -5.83,
                                    "last_value": 2.11,
                                }
                            ],
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
        },
        404: {"description": "없는 지역 또는 지표. 응답에 사용 가능한 값 목록이 함께 온다."},
    },
)
def timeseries(
    regions: str | None = REGIONS_QUERY,
    metric: str = METRIC_QUERY,
    from_: str = FROM_QUERY,
    to: str = TO_QUERY,
    freq: str = FREQ_QUERY,
) -> Envelope[TimeseriesData]:
    panel = get_panel()
    metric_info = get_timeseries_metric(metric)
    freq = service.validate_freq(freq)
    from_month = service.parse_month(from_, "from")
    to_month = service.parse_month(to, "to")

    selected = (
        panel.require_regions([r.strip() for r in regions.split(",") if r.strip()])
        if regions
        else panel.region_names
    )
    data = service.region_series(panel, selected, metric_info, from_month, to_month, freq)

    notes = service.range_notes(panel, from_month, to_month)
    if freq != "month":
        notes.append(
            f"{freq} 재집계는 지표 성격에 따라 {metric_info.aggregation} 방식으로 했다."
        )
    if metric_info.key == "employment_insured_yoy_pct":
        notes.append("2017년 값은 구조적 결측이며 보간하지 않는다.")
    status = "actual" if freq == "month" else "derived"
    empty = all(s["point_count"] == 0 for s in data) if data else True

    return Envelope[TimeseriesData](
        data=TimeseriesData(
            metric=_metric_ref(metric_info),
            freq=freq,
            from_period=from_month,
            to_period=to_month,
            series=[RegionSeries(**s) for s in data],
        ),
        meta=panel_meta(
            as_of=panel.period_end,
            data_status="unavailable" if empty else status,
            notes=notes,
        ),
    )


@router.get(
    "/group-timeseries",
    response_model=Envelope[GroupTimeseriesData],
    summary="처치군·비교군 그룹 평균 시계열",
    description=(
        "인과분석 화면의 선그래프용. 처치군 6개 시군 평균과 비교군 5개 시군 평균을 "
        "같은 시점축에 올려 반환한다. 그룹 평균은 지역 단순평균이다. "
        "treatment_start_period 는 세로선 위치로 쓴다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "metric": {
                                "key": "youth_net_migration_rate_per_1000",
                                "label_ko": "청년 순이동률",
                                "unit": "명/천명",
                                "definition": "20–39세 순이동자 합계 / 20–39세 주민등록인구 합계 × 1,000.",
                                "aggregation": "mean",
                            },
                            "freq": "year",
                            "from_period": "2017-01",
                            "to_period": "2024-12",
                            "treatment_regions": ["괴산군", "단양군", "보은군", "영동군", "옥천군", "제천시"],
                            "control_regions": ["음성군", "증평군", "진천군", "청주시", "충주시"],
                            "treatment_start_period": "2022-01",
                            "points": [
                                {
                                    "period": "2022",
                                    "treatment_mean": -3.9,
                                    "control_mean": 0.32,
                                    "difference": -4.22,
                                    "treatment_region_count": 6,
                                    "control_region_count": 5,
                                }
                            ],
                        },
                        "meta": {
                            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
                            "as_of": "2024-12",
                            "data_status": "derived",
                            "notes": [
                                "그룹 계열은 각 시점에서 지역별 값을 단순평균한 값이다(인구 가중 아님). 처치군 6개, 비교군 5개 시군의 산술평균."
                            ],
                        },
                    }
                }
            }
        }
    },
)
def group_timeseries(
    metric: str = METRIC_QUERY,
    from_: str = FROM_QUERY,
    to: str = TO_QUERY,
    freq: str = FREQ_QUERY,
) -> Envelope[GroupTimeseriesData]:
    panel = get_panel()
    metric_info = get_timeseries_metric(metric)
    freq = service.validate_freq(freq)
    from_month = service.parse_month(from_, "from")
    to_month = service.parse_month(to, "to")

    points = service.group_series(panel, metric_info, from_month, to_month, freq)

    notes = [service.GROUP_MEAN_NOTE, *service.range_notes(panel, from_month, to_month)]
    if freq != "month":
        notes.append(
            f"{freq} 재집계는 지역별로 {metric_info.aggregation} 집계한 뒤 그룹 평균을 냈다."
        )
    notes.append(
        "처치군은 인구감소지역 6개 시군, 비교군은 비처치 5개 시군이다. "
        "패널 설계이며 목업 화면의 3개 대 3개 구성과 다르다."
    )

    return Envelope[GroupTimeseriesData](
        data=GroupTimeseriesData(
            metric=_metric_ref(metric_info),
            freq=freq,
            from_period=from_month,
            to_period=to_month,
            treatment_regions=sorted(panel.treated_regions),
            control_regions=sorted(panel.control_regions),
            treatment_start_period=service.TREATMENT_START_PERIOD,
            points=[GroupPoint(**p) for p in points],
        ),
        meta=panel_meta(
            as_of=panel.period_end,
            data_status="unavailable" if not points else "derived",
            notes=notes,
        ),
    )
