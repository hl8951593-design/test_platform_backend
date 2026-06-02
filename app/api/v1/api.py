from fastapi import APIRouter

from app.api.v1.routers import auth

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

