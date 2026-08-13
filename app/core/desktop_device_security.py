from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import settings


DEVICE_ACCESS_TOKEN_TYPE = "desktop_device_access"


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc_rfc3339(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hash_installation_id(*, owner_id: int, installation_id: str) -> str:
    value = f"{owner_id}:{installation_id.strip()}".encode("utf-8")
    return hmac.new(
        settings.JWT_SECRET_KEY.encode("utf-8"),
        value,
        hashlib.sha256,
    ).hexdigest()


def hash_refresh_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_refresh_secret(*, secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_secret(secret), expected_hash)


@dataclass(frozen=True)
class IssuedDeviceRefreshToken:
    credential_id: str
    secret: str
    token: str
    secret_hash: str


def issue_device_refresh_token() -> IssuedDeviceRefreshToken:
    credential_id = f"dcred_{secrets.token_urlsafe(18)}"
    secret = secrets.token_urlsafe(48)
    return IssuedDeviceRefreshToken(
        credential_id=credential_id,
        secret=secret,
        token=f"{credential_id}.{secret}",
        secret_hash=hash_refresh_secret(secret),
    )


def rotate_device_refresh_token(credential_id: str) -> IssuedDeviceRefreshToken:
    secret = secrets.token_urlsafe(48)
    return IssuedDeviceRefreshToken(
        credential_id=credential_id,
        secret=secret,
        token=f"{credential_id}.{secret}",
        secret_hash=hash_refresh_secret(secret),
    )


def parse_device_refresh_token(token: str) -> tuple[str, str]:
    credential_id, separator, secret = token.partition(".")
    if (
        not separator
        or not credential_id.startswith("dcred_")
        or len(credential_id) > 64
        or len(secret) < 32
    ):
        raise ValueError("invalid desktop device refresh token")
    return credential_id, secret


def create_device_access_token(
    *,
    device_public_id: str,
    owner_id: int,
    credential_id: str,
) -> str:
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.DESKTOP_DEVICE_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": device_public_id,
        "owner_id": owner_id,
        "credential_id": credential_id,
        "type": DEVICE_ACCESS_TOKEN_TYPE,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_device_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    if payload.get("type") != DEVICE_ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("desktop device token type invalid")
    if not payload.get("sub") or not payload.get("credential_id"):
        raise jwt.InvalidTokenError("desktop device token payload invalid")
    return payload
