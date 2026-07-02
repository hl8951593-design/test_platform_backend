from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.permission_service import PermissionService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证凭证无效",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except InvalidTokenError as exc:
        raise credentials_exception from exc

    user = UserRepository(db).get_by_id(int(user_id))
    if user is None:
        raise credentials_exception
    return user


def require_project_permission(permission_code: str):
    def dependency(
        project_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        return PermissionService(db).require_project_permission(
            current_user,
            project_id,
            permission_code,
        )

    return dependency


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user
