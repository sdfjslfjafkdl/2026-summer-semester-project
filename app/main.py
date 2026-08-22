"""FastAPI 진입점.

Layer 1(결정적 분석 엔진)과 Layer 2(자연어 에이전트)를 한 프로세스에서 서빙한다.
Layer 2 는 Layer 1 이 반환한 값만 인용하며 숫자를 스스로 만들지 않는다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.data.panel import get_panel
from app.errors import register_error_handlers
from app.routers import (
    analysis,
    chat,
    evidence,
    funds,
    health,
    meta,
    panel as panel_router,
    plan,
    proposal,
)

logger = logging.getLogger(__name__)

DESCRIPTION = """
충북 지방소멸대응기금의 성과를 **집행률이 아니라 청년 순이동률**로 평가하는 API 서버.

## 계층
- **Layer 1 분석 엔진**: 패널 집계, 기금 지표, 사전계산 분석 아티팩트, 근거 검색. LLM을 호출하지 않는 결정적 계산.
- **Layer 2 에이전트**: 자연어 질문을 Layer 1 호출로 라우팅하고 결과를 서술. 숫자는 Layer 1 반환값만 인용한다.

## 응답 규약
모든 응답은 `{"data": ..., "meta": {...}}` 봉투를 따른다.
`meta.data_status` 는 `actual`(원자료 실재), `unavailable`(요청 범위에 데이터 없음),
`derived`(원자료로부터 규칙에 따라 계산) 세 가지뿐이다.

## 데이터 범위
충북 11개 시군, 2017-01 ~ 2024-12(96개월), 지방소멸대응기금 1종.
2025년 이후 값은 패널에 없으며 추정해 채우지 않는다.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    panel = get_panel()
    logger.info(
        "패널 적재 완료: %d행, 지역 %d개, 기간 %s~%s, LLM=%s",
        panel.row_count,
        len(panel.regions),
        panel.period_start,
        panel.period_end,
        settings.llm_active,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="충북 지방소멸대응기금 성과분석 API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(funds.router)
    app.include_router(panel_router.router)
    app.include_router(analysis.router)
    app.include_router(evidence.router)
    app.include_router(proposal.router)
    app.include_router(plan.router)
    app.include_router(chat.router)
    return app


app = create_app()
