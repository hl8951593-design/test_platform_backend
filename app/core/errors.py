import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id


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
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = _request_id(request)
        _log_http_exception(request, exc, request_id)
        headers = dict(exc.headers or {})
        headers.setdefault("X-Request-ID", request_id)
        return error_response(
            status_code=exc.status_code,
            message=_detail_message(exc.detail, exc.status_code),
            data=exc.detail,
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        request_id = _request_id(request)
        logger.warning(
            "Request validation failed request_id=%s method=%s path=%s errors=%s",
            request_id,
            request.method,
            request.url.path,
            exc.errors(),
        )
        return error_response(
            status_code=422,
            message="request validation failed",
            data=exc.errors(),
            headers={"X-Request-ID": request_id},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = _request_id(request)
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


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    context_request_id = get_request_id()
    if context_request_id and context_request_id != "-":
        return context_request_id
    return request.headers.get("X-Request-ID") or "-"


def _log_http_exception(
    request: Request,
    exc: StarletteHTTPException,
    request_id: str,
) -> None:
    log_method = logger.warning if exc.status_code < 500 else logger.error
    log_method(
        "HTTP exception request_id=%s method=%s path=%s status=%s detail=%s",
        request_id,
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
