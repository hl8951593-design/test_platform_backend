from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

import redis

from app.core.config import settings


logger = logging.getLogger(__name__)


class DesktopPresenceService:
    """Best-effort Redis presence with database heartbeat fallback."""

    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self._retry_after_monotonic = 0.0

    def _get_client(self) -> redis.Redis | None:
        if self._client is not None:
            return self._client
        if time.monotonic() < self._retry_after_monotonic:
            return None
        try:
            client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            client.ping()
            self._client = client
            return client
        except redis.RedisError as exc:
            self._retry_after_monotonic = (
                time.monotonic() + settings.DESKTOP_REDIS_RETRY_SECONDS
            )
            logger.debug("Desktop Redis presence unavailable: %s", exc)
            return None

    def _mark_unhealthy(self, exc: Exception) -> None:
        logger.debug("Desktop Redis presence operation failed: %s", exc)
        if self._client is not None:
            try:
                self._client.close()
            except redis.RedisError:
                pass
        self._client = None
        self._retry_after_monotonic = (
            time.monotonic() + settings.DESKTOP_REDIS_RETRY_SECONDS
        )

    def mark_online(
        self,
        *,
        device_public_id: str,
        observed_at: datetime,
        runtime_state: dict[str, Any],
    ) -> bool:
        client = self._get_client()
        if client is None:
            return False
        key = f"{settings.DESKTOP_PRESENCE_REDIS_KEY_PREFIX}{device_public_id}"
        value = json.dumps(
            {
                "observed_at": observed_at.isoformat(),
                "runtime_state": runtime_state,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            client.setex(key, settings.DESKTOP_DEVICE_OFFLINE_AFTER_SECONDS, value)
            return True
        except redis.RedisError as exc:
            self._mark_unhealthy(exc)
            return False

    def is_online(self, device_public_id: str) -> bool | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            return bool(
                client.exists(
                    f"{settings.DESKTOP_PRESENCE_REDIS_KEY_PREFIX}{device_public_id}"
                )
            )
        except redis.RedisError as exc:
            self._mark_unhealthy(exc)
            return None

    def forget(self, device_public_id: str) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(
                f"{settings.DESKTOP_PRESENCE_REDIS_KEY_PREFIX}{device_public_id}"
            )
        except redis.RedisError as exc:
            self._mark_unhealthy(exc)


desktop_presence_service = DesktopPresenceService()
