"""인과분석 결과 엔드포인트.

여기서는 아무것도 추정하지 않는다. data/artifacts/ 의 결과 JSON을 검증해 그대로 반환한다.
유의성은 아티팩트의 p값과 유의수준으로만 판정하며, 응답에 판정 결과와 해석 주의를 항상 함께 낸다.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas.artifacts import DidArtifact, RegionErrorRow, ValidationArtifact
from app.schemas.envelope import Envelope, Meta
from app.services.artifacts import DID_FILENAME, VALIDATION_FILENAME, did_store, validation_store

router = APIRouter(prefix="/api/analysis", tags=["인과분석"])


class DidDesign(BaseModel):
    method: str
    method_label_ko: str
    outcome: str
    outcome_unit: str
    treated_regions: list[str]
    control_regions: list[str]
    treated_region_count: int
    control_region_count: int
    treatment_start: str = Field(description="처치 시점(YYYY-MM). 그래프 세로선 위치.")
    sample_period: str
    n_observations: int
    n_clusters: int
    standard_error_type: str


class DidEffect(BaseModel):
    coefficient: float = Field(description="추정 효과 크기", examples=[0.9496181198273366])
    unit: str = Field(description="계수의 단위", examples=["명/천명"])
    standard_error: float
    t_statistic: float | None
    ci_95_low: float
    ci_95_high: float
    r_squared: float | None


class DidSignificance(BaseModel):
    p_value: float
    alpha: float
    is_significant: bool = Field(
        description="p_value < alpha 판정. 현재 베이스라인은 false 다.", examples=[False]
    )
    label_ko: str = Field(examples=["통계적으로 유의하지 않음"])
    statement_ko: str = Field(
        description="화면에 그대로 쓸 수 있는 한 문장 요약",
        examples=[
            "추정 효과는 +0.9496명/천명이지만 p값이 0.4631로 유의수준 0.05를 넘어, "
            "효과가 0과 다르다고 말할 수 없습니다."
        ],
    )


class DidGroupMeans(BaseModel):
    treated_pre_mean: float | None
    treated_post_mean: float | None
    control_pre_mean: float | None
    control_post_mean: float | None
    simple_did_mean_difference: float | None


class DidData(BaseModel):
    design: DidDesign
    effect: DidEffect
    significance: DidSignificance
    group_means: DidGroupMeans
    interpretation_cautions: list[str]
    artifact_version: str
    generated_at: str


class ValidationOverall(BaseModel):
    method: str
    method_label_ko: str
    outcome: str
    outcome_unit: str
    test_window: str
    n_observations: int
    mae: float
    rmse: float
    mean_error_bias: float
    interpretation: str


class ValidationData(BaseModel):
    overall: ValidationOverall
    by_region: list[RegionErrorRow]
    artifact_version: str
    generated_at: str


def _significance_statement(artifact: DidArtifact) -> str:
    sign = "+" if artifact.coefficient >= 0 else ""
    if artifact.is_significant:
        return (
            f"추정 효과는 {sign}{artifact.coefficient:.4f}{artifact.outcome_unit}이고 "
            f"p값은 {artifact.p_value:.4f}로 유의수준 {artifact.alpha}보다 작습니다."
        )
    return (
        f"추정 효과는 {sign}{artifact.coefficient:.4f}{artifact.outcome_unit}이지만 "
        f"p값이 {artifact.p_value:.4f}로 유의수준 {artifact.alpha}를 넘어, "
        f"효과가 0과 다르다고 말할 수 없습니다. "
        f"95% 신뢰구간 [{artifact.ci_95[0]:.4f}, {artifact.ci_95[1]:.4f}]도 0을 포함합니다."
    )


DID_EXAMPLE = {
    "data": {
        "design": {
            "method": "two_way_fixed_effects_ols",
            "method_label_ko": "양방향 고정효과 DID (TWFE)",
            "outcome": "youth_net_migration_rate_per_1000",
            "outcome_unit": "명/천명",
            "treated_regions": ["제천시", "보은군", "옥천군", "영동군", "괴산군", "단양군"],
            "control_regions": ["청주시", "충주시", "증평군", "진천군", "음성군"],
            "treated_region_count": 6,
            "control_region_count": 5,
            "treatment_start": "2022-01",
            "sample_period": "2017-01~2024-12",
            "n_observations": 1056,
            "n_clusters": 11,
            "standard_error_type": "clustered_by_municipality",
        },
        "effect": {
            "coefficient": 0.9496181198273366,
            "unit": "명/천명",
            "standard_error": 1.2447543537087846,
            "t_statistic": 0.762896001928348,
            "ci_95_low": -1.823867416850271,
            "ci_95_high": 3.7231036565049442,
            "r_squared": 0.25505836764471757,
        },
        "significance": {
            "p_value": 0.46314203447465774,
            "alpha": 0.05,
            "is_significant": False,
            "label_ko": "통계적으로 유의하지 않음",
            "statement_ko": "추정 효과는 +0.9496명/천명이지만 p값이 0.4631로 유의수준 0.05를 넘어, 효과가 0과 다르다고 말할 수 없습니다.",
        },
        "group_means": {
            "treated_pre_mean": -4.710246832861368,
            "treated_post_mean": -3.810925393560115,
            "control_pre_mean": 0.21198316302062653,
            "control_post_mean": 0.1616864824945462,
            "simple_did_mean_difference": 0.9496181198273335,
        },
        "interpretation_cautions": [
            "Clustered by municipality; only 11 clusters, so inference is exploratory."
        ],
        "artifact_version": "v1",
        "generated_at": "2026-08-18T21:29:51+09:00",
    },
    "meta": {
        "source": "did_twfe_v1.json",
        "as_of": "2024-12",
        "data_status": "actual",
        "notes": ["이 서버는 추정을 수행하지 않고 사전 계산된 아티팩트를 검증해 반환한다."],
    },
}


@router.get(
    "/did",
    response_model=Envelope[DidData],
    summary="이중차분(DID) 추정 결과",
    description=(
        "추정 계수, 표준오차, p값, 신뢰구간, 관측치·군집 수, 처치·비교군 사전사후 평균, "
        "유의성 판정, 해석 주의 문구를 반환한다. 계산은 하지 않고 아티팩트를 읽는다.\n\n"
        "**현재 베이스라인은 유의하지 않다**(계수 +0.9496명/천명, p=0.4631). "
        "`significance.is_significant` 가 false 이며, 프론트는 이 필드로 표기를 결정한다. "
        "효과 크기의 단위는 %p 가 아니라 명/천명이다."
    ),
    responses={
        200: {"content": {"application/json": {"example": DID_EXAMPLE}}},
        500: {"description": "아티팩트가 v1 스키마와 맞지 않음. 어긋난 필드 목록이 함께 온다."},
        503: {"description": "아티팩트 파일 없음."},
    },
)
def did() -> Envelope[DidData]:
    artifact = did_store.load()
    return Envelope[DidData](
        data=DidData(
            design=DidDesign(
                method=artifact.method,
                method_label_ko=artifact.method_label_ko,
                outcome=artifact.outcome,
                outcome_unit=artifact.outcome_unit,
                treated_regions=artifact.treated_regions,
                control_regions=artifact.control_regions,
                treated_region_count=len(artifact.treated_regions),
                control_region_count=len(artifact.control_regions),
                treatment_start=artifact.treatment_start,
                sample_period=artifact.sample_period,
                n_observations=artifact.n_observations,
                n_clusters=artifact.n_clusters,
                standard_error_type=artifact.standard_error_type,
            ),
            effect=DidEffect(
                coefficient=artifact.coefficient,
                unit=artifact.outcome_unit,
                standard_error=artifact.standard_error,
                t_statistic=artifact.t_statistic,
                ci_95_low=artifact.ci_95[0],
                ci_95_high=artifact.ci_95[1],
                r_squared=artifact.r_squared,
            ),
            significance=DidSignificance(
                p_value=artifact.p_value,
                alpha=artifact.alpha,
                is_significant=artifact.is_significant,
                label_ko=artifact.significance_label_ko,
                statement_ko=_significance_statement(artifact),
            ),
            group_means=DidGroupMeans(
                treated_pre_mean=artifact.treated_pre_mean,
                treated_post_mean=artifact.treated_post_mean,
                control_pre_mean=artifact.control_pre_mean,
                control_post_mean=artifact.control_post_mean,
                simple_did_mean_difference=artifact.simple_did_mean_difference,
            ),
            interpretation_cautions=artifact.interpretation_cautions,
            artifact_version=artifact.artifact_version,
            generated_at=artifact.generated_at,
        ),
        meta=Meta(
            source=DID_FILENAME,
            as_of=artifact.sample_period.split("~")[-1],
            data_status="actual",
            notes=[
                "이 서버는 추정을 수행하지 않고 사전 계산된 아티팩트를 검증해 반환한다.",
                f"원본: {', '.join(artifact.source_files) or '미기재'}",
                "효과 크기의 단위는 명/천명이며 %p 가 아니다.",
                *artifact.interpretation_cautions,
            ],
        ),
    )


@router.get(
    "/validation",
    response_model=Envelope[ValidationData],
    summary="시간외 검증 결과",
    description=(
        "2024년 계절 나이브 예측의 전체 오차 지표와 11개 지역별 오차를 반환한다. "
        "예측 진단일 뿐 기금의 인과효과를 입증하지 않는다."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "overall": {
                                "method": "seasonal_naive_y_t_minus_12",
                                "method_label_ko": "계절 나이브(전년 동월) 예측",
                                "outcome": "youth_net_migration_rate_per_1000",
                                "outcome_unit": "명/천명",
                                "test_window": "2024-01 to 2024-12",
                                "n_observations": 132,
                                "mae": 3.1711446949051396,
                                "rmse": 4.265151872241913,
                                "mean_error_bias": -0.2693116998282662,
                                "interpretation": "Forecast diagnostic only; it does not establish the causal effect of the fund.",
                            },
                            "by_region": [
                                {
                                    "region": "청주시",
                                    "n_months": 12,
                                    "actual_mean_rate": 0.3670227544388442,
                                    "predicted_mean_rate": 0.7016024522767389,
                                    "mean_error_bias": -0.3345796978378946,
                                    "mae": 0.7961025713721864,
                                    "rmse": 0.9724265047861128,
                                }
                            ],
                            "artifact_version": "v1",
                            "generated_at": "2026-08-18T21:29:51+09:00",
                        },
                        "meta": {
                            "source": "oot_validation_v1.json",
                            "as_of": "2024-12",
                            "data_status": "actual",
                            "notes": ["예측 진단 지표이며 기금의 인과효과를 입증하지 않는다."],
                        },
                    }
                }
            }
        }
    },
)
def validation() -> Envelope[ValidationData]:
    artifact: ValidationArtifact = validation_store.load()
    return Envelope[ValidationData](
        data=ValidationData(
            overall=ValidationOverall(
                method=artifact.method,
                method_label_ko=artifact.method_label_ko,
                outcome=artifact.outcome,
                outcome_unit=artifact.outcome_unit,
                test_window=artifact.test_window,
                n_observations=artifact.n_observations,
                mae=artifact.mae,
                rmse=artifact.rmse,
                mean_error_bias=artifact.mean_error_bias,
                interpretation=artifact.interpretation,
            ),
            by_region=artifact.by_region,
            artifact_version=artifact.artifact_version,
            generated_at=artifact.generated_at,
        ),
        meta=Meta(
            source=VALIDATION_FILENAME,
            as_of=artifact.test_window.split()[-1].replace("to", "").strip() or "2024-12",
            data_status="actual",
            notes=[
                "예측 진단 지표이며 기금의 인과효과를 입증하지 않는다.",
                "오차가 큰 시군일수록 전년 동월 패턴만으로는 설명되지 않는 변동이 크다는 뜻이다.",
                f"원본: {', '.join(artifact.source_files) or '미기재'}",
            ],
        ),
    )
