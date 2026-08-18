"""구조를 통일한 에러 응답.

존재하지 않는 지역이나 지표를 요청하면 사용 가능한 값 목록을 함께 돌려준다.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str = Field(description="기계가 분기할 수 있는 에러 코드", examples=["unknown_region"])
    message: str = Field(description="사람이 읽는 한국어 설명")
    field: str | None = Field(default=None, description="문제가 된 요청 파라미터 이름")
    allowed_values: list[str] | None = Field(
        default=None, description="해당 파라미터에 허용되는 값 목록"
    )
    details: dict[str, Any] | None = Field(default=None, description="추가 진단 정보")


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """도메인 계층에서 던지는 통일 예외."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        field: str | None = None,
        allowed_values: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = ErrorBody(
            code=code,
            message=message,
            field=field,
            allowed_values=allowed_values,
            details=details,
        )


def unknown_region(value: str, allowed: list[str]) -> ApiError:
    return ApiError(
        status_code=404,
        code="unknown_region",
        message=f"'{value}' 는 이 데이터에 없는 지역입니다. 충북 11개 시군만 조회할 수 있습니다.",
        field="regions",
        allowed_values=allowed,
    )


def unknown_metric(value: str, allowed: list[str]) -> ApiError:
    return ApiError(
        status_code=404,
        code="unknown_metric",
        message=f"'{value}' 는 조회할 수 없는 지표입니다. /api/meta/metrics 의 키만 사용할 수 있습니다.",
        field="metric",
        allowed_values=allowed,
    )


def unknown_fund(value: str, allowed: list[str]) -> ApiError:
    return ApiError(
        status_code=404,
        code="unknown_fund",
        message=f"'{value}' 는 등록되지 않은 기금입니다.",
        field="fund_id",
        allowed_values=allowed,
    )


def _json(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=body).model_dump(exclude_none=True),
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _json(exc.status_code, exc.body)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _json(
            exc.status_code,
            ErrorBody(code=f"http_{exc.status_code}", message=str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _json(
            422,
            ErrorBody(
                code="invalid_request",
                message="요청 파라미터가 올바르지 않습니다.",
                details={"errors": exc.errors()},
            ),
        )
