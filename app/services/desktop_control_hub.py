from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Any

import redis.asyncio as async_redis
from fastapi import WebSocket

from app.core.config import settings


logger = logging.getLogger(__name__)


class DesktopControlHub:
    """Local WebSocket registry plus Redis fan-out for multi-process deployments."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._subscriber_task: asyncio.Task | None = None
        self._stopping = False
        self._instance_id = uuid.uuid4().hex

    async def start(self) -> None:
        if self._subscriber_task is not None and not self._subscriber_task.done():
            return
        self._stopping = False
        self._subscriber_task = asyncio.create_task(
            self._subscriber_loop(),
            name="desktop-control-redis-subscriber",
        )

    async def stop(self) -> None:
        self._stopping = True
        task = self._subscriber_task
        self._subscriber_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        connections = [
            websocket
            for group in self._connections.values()
            for websocket in group
        ]
        self._connections.clear()
        for websocket in connections:
            try:
                await websocket.close(code=1012)
            except Exception:
                pass

    async def connect(self, device_public_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[device_public_id].add(websocket)

    def disconnect(self, device_public_id: str, websocket: WebSocket) -> None:
        group = self._connections.get(device_public_id)
        if group is None:
            return
        group.discard(websocket)
        if not group:
            self._connections.pop(device_public_id, None)

    async def send_local(
        self,
        device_public_id: str,
        message: dict[str, Any],
    ) -> None:
        failed: list[WebSocket] = []
        for websocket in tuple(self._connections.get(device_public_id, ())):
            try:
                await websocket.send_json(message)
            except Exception:
                failed.append(websocket)
        for websocket in failed:
            self.disconnect(device_public_id, websocket)

    async def notify_device(
        self,
        device_public_id: str,
        message: dict[str, Any],
    ) -> None:
        await self.send_local(device_public_id, message)
        payload = dict(message)
        payload["_origin"] = self._instance_id
        client = async_redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        try:
            await client.publish(
                f"{settings.DESKTOP_CONTROL_REDIS_CHANNEL_PREFIX}{device_public_id}",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception as exc:
            logger.debug("Desktop Redis control publish unavailable: %s", exc)
        finally:
            await client.aclose()

    async def _subscriber_loop(self) -> None:
        pattern = f"{settings.DESKTOP_CONTROL_REDIS_CHANNEL_PREFIX}*"
        while not self._stopping:
            client = async_redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=1.0,
            )
            pubsub = client.pubsub()
            try:
                await pubsub.psubscribe(pattern)
                while not self._stopping:
                    item = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if not item:
                        await asyncio.sleep(0.05)
                        continue
                    channel = str(item.get("channel") or "")
                    device_public_id = channel.removeprefix(
                        settings.DESKTOP_CONTROL_REDIS_CHANNEL_PREFIX
                    )
                    payload = json.loads(str(item.get("data") or "{}"))
                    if payload.pop("_origin", None) == self._instance_id:
                        continue
                    await self.send_local(device_public_id, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Desktop Redis control subscriber unavailable: %s", exc)
                await asyncio.sleep(settings.DESKTOP_REDIS_RETRY_SECONDS)
            finally:
                try:
                    await pubsub.aclose()
                finally:
                    await client.aclose()


desktop_control_hub = DesktopControlHub()
