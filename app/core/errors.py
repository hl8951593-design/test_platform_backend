import logging
import uuid
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    code: int
    message: str
    data: Any = None


COMMON_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "业务请求错误"},
    401: {"model": ErrorResponse, "description": "未认证或凭证无效"},
    403: {"model": ErrorResponse, "description": "权限不足"},
    404: {"model": ErrorResponse, "description": "资源不存在"},
    409: {"model": ErrorResponse, "description": "资源状态或版本冲突"},
    422: {"model": ErrorResponse, "description": "请求参数校验失败"},
    500: {"model": ErrorResponse, "description": "服务内部错误"},
}


def error_response(
    *,
    status_code: int,
    message: str,
    data: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "code": status_code,
                "message": message,
                "data": data,
            }
        ),
        headers=headers,
    )


def register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException):
        return error_response(
            status_code=exc.status_code,
            message=_detail_message(exc.detail, exc.status_code),
            data=exc.detail,
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request, exc: RequestValidationError
    ):
        return error_response(
            status_code=422,
            message="request validation failed",
            data=exc.errors(),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        logger.error(
            "Unhandled request error request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="internal server error",
            data={
                "error": "internal_server_error",
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )


def _detail_message(detail: Any, status_code: int) -> str:
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    try:
        return HTTPStatus(status_code).phrase.lower()
    except ValueError:
        return "request failed"
