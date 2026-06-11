from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.core.config import settings
from app.services.websocket_debug_session_service import debug_session_manager
from app.services.test_plan_scheduler import test_plan_scheduler


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="自动化测试平台后端 API",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)
    application.router.add_event_handler("shutdown", debug_session_manager.close_all)
    application.router.add_event_handler("startup", test_plan_scheduler.start)
    application.router.add_event_handler("shutdown", test_plan_scheduler.stop)

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else exc.detail.get("message", "request failed")
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder({"code": exc.status_code, "message": message, "data": exc.detail}),
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(
                {"code": 422, "message": "request validation failed", "data": exc.errors()}
            ),
        )

    @application.get("/")
    async def root():
        return {"message": settings.PROJECT_NAME}

    return application


app = create_app()
