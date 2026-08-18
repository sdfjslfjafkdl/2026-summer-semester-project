"""패널 시계열과 처치군·비교군 그룹 시계열 (Layer 1).

그룹 평균은 지역 단순평균이다. 인구 가중평균이 아니며, 청주시처럼 인구가 큰 시군이
그룹 평균을 지배하지 않도록 하는 선택이다. 이 계산 방식은 meta.notes 에 항상 적는다.
"""

from __future__ import annotations

import math
import re

import pandas as pd

from app.data.metrics import MetricInfo
from app.data.panel import Panel
from app.errors import ApiError

FREQUENCIES = ("month", "quarter", "year")

# 기금 투입 시작 시점. post_fund_2022 가 1이 되는 첫 달이며 인과분석 화면의 세로선 위치다.
TREATMENT_START_PERIOD = "2022-01"

GROUP_MEAN_NOTE = (
    "그룹 계열은 각 시점에서 지역별 값을 단순평균한 값이다(인구 가중 아님). "
    "처치군 6개, 비교군 5개 시군의 산술평균."
)
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_month(value: str, field: str) -> str:
    if not MONTH_PATTERN.match(value.strip()):
        raise ApiError(
            status_code=422,
            code="invalid_period",
            message=f"{field} 는 YYYY-MM 형식이어야 합니다. 받은 값: '{value}'",
            field=field,
        )
    return value.strip()


def validate_freq(freq: str) -> str:
    if freq not in FREQUENCIES:
        raise ApiError(
            status_code=422,
            code="invalid_frequency",
            message=f"freq 는 {', '.join(FREQUENCIES)} 중 하나여야 합니다.",
            field="freq",
            allowed_values=list(FREQUENCIES),
        )
    return freq


def _period_label(freq: str) -> callable:  # type: ignore[valid-type]
    if freq == "month":
        return lambda s: s["year_month"]
    if freq == "quarter":
        return lambda s: s["year"].astype(str) + "-Q" + ((s["month"] - 1) // 3 + 1).astype(str)
    return lambda s: s["year"].astype(str)


def window(panel: Panel, from_month: str, to_month: str) -> pd.DataFrame:
    if from_month > to_month:
        raise ApiError(
            status_code=422,
            code="invalid_period_range",
            message=f"from({from_month})이 to({to_month})보다 뒤입니다.",
            field="from",
        )
    df = panel.df
    return df.loc[(df["year_month"] >= from_month) & (df["year_month"] <= to_month)]


def range_notes(panel: Panel, from_month: str, to_month: str) -> list[str]:
    """요청 구간이 패널 범위를 벗어난 부분을 숨기지 않고 알려준다."""
    notes: list[str] = []
    if from_month < panel.period_start or to_month > panel.period_end:
        notes.append(
            f"요청 구간 {from_month}~{to_month} 중 패널 수록 범위"
            f"({panel.period_start}~{panel.period_end}) 밖의 기간은 값을 만들지 않고 비워 두었다."
        )
    return notes


def _value(raw: object) -> float | None:
    if raw is None:
        return None
    number = float(raw)  # type: ignore[arg-type]
    return None if math.isnan(number) else number


def _aggregate(frame: pd.DataFrame, metric: MetricInfo, freq: str) -> pd.DataFrame:
    """지역 × 기간 단위로 재집계한다. 결측(구조적 결측 포함)은 채우지 않는다."""
    work = frame.loc[:, ["region", "year", "month", "year_month", metric.key]].copy()
    work["period"] = _period_label(freq)(work)
    if freq == "month":
        return work.loc[:, ["region", "period", metric.key]]

    grouped = work.groupby(["region", "period"], as_index=False)
    if metric.aggregation == "sum":
        # 구간 안에 결측이 하나라도 있으면 합계를 신뢰할 수 없으므로 결측으로 둔다.
        aggregated = grouped[metric.key].agg(lambda s: s.sum() if s.notna().all() else float("nan"))
    else:
        aggregated = grouped[metric.key].mean()
    return aggregated


def region_series(
    panel: Panel,
    regions: list[str],
    metric: MetricInfo,
    from_month: str,
    to_month: str,
    freq: str = "month",
) -> list[dict]:
    frame = window(panel, from_month, to_month)
    frame = frame.loc[frame["region"].isin(regions)]
    aggregated = _aggregate(frame, metric, freq)

    series: list[dict] = []
    for region in regions:
        rows = aggregated.loc[aggregated["region"] == region].sort_values("period")
        points = [
            {"period": str(row.period), "value": _value(getattr(row, metric.key))}
            for row in rows.itertuples()
        ]
        values = [p["value"] for p in points if p["value"] is not None]
        series.append(
            {
                "region": region,
                "region_role": panel.role_of(region),
                "is_treated": region in panel.treated_regions,
                "points": points,
                "point_count": len(points),
                "missing_count": len(points) - len(values),
                "mean": sum(values) / len(values) if values else None,
                "first_value": points[0]["value"] if points else None,
                "last_value": points[-1]["value"] if points else None,
            }
        )
    return series


def group_series(
    panel: Panel,
    metric: MetricInfo,
    from_month: str,
    to_month: str,
    freq: str = "month",
) -> list[dict]:
    """처치군 평균과 비교군 평균 두 계열을 같은 시점축에 올린다."""
    frame = window(panel, from_month, to_month)
    aggregated = _aggregate(frame, metric, freq)
    aggregated = aggregated.merge(
        pd.DataFrame(
            {
                "region": panel.region_names,
                "is_treated": [r in panel.treated_regions for r in panel.region_names],
            }
        ),
        on="region",
        how="left",
    )

    points: list[dict] = []
    for period, chunk in aggregated.groupby("period", sort=True):
        treated = chunk.loc[chunk["is_treated"], metric.key]
        control = chunk.loc[~chunk["is_treated"], metric.key]
        treated_mean = _value(treated.mean()) if treated.notna().any() else None
        control_mean = _value(control.mean()) if control.notna().any() else None
        points.append(
            {
                "period": str(period),
                "treatment_mean": treated_mean,
                "control_mean": control_mean,
                "difference": (
                    treated_mean - control_mean
                    if treated_mean is not None and control_mean is not None
                    else None
                ),
                "treatment_region_count": int(treated.notna().sum()),
                "control_region_count": int(control.notna().sum()),
            }
        )
    return points
