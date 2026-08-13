from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.services.desktop_device_service import (
    DesktopDevicePrincipal,
    DesktopDeviceService,
)


desktop_bearer = HTTPBearer(auto_error=False)


def get_current_desktop_device(
    credentials: HTTPAuthorizationCredentials | None = Depends(desktop_bearer),
    db: Session = Depends(get_db),
) -> DesktopDevicePrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="desktop_device_access_token_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return DesktopDeviceService(db).authenticate_device_access_token(
        credentials.credentials
    )
