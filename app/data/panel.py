"""패널 CSV 적재와 구조 검증.

Layer 1(분석 엔진)의 기반이다. 기동 시 한 번 읽어 메모리에 올리고,
같은 입력에 항상 같은 출력을 내는 결정적 계산만 여기서 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.errors import ApiError

# ── 데이터 계약: 이 값들이 어긋나면 적재 자체를 실패시킨다 ────────────────
EXPECTED_ROWS = 1056
EXPECTED_REGIONS = 11
EXPECTED_MONTHS = 96
EXPECTED_START = "2017-01"
EXPECTED_END = "2024-12"

TREATED_REGIONS: tuple[str, ...] = ("제천시", "보은군", "옥천군", "영동군", "괴산군", "단양군")
CONTROL_REGIONS: tuple[str, ...] = ("청주시", "충주시", "증평군", "진천군", "음성군")

# 기금 변수는 연도값을 그 연도 12개월에 그대로 반복 결합한 값이다.
# 월별로 합산하면 12배로 부풀려지므로 지역-연도 단위 중복 제거 후에만 합산한다.
FUND_YEAR_CONSTANT_COLUMNS: tuple[str, ...] = (
    "fund_allocation_million_krw",
    "fund_execution_million_krw",
    "fund_execution_rate",
    "fund_project_count",
    "fund_job_youth_project_count",
    "fund_settlement_service_project_count",
    "fund_job_youth_share",
    "fund_settlement_service_share",
)

# 1인당 지표는 분모가 월별 주민등록인구이므로 지역-연도 안에서도 월마다 값이 다르다.
# 원본 공식은 (연간 기금액 × 1,000,000) / 그 달의 population_total 이다.
# 연도 단위로 하나의 값을 내야 할 때는 임의의 달을 집는 대신 연말(12월) 인구로 다시 계산한다.
FUND_PER_CAPITA_COLUMNS: tuple[str, ...] = (
    "fund_allocation_per_capita_krw",
    "fund_execution_per_capita_krw",
)

FUND_YEARLY_COLUMNS: tuple[str, ...] = FUND_YEAR_CONSTANT_COLUMNS + FUND_PER_CAPITA_COLUMNS

MILLION_KRW = 1_000_000

KEY_COLUMNS: tuple[str, ...] = ("region", "date", "year", "month", "year_month")

OUTCOME_COLUMNS: tuple[str, ...] = (
    "youth_net_migration_rate_per_1000",
    "youth_in_migration_rate_per_1000",
    "youth_out_migration_rate_per_1000",
    "youth_in_migration_20_39",
    "youth_out_migration_20_39",
    "youth_net_migration_20_39",
    "youth_population_20_39",
)

CONTROL_VARIABLE_COLUMNS: tuple[str, ...] = (
    "aged_population_ratio_pct",
    "population_65_plus",
    "population_total",
)

EMPLOYMENT_COLUMNS: tuple[str, ...] = (
    "employment_insured_persons",
    "employment_acquisitions",
    "employment_losses",
    "employment_net_flow",
    "employment_insured_yoy_pct",
)

TREATMENT_COLUMNS: tuple[str, ...] = (
    "is_treated",
    "region_role",
    "post_fund_2022",
    "did_treated_x_post",
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    KEY_COLUMNS
    + OUTCOME_COLUMNS
    + CONTROL_VARIABLE_COLUMNS
    + EMPLOYMENT_COLUMNS
    + FUND_YEARLY_COLUMNS
    + TREATMENT_COLUMNS
)

# employment_insured_yoy_pct 는 2017년 132행이 구조적 결측이다. 절대 보간하지 않는다.
STRUCTURAL_MISSING_YOY_ROWS = 132

FUND_YEARS: tuple[int, ...] = (2022, 2023, 2024)


class PanelValidationError(RuntimeError):
    """패널 CSV가 데이터 계약을 위반했을 때 기동을 중단시킨다."""


@dataclass(frozen=True)
class RegionInfo:
    region: str
    is_treated: bool
    region_role: str


@dataclass
class Panel:
    df: pd.DataFrame
    source_path: Path
    regions: list[RegionInfo]
    checks: dict[str, object] = field(default_factory=dict)

    # ── 기준 정보 ────────────────────────────────────────────────
    @property
    def region_names(self) -> list[str]:
        return [r.region for r in self.regions]

    @property
    def treated_regions(self) -> list[str]:
        return [r.region for r in self.regions if r.is_treated]

    @property
    def control_regions(self) -> list[str]:
        return [r.region for r in self.regions if not r.is_treated]

    @property
    def row_count(self) -> int:
        return int(len(self.df))

    @property
    def period_start(self) -> str:
        return str(self.df["year_month"].min())

    @property
    def period_end(self) -> str:
        return str(self.df["year_month"].max())

    @property
    def available_years(self) -> list[int]:
        return sorted(int(y) for y in self.df["year"].unique())

    def role_of(self, region: str) -> str:
        for info in self.regions:
            if info.region == region:
                return info.region_role
        raise KeyError(region)

    def require_regions(self, regions: list[str]) -> list[str]:
        """지역명 유효성 검사. 없는 지역이면 사용 가능 목록과 함께 404."""
        from app.errors import unknown_region

        known = set(self.region_names)
        for region in regions:
            if region not in known:
                raise unknown_region(region, self.region_names)
        return regions

    def require_year(self, year: int) -> None:
        """패널에 없는 연도는 추정해 채우지 않는다. 호출부가 unavailable 로 응답한다."""
        if year not in self.available_years:
            raise ApiError(
                status_code=404,
                code="year_out_of_range",
                message=(
                    f"{year}년 데이터는 이 패널에 없습니다. "
                    f"수록 기간은 {self.period_start}~{self.period_end} 입니다."
                ),
                field="year",
                allowed_values=[str(y) for y in self.available_years],
            )

    # ── 기금: 지역-연도 단위 중복 제거 ────────────────────────────
    def fund_year_frame(self, year: int | None = None) -> pd.DataFrame:
        """기금 변수를 지역-연도 1행으로 축약한 프레임.

        기금 금액 집계는 반드시 이 프레임을 거쳐야 한다. 월 단위 합산 금지.
        1인당 지표는 연말(12월) 주민등록인구를 분모로 다시 계산한 파생값이다.
        """
        cols = ["region", "year", "is_treated", "region_role", *FUND_YEAR_CONSTANT_COLUMNS]
        frame = (
            self.df.loc[:, cols]
            .drop_duplicates(subset=["region", "year"])
            .merge(self.year_end_population(), on=["region", "year"], how="left")
        )
        frame["fund_allocation_per_capita_krw"] = (
            frame["fund_allocation_million_krw"] * MILLION_KRW / frame["population_total"]
        )
        frame["fund_execution_per_capita_krw"] = (
            frame["fund_execution_million_krw"] * MILLION_KRW / frame["population_total"]
        )
        if year is not None:
            frame = frame.loc[frame["year"] == year]
        return frame.sort_values(["year", "region"]).reset_index(drop=True)

    def year_end_population(self) -> pd.DataFrame:
        """지역-연도별 연말(12월) 주민등록 총인구와 청년인구."""
        december = self.df.loc[self.df["month"] == 12]
        return december.loc[
            :, ["region", "year", "population_total", "youth_population_20_39"]
        ].reset_index(drop=True)


def _read_csv(path: Path) -> pd.DataFrame:
    # 원본 CSV에 BOM이 있어 utf-8-sig 로 읽는다.
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    return df


def _validate(df: pd.DataFrame, path: Path) -> dict[str, object]:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise PanelValidationError(
            f"패널 CSV에 필수 컬럼이 없습니다: {missing} (경로: {path})"
        )

    if len(df) != EXPECTED_ROWS:
        raise PanelValidationError(
            f"패널 행 수가 {EXPECTED_ROWS}행이 아닙니다: {len(df)}행 (경로: {path})"
        )

    regions = sorted(df["region"].unique())
    if len(regions) != EXPECTED_REGIONS:
        raise PanelValidationError(
            f"지역 수가 {EXPECTED_REGIONS}개가 아닙니다: {len(regions)}개 {regions}"
        )

    months = sorted(df["year_month"].unique())
    if len(months) != EXPECTED_MONTHS or months[0] != EXPECTED_START or months[-1] != EXPECTED_END:
        raise PanelValidationError(
            f"기간이 {EXPECTED_START}~{EXPECTED_END} 96개월과 다릅니다: "
            f"{months[0]}~{months[-1]} {len(months)}개월"
        )

    duplicates = int(df.duplicated(subset=["region", "year_month"]).sum())
    if duplicates:
        raise PanelValidationError(f"지역-월 중복 행이 {duplicates}건 있습니다.")

    treated = set(df.loc[df["is_treated"] == 1, "region"].unique())
    control = set(df.loc[df["is_treated"] == 0, "region"].unique())
    if treated != set(TREATED_REGIONS) or control != set(CONTROL_REGIONS):
        raise PanelValidationError(
            "처치군/비교군 구성이 설계와 다릅니다. "
            f"처치군={sorted(treated)}, 비교군={sorted(control)}"
        )

    required_non_null = [
        "youth_population_20_39",
        "youth_in_migration_20_39",
        "youth_out_migration_20_39",
        "youth_net_migration_20_39",
        "youth_net_migration_rate_per_1000",
        "aged_population_ratio_pct",
        "population_total",
        "employment_insured_persons",
    ]
    nulls = {c: int(df[c].isna().sum()) for c in required_non_null}
    offending = {c: n for c, n in nulls.items() if n}
    if offending:
        raise PanelValidationError(f"결측이 허용되지 않는 컬럼에 결측이 있습니다: {offending}")

    # 기금 금액/사업수/비중은 지역-연도 안에서 상수여야 중복 제거 집계가 성립한다.
    grouped = df.groupby(["region", "year"])
    non_constant = [
        column
        for column in FUND_YEAR_CONSTANT_COLUMNS
        if (grouped[column].nunique(dropna=False) > 1).any()
    ]
    if non_constant:
        raise PanelValidationError(
            f"기금 컬럼이 지역-연도 안에서 변동합니다: {non_constant}. "
            "연도값을 월에 결합한 구조가 아니므로 중복 제거 집계를 신뢰할 수 없습니다."
        )

    yoy_missing = int(df["employment_insured_yoy_pct"].isna().sum())
    if yoy_missing != STRUCTURAL_MISSING_YOY_ROWS:
        raise PanelValidationError(
            "employment_insured_yoy_pct 의 구조적 결측이 "
            f"{STRUCTURAL_MISSING_YOY_ROWS}행이어야 하는데 {yoy_missing}행입니다. "
            "보간되었거나 원본이 바뀐 것으로 보입니다."
        )

    return {
        "panel_rows": len(df),
        "region_count": len(regions),
        "month_count": len(months),
        "date_start": months[0],
        "date_end": months[-1],
        "duplicate_region_month_rows": duplicates,
        "missing_required_values": nulls,
        "employment_yoy_structural_missing_rows": yoy_missing,
    }


def load_panel(path: Path | None = None) -> Panel:
    settings = get_settings()
    csv_path = path or settings.resolve(settings.panel_csv)
    if not csv_path.exists():
        raise PanelValidationError(f"패널 CSV를 찾을 수 없습니다: {csv_path}")

    df = _read_csv(csv_path)
    checks = _validate(df, csv_path)

    df["date"] = pd.to_datetime(df["date"])
    df["is_treated"] = df["is_treated"].astype(int)
    df = df.sort_values(["region", "date"]).reset_index(drop=True)

    roles = (
        df.loc[:, ["region", "is_treated", "region_role"]]
        .drop_duplicates()
        .sort_values("region")
    )
    regions = [
        RegionInfo(
            region=str(row.region),
            is_treated=bool(row.is_treated),
            region_role=str(row.region_role),
        )
        for row in roles.itertuples()
    ]

    return Panel(df=df, source_path=csv_path, regions=regions, checks=checks)


@lru_cache
def get_panel() -> Panel:
    """기동 시 1회 적재 후 재사용한다."""
    return load_panel()
