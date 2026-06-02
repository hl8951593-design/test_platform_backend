from fastapi import FastAPI

from app.api.v1.api import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="自动化测试平台后端 API",
    )
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @application.get("/")
    async def root():
        return {"message": settings.PROJECT_NAME}

    return application


app = create_app()

