from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.core.sensitive_data import mask_sensitive, request_fingerprint


agent_trace_logger = logging.getLogger("app.agent.trace")


def trace_debug(event: str, **fields: Any) -> None:
    agent_trace_logger.debug("%s %s", event, _format_trace_fields(fields))


def trace_info(event: str, **fields: Any) -> None:
    agent_trace_logger.info("%s %s", event, _format_trace_fields(fields))


def trace_warning(event: str, **fields: Any) -> None:
    agent_trace_logger.warning("%s %s", event, _format_trace_fields(fields))


def trace_error(event: str, **fields: Any) -> None:
    agent_trace_logger.error("%s %s", event, _format_trace_fields(fields))


def trace_verbose_payload(event: str, value: Any, *, prefix: str, mask: bool = True, **fields: Any) -> None:
    if not settings.AGENT_TRACE_VERBOSE_PAYLOADS:
        return
    payload_fields = trace_payload_preview(value, prefix=prefix, mask=mask)
    merged_fields = {**payload_fields, **fields}
    trace_info(event, **merged_fields)


def trace_full_payload(event: str, value: Any, *, prefix: str, mask: bool = True, **fields: Any) -> None:
    if not settings.AGENT_TRACE_FULL_PAYLOADS:
        return
    payload_fields = trace_payload_full(value, prefix=prefix, mask=mask)
    merged_fields = {**payload_fields, **fields}
    trace_info(event, **merged_fields)


def trace_payload_summary(value: Any, *, prefix: str) -> dict[str, Any]:
    masked = mask_sensitive(value)
    encoded = json.dumps(masked, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    summary: dict[str, Any] = {
        f"{prefix}_type": type(value).__name__,
        f"{prefix}_size_chars": len(encoded),
        f"{prefix}_hash": request_fingerprint(masked),
    }
    if isinstance(value, dict):
        summary[f"{prefix}_keys"] = sorted(str(key) for key in value.keys())
    elif isinstance(value, list):
        summary[f"{prefix}_count"] = len(value)
    return summary


def trace_payload_preview(value: Any, *, prefix: str, mask: bool = True) -> dict[str, Any]:
    visible_value = mask_sensitive(value) if mask else value
    encoded = _encode_payload_preview_value(visible_value)
    max_chars = max(0, int(settings.AGENT_TRACE_PAYLOAD_MAX_CHARS or 0))
    preview = encoded[:max_chars]
    hash_value = visible_value if not isinstance(visible_value, str) else {"text": visible_value}
    return {
        f"{prefix}_preview": preview,
        f"{prefix}_size_chars": len(encoded),
        f"{prefix}_preview_chars": len(preview),
        f"{prefix}_truncated": len(encoded) > max_chars,
        f"{prefix}_hash": request_fingerprint(hash_value),
    }


def trace_payload_full(value: Any, *, prefix: str, mask: bool = True) -> dict[str, Any]:
    visible_value = mask_sensitive(value) if mask else value
    encoded = _encode_payload_preview_value(visible_value)
    hash_value = visible_value if not isinstance(visible_value, str) else {"text": visible_value}
    return {
        f"{prefix}_full": encoded,
        f"{prefix}_size_chars": len(encoded),
        f"{prefix}_hash": request_fingerprint(hash_value),
    }


def trace_message_summary(messages: list[Any], *, prefix: str = "messages") -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    total_chars = 0
    for message in messages:
        role = str(getattr(message, "role", "unknown") or "unknown")
        content = str(getattr(message, "content", "") or "")
        role_counts[role] = role_counts.get(role, 0) + 1
        total_chars += len(content)
    return {
        f"{prefix}_count": len(messages),
        f"{prefix}_chars": total_chars,
        f"{prefix}_role_counts": role_counts,
    }


def _format_trace_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={_format_trace_value(value)}")
    return " ".join(parts)


def _format_trace_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return str(value).replace("\n", "\\n").replace("\r", "\\r")


def _encode_payload_preview_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
