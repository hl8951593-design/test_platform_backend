from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.api.v1.routers.desktop_devices import control_router as desktop_control_router
from app.core.config import settings
from app.core.errors import COMMON_ERROR_RESPONSES, register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_logging import register_request_logging_middleware
from app.services.websocket_debug_session_service import debug_session_manager
from app.services.test_plan_scheduler import test_plan_scheduler
from app.services.execution_metrics_scheduler import execution_metrics_scheduler
from app.services.dashboard_asset_snapshot_scheduler import dashboard_asset_snapshot_scheduler
from app.services.desktop_control_hub import desktop_control_hub
from app.services.ui_execution_lease_scheduler import ui_execution_lease_scheduler
from app.services.ui_execution_artifact_cleanup_scheduler import (
    ui_execution_artifact_cleanup_scheduler,
)


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="自动化测试平台后端 API",
        responses=COMMON_ERROR_RESPONSES,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_request_logging_middleware(application)
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)
    application.include_router(
        desktop_control_router,
        prefix=f"{settings.API_V1_PREFIX}/desktop",
    )
    application.router.add_event_handler("shutdown", debug_session_manager.close_all)
    application.router.add_event_handler("startup", test_plan_scheduler.start)
    application.router.add_event_handler("shutdown", test_plan_scheduler.stop)
    application.router.add_event_handler("startup", execution_metrics_scheduler.start)
    application.router.add_event_handler("shutdown", execution_metrics_scheduler.stop)
    application.router.add_event_handler("startup", dashboard_asset_snapshot_scheduler.start)
    application.router.add_event_handler("shutdown", dashboard_asset_snapshot_scheduler.stop)
    application.router.add_event_handler("startup", desktop_control_hub.start)
    application.router.add_event_handler("shutdown", desktop_control_hub.stop)
    application.router.add_event_handler("startup", ui_execution_lease_scheduler.start)
    application.router.add_event_handler("shutdown", ui_execution_lease_scheduler.stop)
    application.router.add_event_handler("startup", ui_execution_artifact_cleanup_scheduler.start)
    application.router.add_event_handler("shutdown", ui_execution_artifact_cleanup_scheduler.stop)
    register_exception_handlers(application)

    @application.get("/")
    async def root():
        return {"message": settings.PROJECT_NAME}

    return application


app = create_app()
