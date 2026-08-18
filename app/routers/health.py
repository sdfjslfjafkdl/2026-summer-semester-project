"""기동 상태와 적재 결과."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.data.panel import get_panel
from app.schemas.envelope import Envelope, panel_meta

router = APIRouter(prefix="/api", tags=["기준 정보"])


class HealthData(BaseModel):
    status: str = Field(description="ok 이면 패널 적재와 계약 검증을 모두 통과한 상태", examples=["ok"])
    panel_rows: int = Field(description="적재된 패널 행 수", examples=[1056])
    region_count: int = Field(description="지역 수", examples=[11])
    month_count: int = Field(description="월 수", examples=[96])
    period_start: str = Field(description="패널 시작월", examples=["2017-01"])
    period_end: str = Field(description="패널 종료월", examples=["2024-12"])
    treated_region_count: int = Field(description="처치군 시군 수", examples=[6])
    control_region_count: int = Field(description="비교군 시군 수", examples=[5])
    llm_enabled: bool = Field(
        description="Layer 2 에이전트가 LLM을 호출할 수 있는 상태인지. false 면 규칙 기반 폴백으로 동작한다.",
        examples=[False],
    )
    app_env: str = Field(description="실행 환경", examples=["local"])


@router.get(
    "/health",
    response_model=Envelope[HealthData],
    summary="기동 상태 확인",
    description="패널 적재 행 수와 기간, LLM 활성 여부를 반환한다. 배포 헬스체크와 데모 전 점검용.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "data": {
                            "status": "ok",
                            "panel_rows": 1056,
                            "region_count": 11,
                            "month_count": 96,
                            "period_start": "2017-01",
                            "period_end": "2024-12",
                            "treated_region_count": 6,
                            "control_region_count": 5,
                            "llm_enabled": False,
                            "app_env": "local",
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
def health() -> Envelope[HealthData]:
    panel = get_panel()
    settings = get_settings()
    return Envelope[HealthData](
        data=HealthData(
            status="ok",
            panel_rows=panel.row_count,
            region_count=len(panel.regions),
            month_count=int(panel.df["year_month"].nunique()),
            period_start=panel.period_start,
            period_end=panel.period_end,
            treated_region_count=len(panel.treated_regions),
            control_region_count=len(panel.control_regions),
            llm_enabled=settings.llm_active,
            app_env=settings.app_env,
        ),
        meta=panel_meta(as_of=panel.period_end),
    )
