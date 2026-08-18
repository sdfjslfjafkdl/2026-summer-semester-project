"""모든 응답이 공유하는 봉투 구조.

data 에는 실제 값, meta 에는 출처와 기준 정보를 담는다.
data_status 는 actual | unavailable | derived 세 가지뿐이다.
목업 값을 뜻하는 상태는 존재하지 않는다.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

DataStatus = Literal["actual", "unavailable", "derived"]

PANEL_SOURCE = "chungbuk_monthly_model_panel_2017_2024.csv"
PANEL_AS_OF = "2024-12"

T = TypeVar("T")


class Meta(BaseModel):
    source: str = Field(
        description="응답 수치가 유래한 원본 파일 또는 아티팩트 이름",
        examples=[PANEL_SOURCE],
    )
    as_of: str = Field(
        description="데이터 기준 시점 (YYYY-MM 또는 YYYY)",
        examples=[PANEL_AS_OF],
    )
    data_status: DataStatus = Field(
        description=(
            "actual: 원자료에 실재하는 값 / "
            "unavailable: 요청 범위에 데이터가 없음 / "
            "derived: 원자료로부터 규칙에 따라 계산한 값"
        ),
        examples=["actual"],
    )
    notes: list[str] = Field(
        default_factory=list,
        description="집계 규칙, 한계, 해석 주의 등 수치를 읽을 때 필요한 문장",
    )


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


def panel_meta(
    *,
    as_of: str = PANEL_AS_OF,
    data_status: DataStatus = "actual",
    notes: list[str] | None = None,
    source: str = PANEL_SOURCE,
) -> Meta:
    return Meta(
        source=source,
        as_of=as_of,
        data_status=data_status,
        notes=notes or [],
    )
