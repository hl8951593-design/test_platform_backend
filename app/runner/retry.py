import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.schemas.retry import RetryPolicyConfig


SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}


def method_allows_retry(method: str, policy: RetryPolicyConfig) -> bool:
    return policy.retry_unsafe_methods or method.upper() in SAFE_HTTP_METHODS


def retry_delay_seconds(
    policy: RetryPolicyConfig,
    *,
    attempt: int,
    response_headers: dict[str, Any] | None = None,
) -> float:
    if policy.respect_retry_after and response_headers:
        retry_after = next(
            (
                value
                for key, value in response_headers.items()
                if str(key).lower() == "retry-after"
            ),
            None,
        )
        parsed = parse_retry_after(retry_after)
        if parsed is not None:
            return min(parsed, policy.max_delay_ms / 1000)

    cap_ms = min(policy.max_delay_ms, policy.base_delay_ms * (2 ** (attempt - 1)))
    if policy.jitter == "full":
        return random.uniform(0, cap_ms) / 1000
    return cap_ms / 1000


def parse_retry_after(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(float(text), 0)
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max((target - datetime.now(timezone.utc)).total_seconds(), 0)


def failed_assertions_are_retryable(assertion_results: list[dict[str, Any]]) -> bool:
    failed = [item for item in assertion_results if not item.get("passed")]
    return bool(failed) and all(
        bool((item.get("assertion") or {}).get("retry_on_failure"))
        for item in failed
    )
