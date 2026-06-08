from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest
from app.schemas.user import TokenRead, UserRead


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = UserRepository(db)

    def register(self, payload: RegisterRequest) -> UserRead:
        existing_user = self.repository.get_by_account_phone_or_email(
            payload.account, payload.phone, payload.email
        )
        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="账号、手机号或邮箱已存在",
            )

        try:
            user = self.repository.create(
                username=payload.username,
                avatar=payload.avatar,
                account=payload.account,
                password_hash=hash_password(payload.password),
                phone=payload.phone,
                email=str(payload.email),
            )
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="账号、手机号或邮箱已存在",
            ) from exc

        return UserRead.model_validate(user)

    def login(self, payload: LoginRequest) -> TokenRead:
        user = self.repository.get_by_account(payload.account)
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="账号或密码错误",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户已被禁用",
            )

        return TokenRead(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            user=UserRead.model_validate(user),
        )

    def refresh_token(self, payload: RefreshTokenRequest) -> TokenRead:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌无效",
        )
        try:
            token_payload = decode_refresh_token(payload.refresh_token)
            user_id = token_payload.get("sub")
            if user_id is None:
                raise credentials_exception
            user_id_int = int(user_id)
        except (InvalidTokenError, ValueError) as exc:
            raise credentials_exception from exc

        user = self.repository.get_by_id(user_id_int)
        if user is None:
            raise credentials_exception
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")

        return TokenRead(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            user=UserRead.model_validate(user),
        )
