import json
import re
from dataclasses import dataclass
from typing import Any


_FAILURE_STATUSES = {"failed", "timeout", "error"}
_AUTHORIZATION_CODES = {401, 403, 90001, "401", "403", "90001"}
_AUTHORIZATION_MARKERS = (
    "unauthorized",
    "forbidden",
    "not authorized",
    "未授权",
    "无权限",
    "没有权限",
)


@dataclass(frozen=True)
class FailureIdentity:
    category: str
    signature: str


def assertion_summaries(step: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = step.get("assertion_results") or step.get("assertions") or []
    if not isinstance(raw_items, list):
        return []
    summaries: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        definition = raw.get("assertion")
        if not isinstance(definition, dict):
            definition = raw
        summaries.append(
            {
                "type": _bounded(definition.get("type"), 64),
                "path": _bounded(definition.get("path"), 128),
                "expected": _bounded_value(definition.get("expected")),
                "actual": _bounded_value(raw.get("actual")),
                "passed": bool(raw.get("passed")),
                "message": _bounded(raw.get("message") or raw.get("error"), 256),
            }
        )
    return summaries


def response_summary(step: dict[str, Any]) -> dict[str, Any]:
    raw = step.get("response_snapshot") or step.get("response") or {}
    if not isinstance(raw, dict):
        raw = {}
    body = _parse_body(raw.get("body"))
    status_code = raw.get("status_code")
    if status_code is None:
        status_code = raw.get("status") if isinstance(raw.get("status"), int) else None
    business_code = _first_not_none(raw.get("code"), body.get("code"))
    success = _first_not_none(raw.get("success"), body.get("success"))
    message = _first_not_none(
        raw.get("msg"),
        raw.get("message"),
        body.get("msg"),
        body.get("message"),
    )
    return {
        key: value
        for key, value in {
            "status_code": status_code,
            "business_code": _bounded_value(business_code),
            "success": success if isinstance(success, bool) or success is None else _bounded_value(success),
            "message": _bounded(message, 256),
        }.items()
        if value is not None
    }


def classify_failure(*, execution_type: str, step: dict[str, Any]) -> FailureIdentity:
    response = response_summary(step)
    failed_assertion = next(
        (item for item in assertion_summaries(step) if not item["passed"]), None
    )
    message = str(response.get("message") or step.get("error_message") or "").lower()
    if response.get("business_code") in _AUTHORIZATION_CODES or any(
        marker in message for marker in _AUTHORIZATION_MARKERS
    ):
        category = "authorization"
    elif str(step.get("status") or "").lower() == "timeout":
        category = "timeout"
    elif failed_assertion:
        category = "assertion"
    else:
        category = "execution"
    tokens = [
        execution_type,
        category,
        f"HTTP_{response.get('status_code', 'NA')}",
        f"BUSINESS_{response.get('business_code', 'NA')}",
    ]
    if failed_assertion:
        tokens.extend(
            [
                str(failed_assertion.get("type") or "unknown"),
                str(failed_assertion.get("path") or "root"),
            ]
        )
    normalized = "_".join(_normalize_token(item) for item in tokens)
    return FailureIdentity(category=category, signature=normalized)


def is_failure(step: dict[str, Any]) -> bool:
    return str(step.get("status") or "").lower() in _FAILURE_STATUSES


def _parse_body(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or len(value) > 100_000:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _bounded(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= max_chars else text[:max_chars]


def _bounded_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        return _bounded(value, 256)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        encoded = str(value)
    return _bounded(encoded, 256)


def _normalize_token(value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()
    return normalized or "NA"
