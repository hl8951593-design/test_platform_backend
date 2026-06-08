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
                detail="DeepSeek API Key 未配置",
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
                detail=f"DeepSeek 请求失败: {exc}",
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
            return f"DeepSeek 返回异常状态: {response.status_code}"

        error = data.get("error")
        if isinstance(error, dict):
            return error.get("message") or f"DeepSeek 返回异常状态: {response.status_code}"
        return f"DeepSeek 返回异常状态: {response.status_code}"
