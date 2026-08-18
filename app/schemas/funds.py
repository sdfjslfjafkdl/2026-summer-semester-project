"""기금 대시보드 응답 스키마.

집행률은 비율(0~1)과 퍼센트를 함께 준다. 프론트 표기는 퍼센트를 쓰고,
원자료와 대조할 때는 비율을 쓴다. 배분액이 0인 시군의 집행률은 정의되지 않아 null 이다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FundInfo(BaseModel):
    fund_id: str = Field(description="기금 식별자", examples=["local-extinction"])
    name_ko: str = Field(description="기금 이름", examples=["지방소멸대응기금"])
    first_year: int = Field(description="데이터가 존재하는 첫 연도", examples=[2022])
    last_year: int = Field(description="데이터가 존재하는 마지막 연도", examples=[2024])


class FundSummaryData(BaseModel):
    fund_id: str
    fund_name: str
    year: int
    total_allocation_million_krw: float | None = Field(
        default=None, description="총 배분액(백만원). 지역-연도 중복 제거 후 합산."
    )
    total_execution_million_krw: float | None = Field(
        default=None, description="총 집행액(백만원)"
    )
    unexecuted_million_krw: float | None = Field(
        default=None, description="배분액에서 집행액을 뺀 미집행액(백만원)"
    )
    execution_rate: float | None = Field(
        default=None, description="총 집행액 / 총 배분액 (0~1)", examples=[0.4086]
    )
    execution_rate_pct: float | None = Field(
        default=None, description="집행률(%)", examples=[40.86]
    )
    previous_year: int | None = Field(default=None, description="비교 대상 전년도")
    previous_execution_rate_pct: float | None = Field(
        default=None, description="전년 집행률(%)"
    )
    execution_rate_change_pp: float | None = Field(
        default=None, description="전년 대비 집행률 증감(%p)"
    )
    allocation_change_million_krw: float | None = Field(
        default=None, description="전년 대비 배분액 증감(백만원)"
    )
    execution_change_million_krw: float | None = Field(
        default=None, description="전년 대비 집행액 증감(백만원)"
    )
    region_count: int = Field(description="패널에 포함된 전체 시군 수", examples=[11])
    recipient_region_count: int | None = Field(
        default=None, description="해당 연도에 기금을 배분받은 시군 수", examples=[6]
    )
    total_project_count: float | None = Field(default=None, description="기금 사업 총 건수")
    available_years: list[int] = Field(
        default_factory=list, description="이 기금에서 조회 가능한 연도"
    )


class FundRegionRow(BaseModel):
    region: str
    region_role: str = Field(description="treatment 또는 control", examples=["treatment"])
    is_treated: bool
    allocation_million_krw: float
    execution_million_krw: float
    unexecuted_million_krw: float
    execution_rate: float | None = Field(
        default=None, description="배분액이 0이면 정의되지 않아 null"
    )
    execution_rate_pct: float | None = None
    project_count: float
    job_youth_project_count: float
    settlement_service_project_count: float
    job_youth_share: float
    settlement_service_share: float
    population_total: float = Field(description="연말(12월) 주민등록 총인구")
    allocation_per_capita_krw: float = Field(description="연말 인구 기준 1인당 배분액(원)")
    execution_per_capita_krw: float = Field(description="연말 인구 기준 1인당 집행액(원)")


class FundRegionsData(BaseModel):
    fund_id: str
    fund_name: str
    year: int
    regions: list[FundRegionRow] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)


class FundTrendPoint(BaseModel):
    year: int
    total_allocation_million_krw: float
    total_execution_million_krw: float
    execution_rate: float | None
    execution_rate_pct: float | None
    execution_rate_change_pp: float | None = Field(
        default=None, description="직전 연도 대비 집행률 증감(%p)"
    )
    recipient_region_count: int
    total_project_count: float


class FundTrendData(BaseModel):
    fund_id: str
    fund_name: str
    points: list[FundTrendPoint] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
