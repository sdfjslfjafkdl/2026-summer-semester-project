"""차년도 투자계획 제안 (Layer 1, 규칙 기반).

LLM을 쓰지 않는다. 아래 규칙만으로 결정적으로 계산하며, 같은 데이터에 항상 같은 제안을 낸다.

━━ 입력 지표 (모두 패널에서 계산) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  A. 최근 3년(2022~2024) 청년 순이동률 평균          … 수준
  B. 2024년 평균 − 2022년 평균                        … 추세
  C. 최근 3년 청년 전입률·전출률 평균과 11개 시군 중앙값의 차 … 유입 부족 / 유출 과다 진단
  D. 2024년 1인당 기금 배분액                          … 투입 강도
  E. 2024년 기금 집행률                                … 집행 역량
  F. 2024년 일자리·청년 / 정주·생활서비스 사업 비중     … 사업 구성

━━ 우선순위 점수 (배분 대상 시군 안에서만 순위를 매긴다) ━━━━━━━━━━━━━━
  점수 = 45×수준 + 30×추세 + 25×투입격차   (각 항목은 대상 시군 내 백분위 0~1)
    수준   : A가 낮을수록(유출이 심할수록) 1에 가깝다
    추세   : B가 음수일수록(악화될수록) 1에 가깝다
    투입격차: D가 낮을수록 1에 가깝다 — 필요 대비 투입이 적은 곳을 끌어올린다
  점수 상위 1/3 → high, 중간 1/3 → medium, 하위 1/3 → low

━━ 권장 사업 유형 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  유출 초과분(전출률 − 중앙값)이 유입 부족분(중앙값 − 전입률)보다 크면  → 정착·정주형
  반대면                                                              → 유입 확대형
  두 값이 모두 0 이하(둘 다 양호)면                                    → 현행 유지형
  두 격차의 차이가 0.5명/천명 미만이면                                 → 혼합형

━━ 배분 조정 방향 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  집행률 < 50%                        → "집행 구조 개선 우선(배분 유지)"
  집행률 ≥ 50% & 우선순위 high        → "확대"
  집행률 ≥ 50% & 우선순위 low         → "유지"
  그 밖                               → "유지"
  ※ 집행률이 낮은 곳에 배분을 더 얹지 않는다. 집행률은 성과가 아니라 집행 역량의 신호로만 쓴다.

━━ 사업 구성 점검 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  정착·정주형 권장인데 정주·생활서비스 비중 < 0.5  → 구성 조정 권고
  유입 확대형 권장인데 일자리·청년 비중 < 0.5      → 구성 조정 권고

이 제안은 확정된 인과효과가 아니라 기술통계와 진단 지표에 근거한 참고안이다.
DID 1차 추정이 유의하지 않기 때문이며, 응답의 basis 필드에 이 사실을 명시한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.data.panel import FUND_YEARS, Panel

RECENT_YEARS = (2022, 2023, 2024)
MIXED_THRESHOLD = 0.5  # 명/천명. 두 격차 차이가 이보다 작으면 혼합형
LOW_EXECUTION_RATE = 0.5

TYPE_SETTLEMENT = "정착·정주형"
TYPE_INFLOW = "유입 확대형"
TYPE_MIXED = "혼합형"
TYPE_MAINTAIN = "현행 유지형"

DIRECTION_EXPAND = "확대"
DIRECTION_HOLD = "유지"
DIRECTION_FIX_EXECUTION = "집행 구조 개선 우선(배분 유지)"
DIRECTION_NOT_APPLICABLE = "해당 없음(기금 비배분 시군)"

BASIS_NOTE = (
    "이 제안은 확정된 인과효과가 아니라 기술통계와 진단 지표에 근거한 참고안이다. "
    "1차 DID 추정(계수 +0.9496명/천명, p=0.4631)이 통계적으로 유의하지 않아, "
    "특정 사업 유형이 효과가 있다고 단정할 수 없다."
)

RULES_SUMMARY = [
    "우선순위 점수 = 45×(순이동률 수준 백분위) + 30×(추세 악화 백분위) + 25×(1인당 배분액 부족 백분위).",
    "유출 초과분이 유입 부족분보다 크면 정착·정주형, 반대면 유입 확대형, 차이가 0.5명/천명 미만이면 혼합형.",
    "집행률이 50% 미만이면 배분 확대 대신 집행 구조 개선을 먼저 권고한다.",
    "순위는 기금 배분 대상 시군(2022~2024 배분액 > 0) 안에서만 매긴다.",
]


@dataclass
class RegionDiagnosis:
    region: str
    is_treated: bool
    fund_recipient: bool
    net_rate_recent_mean: float
    net_rate_2022_mean: float
    net_rate_2024_mean: float
    net_rate_trend: float
    in_rate_recent_mean: float
    out_rate_recent_mean: float
    in_rate_gap: float  # 중앙값 − 전입률 (양수면 유입 부족)
    out_rate_gap: float  # 전출률 − 중앙값 (양수면 유출 과다)
    allocation_per_capita_krw: float
    execution_rate: float | None
    job_youth_share: float
    settlement_service_share: float
    project_count: float


def _yearly_rate_mean(panel: Panel, column: str) -> pd.DataFrame:
    frame = panel.df.loc[panel.df["year"].isin(RECENT_YEARS)]
    return frame.groupby(["region", "year"], as_index=False)[column].mean()


def diagnose(panel: Panel) -> list[RegionDiagnosis]:
    net = _yearly_rate_mean(panel, "youth_net_migration_rate_per_1000")
    inflow = _yearly_rate_mean(panel, "youth_in_migration_rate_per_1000")
    outflow = _yearly_rate_mean(panel, "youth_out_migration_rate_per_1000")

    net_recent = net.groupby("region")["youth_net_migration_rate_per_1000"].mean()
    in_recent = inflow.groupby("region")["youth_in_migration_rate_per_1000"].mean()
    out_recent = outflow.groupby("region")["youth_out_migration_rate_per_1000"].mean()
    in_median = float(in_recent.median())
    out_median = float(out_recent.median())

    latest_fund = panel.fund_year_frame(max(FUND_YEARS)).set_index("region")
    all_fund = panel.fund_year_frame().groupby("region")["fund_allocation_million_krw"].sum()

    diagnoses: list[RegionDiagnosis] = []
    for region in panel.region_names:
        by_year = net.loc[net["region"] == region].set_index("year")[
            "youth_net_migration_rate_per_1000"
        ]
        fund_row = latest_fund.loc[region]
        execution_rate = fund_row["fund_execution_rate"]
        diagnoses.append(
            RegionDiagnosis(
                region=region,
                is_treated=region in panel.treated_regions,
                fund_recipient=bool(all_fund.get(region, 0) > 0),
                net_rate_recent_mean=float(net_recent[region]),
                net_rate_2022_mean=float(by_year.loc[2022]),
                net_rate_2024_mean=float(by_year.loc[2024]),
                net_rate_trend=float(by_year.loc[2024] - by_year.loc[2022]),
                in_rate_recent_mean=float(in_recent[region]),
                out_rate_recent_mean=float(out_recent[region]),
                in_rate_gap=in_median - float(in_recent[region]),
                out_rate_gap=float(out_recent[region]) - out_median,
                allocation_per_capita_krw=float(fund_row["fund_allocation_per_capita_krw"]),
                execution_rate=None if pd.isna(execution_rate) else float(execution_rate),
                job_youth_share=float(fund_row["fund_job_youth_share"]),
                settlement_service_share=float(fund_row["fund_settlement_service_share"]),
                project_count=float(fund_row["fund_project_count"]),
            )
        )
    return diagnoses


def _percentile_rank(values: list[float], value: float) -> float:
    """작을수록 1에 가까운 백분위. 값이 하나뿐이면 0.5."""
    if len(values) <= 1:
        return 0.5
    below = sum(1 for v in values if v > value)
    ties = sum(1 for v in values if v == value)
    return (below + 0.5 * (ties - 1)) / (len(values) - 1) if len(values) > 1 else 0.5


def recommend_type(diagnosis: RegionDiagnosis) -> tuple[str, str]:
    outflow_pressure = diagnosis.out_rate_gap
    inflow_shortage = diagnosis.in_rate_gap
    if outflow_pressure <= 0 and inflow_shortage <= 0:
        return (
            TYPE_MAINTAIN,
            "전입률과 전출률 모두 11개 시군 중앙값보다 양호해 구조적 개입 필요가 낮다.",
        )
    if abs(outflow_pressure - inflow_shortage) < MIXED_THRESHOLD:
        return (
            TYPE_MIXED,
            f"유출 초과분 {outflow_pressure:+.2f}명/천명과 유입 부족분 {inflow_shortage:+.2f}명/천명이 "
            "비슷해 어느 한쪽으로 단정하기 어렵다.",
        )
    if outflow_pressure > inflow_shortage:
        return (
            TYPE_SETTLEMENT,
            f"전출률이 중앙값보다 {outflow_pressure:+.2f}명/천명 높아 유출이 주 원인이다.",
        )
    return (
        TYPE_INFLOW,
        f"전입률이 중앙값보다 {inflow_shortage:.2f}명/천명 낮아 유입 부족이 주 원인이다.",
    )


def _direction(execution_rate: float | None, level: str, recipient: bool) -> tuple[str, str]:
    if not recipient:
        return (
            DIRECTION_NOT_APPLICABLE,
            "2022~2024 기금 배분 대상이 아니어서 배분 조정 대상에 들어가지 않는다.",
        )
    if execution_rate is not None and execution_rate < LOW_EXECUTION_RATE:
        return (
            DIRECTION_FIX_EXECUTION,
            f"2024년 집행률이 {execution_rate * 100:.1f}%로 50% 미만이라 "
            "배분 확대보다 집행 구조 개선이 먼저다.",
        )
    if level == "high":
        return (
            DIRECTION_EXPAND,
            "우선순위가 높고 집행률이 50% 이상이라 배분 확대를 감당할 수 있다.",
        )
    if level == "low":
        return (DIRECTION_HOLD, "우선순위가 상대적으로 낮아 현 수준 유지가 적절하다.")
    return (DIRECTION_HOLD, "우선순위가 중간 수준이라 현 배분을 유지하며 사업 구성만 조정한다.")


def _composition_note(recommended: str, diagnosis: RegionDiagnosis) -> str | None:
    if not diagnosis.fund_recipient:
        return None
    if recommended == TYPE_SETTLEMENT and diagnosis.settlement_service_share < 0.5:
        return (
            f"정착·정주형을 권장하지만 2024년 정주·생활서비스 사업 비중이 "
            f"{diagnosis.settlement_service_share * 100:.0f}%에 그쳐 구성 조정이 필요하다."
        )
    if recommended == TYPE_INFLOW and diagnosis.job_youth_share < 0.5:
        return (
            f"유입 확대형을 권장하지만 2024년 일자리·청년 사업 비중이 "
            f"{diagnosis.job_youth_share * 100:.0f}%에 그쳐 구성 조정이 필요하다."
        )
    return None


def build_proposals(panel: Panel) -> list[dict]:
    diagnoses = diagnose(panel)
    recipients = [d for d in diagnoses if d.fund_recipient]

    levels = [d.net_rate_recent_mean for d in recipients]
    trends = [d.net_rate_trend for d in recipients]
    allocations = [d.allocation_per_capita_krw for d in recipients]

    scored: list[dict] = []
    for diagnosis in diagnoses:
        if diagnosis.fund_recipient:
            level_component = _percentile_rank(levels, diagnosis.net_rate_recent_mean)
            trend_component = _percentile_rank(trends, diagnosis.net_rate_trend)
            gap_component = _percentile_rank(allocations, diagnosis.allocation_per_capita_krw)
            score = 45 * level_component + 30 * trend_component + 25 * gap_component
        else:
            level_component = trend_component = gap_component = None
            score = None
        scored.append(
            {
                "diagnosis": diagnosis,
                "score": score,
                "components": {
                    "level": level_component,
                    "trend": trend_component,
                    "allocation_gap": gap_component,
                },
            }
        )

    ranked = sorted(
        [s for s in scored if s["score"] is not None],
        key=lambda s: (-s["score"], s["diagnosis"].region),
    )
    total = len(ranked)
    rank_by_region: dict[str, int] = {}
    level_by_region: dict[str, str] = {}
    for position, entry in enumerate(ranked, start=1):
        region = entry["diagnosis"].region
        rank_by_region[region] = position
        if position <= total / 3:
            level_by_region[region] = "high"
        elif position <= 2 * total / 3:
            level_by_region[region] = "medium"
        else:
            level_by_region[region] = "low"

    proposals: list[dict] = []
    for entry in scored:
        diagnosis: RegionDiagnosis = entry["diagnosis"]
        recommended, type_reason = recommend_type(diagnosis)
        level = level_by_region.get(diagnosis.region, "not_ranked")
        direction, direction_reason = _direction(
            diagnosis.execution_rate, level, diagnosis.fund_recipient
        )
        composition = _composition_note(recommended, diagnosis)

        drivers = [
            {
                "metric": "youth_net_migration_rate_per_1000",
                "label_ko": "최근 3년(2022~2024) 청년 순이동률 평균",
                "value": round(diagnosis.net_rate_recent_mean, 4),
                "unit": "명/천명",
                "note": "값이 음수이면 청년이 순유출되고 있다는 뜻이다.",
            },
            {
                "metric": "youth_net_migration_rate_trend",
                "label_ko": "2024년 평균 − 2022년 평균",
                "value": round(diagnosis.net_rate_trend, 4),
                "unit": "명/천명",
                "note": "음수이면 최근 3년 사이 악화됐다는 뜻이다.",
            },
            {
                "metric": "youth_out_migration_rate_per_1000",
                "label_ko": "청년 전출률 − 11개 시군 중앙값",
                "value": round(diagnosis.out_rate_gap, 4),
                "unit": "명/천명",
                "note": "양수이면 유출이 상대적으로 과다하다.",
            },
            {
                "metric": "youth_in_migration_rate_per_1000",
                "label_ko": "11개 시군 중앙값 − 청년 전입률",
                "value": round(diagnosis.in_rate_gap, 4),
                "unit": "명/천명",
                "note": "양수이면 유입이 상대적으로 부족하다.",
            },
            {
                "metric": "fund_allocation_per_capita_krw",
                "label_ko": "2024년 1인당 기금 배분액",
                "value": round(diagnosis.allocation_per_capita_krw, 0),
                "unit": "원/명",
                "note": "연말 인구 기준. 배분 대상이 아니면 0이다.",
            },
            {
                "metric": "fund_execution_rate",
                "label_ko": "2024년 기금 집행률",
                "value": (
                    None if diagnosis.execution_rate is None else round(diagnosis.execution_rate, 4)
                ),
                "unit": "비율(0~1)",
                "note": "배분액이 0인 시군은 정의되지 않는다.",
            },
            {
                "metric": "fund_settlement_service_share",
                "label_ko": "2024년 정주·생활서비스 사업 비중",
                "value": round(diagnosis.settlement_service_share, 4),
                "unit": "비율(0~1)",
                "note": "정착·정주형 권장 시 이 비중을 함께 본다.",
            },
            {
                "metric": "fund_job_youth_share",
                "label_ko": "2024년 일자리·청년 사업 비중",
                "value": round(diagnosis.job_youth_share, 4),
                "unit": "비율(0~1)",
                "note": "유입 확대형 권장 시 이 비중을 함께 본다.",
            },
        ]

        rationale = " ".join(
            filter(
                None,
                [
                    f"{diagnosis.region}의 최근 3년 청년 순이동률은 평균 "
                    f"{diagnosis.net_rate_recent_mean:+.2f}명/천명이고, 2022년 대비 2024년 변화는 "
                    f"{diagnosis.net_rate_trend:+.2f}명/천명이다.",
                    type_reason,
                    direction_reason,
                    composition,
                ],
            )
        )

        proposals.append(
            {
                "region": diagnosis.region,
                "is_treated": diagnosis.is_treated,
                "fund_recipient": diagnosis.fund_recipient,
                "priority_rank": rank_by_region.get(diagnosis.region),
                "priority_score": None if entry["score"] is None else round(entry["score"], 2),
                "priority_level": level,
                "score_components": {
                    key: (None if value is None else round(value, 4))
                    for key, value in entry["components"].items()
                },
                "recommended_project_type": recommended,
                "recommended_type_reason": type_reason,
                "allocation_direction": direction,
                "allocation_direction_reason": direction_reason,
                "composition_note": composition,
                "rationale_ko": rationale,
                "drivers": drivers,
            }
        )

    proposals.sort(key=lambda p: (p["priority_rank"] is None, p["priority_rank"] or 0, p["region"]))
    return proposals
