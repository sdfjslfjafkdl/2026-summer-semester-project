"""조회 가능한 지표 카탈로그.

정의 문장의 출처는 README_chungbuk_model_panel.md 이며, 원문에 없는 설명은
패널 컬럼의 계산식을 그대로 서술한 것이다. 프론트의 지표 선택 UI와
Layer 2 라우터의 지표 매칭이 모두 이 카탈로그를 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass

METRIC_SOURCE_DOC = "README_chungbuk_model_panel.md"


@dataclass(frozen=True)
class MetricInfo:
    key: str
    label_ko: str
    unit: str
    definition: str
    category: str
    frequency: str  # month | year
    aliases: tuple[str, ...] = ()
    # 월 → 분기·연 재집계 방식.
    #   sum : 기간 중 발생량을 더하는 유량 지표 (전입·전출 인원, 고용 취득·상실)
    #   mean: 시점의 상태를 나타내는 저량·비율 지표 (인구, 피보험자 수, 각종 비율)
    aggregation: str = "mean"


METRICS: tuple[MetricInfo, ...] = (
    MetricInfo(
        key="youth_net_migration_rate_per_1000",
        label_ko="청년 순이동률",
        unit="명/천명",
        definition=(
            "20–39세 순이동자 합계 / 20–39세 주민등록인구 합계 × 1,000. "
            "이 서비스의 주 결과변수이며, 기금 성과를 집행률 대신 이 지표로 평가한다."
        ),
        category="청년 이동",
        frequency="month",
        aliases=("청년 순이동률", "순이동률", "청년순이동", "인구 유출", "청년 유출"),
    ),
    MetricInfo(
        key="youth_in_migration_rate_per_1000",
        label_ko="청년 전입률",
        unit="명/천명",
        definition=(
            "20–39세 총전입자 / 20–39세 주민등록인구 × 1,000. "
            "순이동 변화를 유입 확대와 유출 완화로 분해하는 진단 변수."
        ),
        category="청년 이동",
        frequency="month",
        aliases=("전입률", "유입률", "청년 유입"),
    ),
    MetricInfo(
        key="youth_out_migration_rate_per_1000",
        label_ko="청년 전출률",
        unit="명/천명",
        definition=(
            "20–39세 총전출자 / 20–39세 주민등록인구 × 1,000. "
            "순이동 변화를 유입 확대와 유출 완화로 분해하는 진단 변수."
        ),
        category="청년 이동",
        frequency="month",
        aliases=("전출률", "유출률"),
    ),
    MetricInfo(
        key="youth_net_migration_20_39",
        label_ko="청년 순이동자 수",
        unit="명",
        definition="20–39세 전입자에서 전출자를 뺀 월별 순이동 인원.",
        category="청년 이동",
        frequency="month",
        aliases=("청년 순이동 인원",),
        aggregation="sum",
    ),
    MetricInfo(
        key="youth_in_migration_20_39",
        label_ko="청년 전입자 수",
        unit="명",
        definition="20–39세 월별 총전입 인원.",
        category="청년 이동",
        frequency="month",
        aggregation="sum",
    ),
    MetricInfo(
        key="youth_out_migration_20_39",
        label_ko="청년 전출자 수",
        unit="명",
        definition="20–39세 월별 총전출 인원.",
        category="청년 이동",
        frequency="month",
        aggregation="sum",
    ),
    MetricInfo(
        key="youth_population_20_39",
        label_ko="청년인구(20–39세)",
        unit="명",
        definition="20–39세 주민등록인구. 청년 이동률의 분모.",
        category="인구",
        frequency="month",
        aliases=("청년인구",),
    ),
    MetricInfo(
        key="population_total",
        label_ko="총인구",
        unit="명",
        definition="주민등록 총인구.",
        category="인구",
        frequency="month",
        aliases=("인구",),
    ),
    MetricInfo(
        key="population_65_plus",
        label_ko="65세 이상 인구",
        unit="명",
        definition="65세 이상 주민등록인구.",
        category="인구",
        frequency="month",
    ),
    MetricInfo(
        key="aged_population_ratio_pct",
        label_ko="고령인구비율",
        unit="%",
        definition="고령인구비율(%). 인구 통제변수.",
        category="인구",
        frequency="month",
        aliases=("고령화율", "고령인구 비율"),
    ),
    MetricInfo(
        key="employment_insured_persons",
        label_ko="고용보험 피보험자 수",
        unit="명",
        definition="월별 고용보험 피보험자 지표.",
        category="고용",
        frequency="month",
        aliases=("피보험자", "고용보험"),
    ),
    MetricInfo(
        key="employment_acquisitions",
        label_ko="고용보험 취득자 수",
        unit="명",
        definition="월별 고용보험 자격취득 인원.",
        category="고용",
        frequency="month",
        aggregation="sum",
    ),
    MetricInfo(
        key="employment_losses",
        label_ko="고용보험 상실자 수",
        unit="명",
        definition="월별 고용보험 자격상실 인원.",
        category="고용",
        frequency="month",
        aggregation="sum",
    ),
    MetricInfo(
        key="employment_net_flow",
        label_ko="고용보험 순증",
        unit="명",
        definition="월별 고용보험 취득에서 상실을 뺀 순증 인원.",
        category="고용",
        frequency="month",
        aggregation="sum",
    ),
    MetricInfo(
        key="employment_insured_yoy_pct",
        label_ko="고용보험 피보험자 전년동월비",
        unit="%",
        definition=(
            "12개월 전 대비 피보험자 수 증감률. "
            "최초 12개월 × 11개 시군(132행)은 구조적으로 결측이며 보간하지 않는다."
        ),
        category="고용",
        frequency="month",
        aliases=("고용 증감률",),
    ),
    MetricInfo(
        key="fund_allocation_million_krw",
        label_ko="기금 배분액",
        unit="백만원",
        definition=(
            "2022–2024 연도별 지방소멸대응기금 배분액. "
            "연도값을 해당 연도 모든 월에 결합한 변수이므로 월별로 합산하면 12배가 된다. "
            "집계는 지역-연도 중복 제거 후에만 수행한다."
        ),
        category="기금",
        frequency="year",
        aliases=("배분액", "배정액", "총 배분액"),
    ),
    MetricInfo(
        key="fund_execution_million_krw",
        label_ko="기금 집행액",
        unit="백만원",
        definition="2022–2024 연도별 지방소멸대응기금 집행액. 지역-연도 중복 제거 후 합산한다.",
        category="기금",
        frequency="year",
        aliases=("집행액",),
    ),
    MetricInfo(
        key="fund_execution_rate",
        label_ko="기금 집행률",
        unit="비율(0~1)",
        definition=(
            "집행액 / 배분액. 배분액이 0인 시군은 정의되지 않아 결측이다. "
            "집행률은 성과가 아니라 투입 진행률을 뜻하므로, 이 서비스는 성과 평가에 쓰지 않는다."
        ),
        category="기금",
        frequency="year",
        aliases=("집행률",),
    ),
    MetricInfo(
        key="fund_project_count",
        label_ko="기금 사업 수",
        unit="건",
        definition="연도별 기금 사업 건수.",
        category="기금",
        frequency="year",
        aliases=("사업수", "사업 건수"),
    ),
    MetricInfo(
        key="fund_job_youth_project_count",
        label_ko="일자리·청년 사업 수",
        unit="건",
        definition="연도별 일자리·청년 유형 사업 건수.",
        category="기금",
        frequency="year",
    ),
    MetricInfo(
        key="fund_settlement_service_project_count",
        label_ko="정주·생활서비스 사업 수",
        unit="건",
        definition="연도별 정주·생활서비스 유형 사업 건수.",
        category="기금",
        frequency="year",
    ),
    MetricInfo(
        key="fund_job_youth_share",
        label_ko="일자리·청년 사업 비중",
        unit="비율(0~1)",
        definition="전체 기금 사업 중 일자리·청년 유형 비중.",
        category="기금",
        frequency="year",
    ),
    MetricInfo(
        key="fund_settlement_service_share",
        label_ko="정주·생활서비스 사업 비중",
        unit="비율(0~1)",
        definition="전체 기금 사업 중 정주·생활서비스 유형 비중.",
        category="기금",
        frequency="year",
    ),
    MetricInfo(
        key="fund_allocation_per_capita_krw",
        label_ko="1인당 기금 배분액",
        unit="원/명",
        definition=(
            "연간 배분액 × 1,000,000 / 주민등록 총인구. "
            "연도 대표값은 연말(12월) 인구를 분모로 다시 계산한 파생값이다."
        ),
        category="기금",
        frequency="year",
        aliases=("1인당 배분액",),
    ),
    MetricInfo(
        key="fund_execution_per_capita_krw",
        label_ko="1인당 기금 집행액",
        unit="원/명",
        definition=(
            "연간 집행액 × 1,000,000 / 주민등록 총인구. "
            "연도 대표값은 연말(12월) 인구를 분모로 다시 계산한 파생값이다."
        ),
        category="기금",
        frequency="year",
        aliases=("1인당 집행액",),
    ),
)

METRIC_BY_KEY: dict[str, MetricInfo] = {m.key: m for m in METRICS}

# 월별 시계열로 조회할 수 있는 지표 (기금 변수는 연도 단위라 제외)
TIMESERIES_METRIC_KEYS: tuple[str, ...] = tuple(
    m.key for m in METRICS if m.frequency == "month"
)


def get_metric(key: str) -> MetricInfo:
    from app.errors import unknown_metric

    metric = METRIC_BY_KEY.get(key)
    if metric is None:
        raise unknown_metric(key, list(METRIC_BY_KEY))
    return metric


def get_timeseries_metric(key: str) -> MetricInfo:
    from app.errors import unknown_metric

    metric = METRIC_BY_KEY.get(key)
    if metric is None or metric.frequency != "month":
        raise unknown_metric(key, list(TIMESERIES_METRIC_KEYS))
    return metric
