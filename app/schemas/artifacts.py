"""분석 결과 아티팩트 스키마 (v1).

인과추론 모델링은 다른 팀원이 수행하고 결과 JSON만 전달된다. 이 서버는 계산하지 않고
data/artifacts/ 아래 파일을 읽어 반환한다. 그래서 스키마를 여기서 고정하고,
스키마에 맞지 않는 아티팩트가 들어오면 어떤 필드가 어긋났는지 알려주는 검증 오류를 낸다.

새 아티팩트를 넣는 쪽이 지켜야 할 규약:
- artifact_version 을 올린다.
- is_significant 는 p_value 와 alpha 로부터 나온 판정과 일치해야 한다.
  (p=0.4631 을 유의한 결과로 표기한 아티팩트는 적재 단계에서 거부된다.)
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Alpha = Annotated[float, Field(gt=0, lt=1)]


class DidArtifact(BaseModel):
    """이중차분 추정 결과."""

    model_config = {"extra": "forbid"}

    artifact_version: str = Field(description="아티팩트 스키마 버전", examples=["v1"])
    generated_at: str = Field(description="산출 시각(ISO 8601)", examples=["2026-08-18T00:00:00+09:00"])
    generated_by: str | None = Field(default=None, description="산출 주체/스크립트")

    method: str = Field(description="추정 방법 이름", examples=["two_way_fixed_effects_ols"])
    method_label_ko: str = Field(description="화면 표기용 방법 이름", examples=["양방향 고정효과 DID"])
    outcome: str = Field(description="결과변수 키", examples=["youth_net_migration_rate_per_1000"])
    outcome_unit: str = Field(description="계수의 단위", examples=["명/천명"])

    treated_regions: list[str] = Field(min_length=1, description="처치군 지역 목록")
    control_regions: list[str] = Field(min_length=1, description="비교군 지역 목록")
    treatment_start: str = Field(description="처치 시점(YYYY-MM)", examples=["2022-01"])
    sample_period: str = Field(description="추정 표본 기간", examples=["2017-01~2024-12"])

    coefficient: float = Field(description="추정 계수", examples=[0.9496181198273366])
    standard_error: float = Field(description="표준오차", examples=[1.2447543537087846])
    standard_error_type: str = Field(
        description="표준오차 종류", examples=["clustered_by_municipality"]
    )
    t_statistic: float | None = Field(default=None, description="t 통계량")
    p_value: float = Field(ge=0, le=1, description="p값", examples=[0.46314203447465774])
    ci_95: list[float] = Field(
        min_length=2, max_length=2, description="95% 신뢰구간 [하한, 상한]"
    )
    alpha: Alpha = Field(default=0.05, description="유의수준")
    is_significant: bool = Field(
        description="유의성 판정. p_value 와 alpha 로부터 나온 값과 일치해야 한다."
    )
    significance_label_ko: str = Field(
        description="화면 표기용 판정 문구", examples=["통계적으로 유의하지 않음"]
    )

    n_observations: int = Field(gt=0, description="관측치 수", examples=[1056])
    n_clusters: int = Field(gt=0, description="군집 수", examples=[11])
    r_squared: float | None = Field(default=None, description="결정계수")
    n_model_parameters: int | None = Field(default=None, description="모형 모수 개수")

    treated_pre_mean: float | None = Field(default=None, description="처치군 사전 평균")
    treated_post_mean: float | None = Field(default=None, description="처치군 사후 평균")
    control_pre_mean: float | None = Field(default=None, description="비교군 사전 평균")
    control_post_mean: float | None = Field(default=None, description="비교군 사후 평균")
    simple_did_mean_difference: float | None = Field(
        default=None, description="단순 DID 평균차"
    )

    interpretation_cautions: list[str] = Field(
        min_length=1, description="해석 주의 문구. 응답에 항상 함께 나간다."
    )
    source_files: list[str] = Field(
        default_factory=list, description="이 아티팩트를 만든 원본 파일"
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> "DidArtifact":
        expected = self.p_value < self.alpha
        if self.is_significant != expected:
            raise ValueError(
                f"is_significant={self.is_significant} 인데 p_value={self.p_value}, "
                f"alpha={self.alpha} 기준 판정은 {expected} 입니다. "
                "유의성 표기를 임의로 바꾼 아티팩트는 사용할 수 없습니다."
            )
        low, high = self.ci_95
        if low > high:
            raise ValueError(f"ci_95 의 하한({low})이 상한({high})보다 큽니다.")
        if not (low <= self.coefficient <= high):
            raise ValueError(
                f"coefficient({self.coefficient})가 ci_95 {self.ci_95} 밖에 있습니다."
            )
        overlap = set(self.treated_regions) & set(self.control_regions)
        if overlap:
            raise ValueError(f"처치군과 비교군에 같은 지역이 있습니다: {sorted(overlap)}")
        return self


class RegionErrorRow(BaseModel):
    model_config = {"extra": "forbid"}

    region: str
    n_months: int = Field(gt=0)
    actual_mean_rate: float
    predicted_mean_rate: float
    mean_error_bias: float
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)


class ValidationArtifact(BaseModel):
    """시간외 검증(out-of-time) 결과."""

    model_config = {"extra": "forbid"}

    artifact_version: str
    generated_at: str
    generated_by: str | None = None

    method: str = Field(description="예측 방법", examples=["seasonal_naive_y_t_minus_12"])
    method_label_ko: str = Field(examples=["계절 나이브(전년 동월)"])
    outcome: str = Field(examples=["youth_net_migration_rate_per_1000"])
    outcome_unit: str = Field(examples=["명/천명"])
    test_window: str = Field(description="검증 구간", examples=["2024-01 to 2024-12"])
    n_observations: int = Field(gt=0, examples=[132])
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)
    mean_error_bias: float
    interpretation: str = Field(description="이 지표가 무엇을 말하고 무엇을 말하지 않는지")
    by_region: list[RegionErrorRow] = Field(min_length=1, description="지역별 오차")
    source_files: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "ValidationArtifact":
        if self.rmse < self.mae:
            raise ValueError(f"rmse({self.rmse})가 mae({self.mae})보다 작습니다.")
        regions = [row.region for row in self.by_region]
        if len(regions) != len(set(regions)):
            raise ValueError("by_region 에 중복 지역이 있습니다.")
        return self


class SpecRow(BaseModel):
    """진단 사양 한 줄(기본 DID, 추세 통제 등)."""

    model_config = {"extra": "forbid"}

    label: str = Field(description="사양 이름", examples=["기본 DID", "처치군 추세 통제"])
    coefficient: float = Field(description="추정 계수")
    cluster_p: float = Field(ge=0, le=1, description="군집 표준오차 기반 p값")
    wild_bootstrap_p: float = Field(ge=0, le=1, description="와일드 클러스터 부트스트랩 p값")
    is_significant: bool = Field(description="유의성 판정. 부트스트랩 p와 alpha 기준 판정과 일치해야 한다.")


class MechanismRow(BaseModel):
    """원인 분해 진단 한 줄(전출률/전입률)."""

    model_config = {"extra": "forbid"}

    label: str = Field(description="지표 이름", examples=["청년 총전출률"])
    coefficient: float
    cluster_p: float = Field(ge=0, le=1)
    wild_bootstrap_p: float = Field(ge=0, le=1)
    note: str | None = Field(default=None, description="해석 메모")


class Mechanism(BaseModel):
    model_config = {"extra": "forbid"}

    specification: str = Field(description="어떤 사양의 값인지", examples=["처치군 추세 통제"])
    out_migration_rate: MechanismRow
    in_migration_rate: MechanismRow


class ParallelTrend(BaseModel):
    model_config = {"extra": "forbid"}

    linear_trend_p: float = Field(ge=0, le=1, description="처치군×선형추세 검정 p값")
    leads_joint_p: float = Field(ge=0, le=1, description="처치군×연도 리드 공동검정 p값")
    rejected: bool = Field(description="평행추세 기각 여부")
    note: str | None = None


class DiagnosticsArtifact(BaseModel):
    """DID 강건성·진단 요약(v3). 여러 사양과 원인 분해, 평행추세를 한 번에 담는다.

    효과 '입증'이 아니라 '검증 파이프라인·탐색적 추정'을 보여주는 용도다.
    각 사양의 is_significant 는 부트스트랩 p값과 alpha 기준 판정과 일치해야 한다.
    """

    model_config = {"extra": "forbid"}

    artifact_version: str
    generated_at: str
    generated_by: str | None = None

    outcome: str = Field(examples=["youth_net_migration_rate_per_1000"])
    outcome_unit: str = Field(examples=["명/천명"])
    treated_regions: list[str] = Field(min_length=1)
    control_regions: list[str] = Field(min_length=1)
    sample_period: str = Field(examples=["2017-01~2024-12"])
    alpha: Alpha = Field(default=0.05)

    specifications: list[SpecRow] = Field(min_length=1, description="사양별 DID 결과")
    mechanism: Mechanism | None = Field(default=None, description="전출/전입 원인 분해")
    parallel_trend: ParallelTrend | None = Field(default=None)

    conclusion_ko: str = Field(description="화면 표기용 종합 결론")
    interpretation_cautions: list[str] = Field(
        min_length=1, description="해석 주의 문구. 응답에 항상 함께 나간다."
    )
    source_files: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "DiagnosticsArtifact":
        for spec in self.specifications:
            expected = spec.wild_bootstrap_p < self.alpha
            if spec.is_significant != expected:
                raise ValueError(
                    f"사양 '{spec.label}' 의 is_significant={spec.is_significant} 인데 "
                    f"wild_bootstrap_p={spec.wild_bootstrap_p}, alpha={self.alpha} 기준 "
                    f"판정은 {expected} 입니다. 유의성 표기를 임의로 바꿀 수 없습니다."
                )
        overlap = set(self.treated_regions) & set(self.control_regions)
        if overlap:
            raise ValueError(f"처치군과 비교군에 같은 지역이 있습니다: {sorted(overlap)}")
        return self


ArtifactKind = Literal["did", "validation", "diagnostics"]
