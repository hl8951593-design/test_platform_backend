from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.core.response import success
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest
from app.services.user_service import UserService

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="用户注册")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = UserService(db).register(payload)
    return success(data=user, message="注册成功")


@router.post("/login", summary="用户登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    token_data = UserService(db).login(payload)
    return success(data=token_data, message="登录成功")


@router.post("/refresh", summary="刷新访问令牌")
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_data = UserService(db).refresh_token(payload)
    return success(data=token_data, message="令牌刷新成功")
