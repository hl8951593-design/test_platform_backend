from typing import Any

from app.core.response import normalize_response_data


DEFAULT_EXECUTION_POLL_AFTER_MS = 1000
INTERNAL_PENDING_STATUSES = {"queued", "pending"}


def public_execution_status(status: str | None) -> str | None:
    if status in INTERNAL_PENDING_STATUSES:
        return "running"
    return status


def execution_started_payload(
    data: Any,
    *,
    execution_type: str,
    execution_id: int | str,
    project_id: int,
    poll_after_ms: int = DEFAULT_EXECUTION_POLL_AFTER_MS,
) -> dict[str, Any]:
    payload = normalize_response_data(data)
    if not isinstance(payload, dict):
        payload = {"result": payload}

    payload["status"] = public_execution_status(payload.get("status"))
    payload.update(
        {
            "request_status": "started",
            "terminal": payload.get("status") not in {"running"},
            "execution_type": execution_type,
            "execution_id": execution_id,
            "poll_after_ms": poll_after_ms,
            "polling_url": (
                f"/api/v1/execution-records/{execution_type}/{execution_id}"
                f"?project_id={project_id}"
            ),
        }
    )
    return payload
