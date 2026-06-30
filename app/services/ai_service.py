import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.ai import AIChatRequest, AIChatResponse, AIProviderRead


class AIService:
    provider = "deepseek"

    def provider_config(self) -> AIProviderRead:
        return AIProviderRead(
            provider=self.provider,
            base_url=settings.DEEPSEEK_BASE_URL,
            default_model=settings.DEEPSEEK_MODEL,
            configured=bool(settings.DEEPSEEK_API_KEY),
        )

    def chat(self, payload: AIChatRequest) -> AIChatResponse:
        if not settings.DEEPSEEK_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="DeepSeek API Key is not configured",
            )

        request_body = self._build_chat_payload(payload)
        endpoint = f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=settings.DEEPSEEK_TIMEOUT_SECONDS) as client:
                response = client.post(endpoint, headers=headers, json=request_body)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=self._extract_error_message(exc.response),
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"DeepSeek request failed: {exc}",
            ) from exc

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return AIChatResponse(
            provider=self.provider,
            model=data.get("model") or request_body["model"],
            content=message.get("content") or "",
            usage=data.get("usage"),
            finish_reason=choice.get("finish_reason"),
        )

    def chat_stream(self, payload: AIChatRequest) -> Iterator[dict[str, Any]]:
        if not settings.DEEPSEEK_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="DeepSeek API Key is not configured",
            )

        request_body = self._build_chat_payload(payload)
        request_body["stream"] = True
        endpoint = f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

        max_retries = max(0, int(settings.DEEPSEEK_STREAM_MAX_RETRIES))
        failed_attempts = 0
        while True:
            yielded_any = False
            try:
                for item in self._chat_stream_once(
                    endpoint=endpoint,
                    headers=headers,
                    request_body=request_body,
                ):
                    yielded_any = True
                    yield item
                return
            except HTTPException as exc:
                if yielded_any or failed_attempts >= max_retries or not self._is_retryable_stream_error(exc):
                    raise
                failed_attempts += 1
                delay_seconds = self._stream_retry_delay(failed_attempts)
                yield {
                    "type": "retry",
                    "attempt": failed_attempts,
                    "max_retries": max_retries,
                    "delay_seconds": delay_seconds,
                    "error_message": self._http_exception_message(exc),
                }
                time.sleep(delay_seconds)

    def _chat_stream_once(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        request_body: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        try:
            with httpx.Client(timeout=settings.DEEPSEEK_TIMEOUT_SECONDS) as client:
                with client.stream("POST", endpoint, headers=headers, json=request_body) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        text = line.removeprefix("data:").strip()
                        if text == "[DONE]":
                            break
                        try:
                            data = json.loads(text)
                        except ValueError:
                            continue
                        choice = (data.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield {"type": "delta", "content": content}
                        finish_reason = choice.get("finish_reason")
                        if finish_reason:
                            yield {
                                "type": "done",
                                "finish_reason": finish_reason,
                                "model": data.get("model") or request_body["model"],
                                "usage": data.get("usage"),
                            }
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=self._extract_error_message(exc.response),
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"DeepSeek request failed: {exc}",
            ) from exc

    def _is_retryable_stream_error(self, exc: HTTPException) -> bool:
        return exc.status_code in {
            status.HTTP_502_BAD_GATEWAY,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            status.HTTP_504_GATEWAY_TIMEOUT,
        }

    def _stream_retry_delay(self, attempt: int) -> float:
        base = max(0.0, float(settings.DEEPSEEK_STREAM_RETRY_BASE_SECONDS))
        cap = max(base, float(settings.DEEPSEEK_STREAM_RETRY_MAX_SECONDS))
        return min(cap, base * (2 ** max(0, attempt - 1)))

    def _http_exception_message(self, exc: HTTPException) -> str:
        if isinstance(exc.detail, str):
            return exc.detail
        return str(exc.detail)

    def _build_chat_payload(self, payload: AIChatRequest) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "model": payload.model or settings.DEEPSEEK_MODEL,
            "messages": [message.model_dump() for message in payload.messages],
        }
        if payload.temperature is not None:
            request_body["temperature"] = payload.temperature
        if payload.max_tokens is not None:
            request_body["max_tokens"] = payload.max_tokens
        if payload.thinking is not None:
            request_body["thinking"] = {"type": payload.thinking}
        if payload.reasoning_effort is not None:
            request_body["reasoning_effort"] = payload.reasoning_effort
        if payload.response_format == "json":
            request_body["response_format"] = {"type": "json_object"}
        return request_body

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return f"DeepSeek returned HTTP status {response.status_code}"

        error = data.get("error")
        if isinstance(error, dict):
            return error.get("message") or f"DeepSeek returned HTTP status {response.status_code}"
        return f"DeepSeek returned HTTP status {response.status_code}"
