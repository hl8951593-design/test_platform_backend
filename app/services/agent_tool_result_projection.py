from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


TOOL_RESULT_PROJECTION_VERSION = "tool_result_projection_v1"
QUERY_PROJECT_CASES_MODEL_VIEW_TARGET_CHARS = 3800
QUERY_PROJECT_CASES_CASES_TARGET_CHARS = 2900
QUERY_PROJECT_CASES_DETAILS_TARGET_CHARS = 500
QUERY_PROJECT_CASES_MAX_CASES = 60
QUERY_PROJECT_CASES_MAX_DETAILS = 20


@dataclass(frozen=True)
class ToolResultProjection:
    model_output: Any
    full_output_size_chars: int
    model_view_chars: int
    compacted: bool
    projection_version: str | None = None


class ToolResultProjectionService:
    """Project full tool results into bounded model-facing views.

    ToolCall.output_json_redacted remains the ledger view. This service only
    decides which fields are safe and useful enough to re-enter model context.
    """

    def project(self, tool_name: str | None, output: Any) -> ToolResultProjection | None:
        if tool_name == "testcase.query_project_cases" and isinstance(output, dict):
            return self.project_query_project_cases(output)
        return None

    def project_query_project_cases(self, output: dict[str, Any]) -> ToolResultProjection:
        rows = [
            self._project_case_row(item)
            for item in (output.get("case_display_rows") or [])
            if isinstance(item, dict)
        ]
        details = self._project_case_details(output)
        snapshot = self._snapshot_summary(output)
        counts = self._case_counts(output, rows)
        model_output: dict[str, Any] = {
            "projection_version": TOOL_RESULT_PROJECTION_VERSION,
            "tool_name": "testcase.query_project_cases",
            "project_id": output.get("project_id"),
            "environment_id": output.get("environment_id"),
            "detail_level": output.get("detail_level"),
            "snapshot": snapshot,
            "counts": counts,
            "cases": [],
        }
        projected_rows = self._fit_items_by_chars(
            rows,
            target_chars=QUERY_PROJECT_CASES_CASES_TARGET_CHARS,
            max_items=QUERY_PROJECT_CASES_MAX_CASES,
        )
        model_output["cases"] = projected_rows
        total_rows = len(rows)
        if len(projected_rows) < total_rows:
            model_output["cases_truncated"] = {
                "returned": len(projected_rows),
                "total": total_rows,
                "full_result_reference": "ToolCall.output_json_redacted",
            }
        if details:
            projected_details = self._fit_items_by_chars(
                details,
                target_chars=QUERY_PROJECT_CASES_DETAILS_TARGET_CHARS,
                max_items=QUERY_PROJECT_CASES_MAX_DETAILS,
            )
            if projected_details:
                model_output["case_details"] = projected_details
            if len(projected_details) < len(details):
                model_output["case_details_truncated"] = {
                    "returned": len(projected_details),
                    "total": len(details),
                    "full_result_reference": "ToolCall.output_json_redacted",
                }
        self._trim_to_target(model_output)
        full_output_size_chars = self._json_size(output)
        model_view_chars = self._json_size(model_output)
        return ToolResultProjection(
            model_output=model_output,
            full_output_size_chars=full_output_size_chars,
            model_view_chars=model_view_chars,
            compacted=True,
            projection_version=TOOL_RESULT_PROJECTION_VERSION,
        )

    @staticmethod
    def _case_counts(output: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, int]:
        http_total = ToolResultProjectionService._safe_int(output.get("http_total"))
        websocket_total = ToolResultProjectionService._safe_int(output.get("websocket_total"))
        if http_total is None:
            http_total = sum(1 for item in rows if item.get("case_type") == "http")
        if websocket_total is None:
            websocket_total = sum(1 for item in rows if item.get("case_type") == "websocket")
        return {
            "http": http_total,
            "websocket": websocket_total,
            "total": http_total + websocket_total,
        }

    @staticmethod
    def _snapshot_summary(output: dict[str, Any]) -> dict[str, Any]:
        case_snapshot = output.get("case_snapshot") if isinstance(output.get("case_snapshot"), dict) else {}
        case_id_manifest = (
            output.get("case_id_manifest")
            if isinstance(output.get("case_id_manifest"), dict)
            else {}
        )
        object_manifest = (
            output.get("object_reference_manifest")
            if isinstance(output.get("object_reference_manifest"), dict)
            else {}
        )
        snapshot_id = (
            case_snapshot.get("snapshot_id")
            or case_id_manifest.get("snapshot_id")
            or object_manifest.get("snapshot_id")
        )
        return {
            key: value
            for key, value in {
                "snapshot_id": snapshot_id,
                "execution_ready": case_snapshot.get("execution_ready"),
                "validity_scope": case_snapshot.get("validity_scope") or case_id_manifest.get("validity_scope"),
            }.items()
            if value is not None
        }

    @staticmethod
    def _project_case_row(item: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = (
            "case_type",
            "id",
            "object_ref",
            "name",
            "method",
            "path",
            "environment_id",
            "last_execution_status",
        )
        return {
            key: ToolResultProjectionService._compact_value(item.get(key), max_string_chars=220)
            for key in allowed_keys
            if key in item and (item.get(key) is not None or key == "last_execution_status")
        }

    def _project_case_details(self, output: dict[str, Any]) -> list[dict[str, Any]]:
        detail_level = str(output.get("detail_level") or "")
        if detail_level not in {"assertions", "selected", "full"}:
            return []
        details: list[dict[str, Any]] = []
        for item in output.get("http_test_cases") or []:
            if isinstance(item, dict):
                detail = self._project_case_detail(item, case_type="http")
                if detail:
                    details.append(detail)
        for item in output.get("websocket_test_cases") or []:
            if isinstance(item, dict):
                detail = self._project_case_detail(item, case_type="websocket")
                if detail:
                    details.append(detail)
        return details

    @classmethod
    def _project_case_detail(cls, item: dict[str, Any], *, case_type: str) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "case_type": case_type,
            "id": item.get("id"),
            "name": cls._compact_value(item.get("name"), max_string_chars=180),
        }
        for key in ("method", "path", "object_ref"):
            value = item.get(key)
            if value is not None:
                detail[key] = cls._compact_value(value, max_string_chars=220)
        assertions = item.get("assertions")
        if isinstance(assertions, list):
            detail["assertions"] = [
                cls._project_assertion(assertion)
                for assertion in assertions[:8]
                if isinstance(assertion, dict)
            ]
            detail["assertion_count"] = len(assertions)
        elif "assertion_count" in item:
            detail["assertion_count"] = item.get("assertion_count")
        extractors = item.get("extractors")
        if isinstance(extractors, list):
            detail["extractors"] = [
                cls._project_extractor(extractor)
                for extractor in extractors[:8]
                if isinstance(extractor, dict)
            ]
            detail["extractor_count"] = len(extractors)
        elif "extractor_count" in item:
            detail["extractor_count"] = item.get("extractor_count")
        return {key: value for key, value in detail.items() if value not in (None, [], {})}

    @classmethod
    def _project_assertion(cls, assertion: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = (
            "name",
            "type",
            "source",
            "field",
            "path",
            "operator",
            "expected",
            "enabled",
        )
        return {
            key: cls._compact_value(assertion.get(key), max_string_chars=160)
            for key in allowed_keys
            if key in assertion and assertion.get(key) is not None
        }

    @classmethod
    def _project_extractor(cls, extractor: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = ("name", "source", "field", "path", "default", "required")
        return {
            key: cls._compact_value(extractor.get(key), max_string_chars=160)
            for key in allowed_keys
            if key in extractor and extractor.get(key) is not None
        }

    @classmethod
    def _compact_value(cls, value: Any, *, max_string_chars: int) -> Any:
        if isinstance(value, str):
            if len(value) <= max_string_chars:
                return value
            return f"[string_truncated chars={len(value)}]"
        if isinstance(value, list):
            return [cls._compact_value(item, max_string_chars=max_string_chars) for item in value[:20]]
        if isinstance(value, dict):
            return {
                str(key): cls._compact_value(item, max_string_chars=max_string_chars)
                for key, item in value.items()
                if str(key) not in {"headers", "body", "query_params", "messages", "subprotocols"}
            }
        return value

    @classmethod
    def _fit_items_by_chars(
        cls,
        items: list[dict[str, Any]],
        *,
        target_chars: int,
        max_items: int,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for item in items[:max_items]:
            candidate = [*selected, item]
            if cls._json_size(candidate) > target_chars and selected:
                break
            selected = candidate
            if cls._json_size(selected) >= target_chars:
                break
        return selected

    @classmethod
    def _trim_to_target(cls, model_output: dict[str, Any]) -> None:
        while cls._json_size(model_output) > QUERY_PROJECT_CASES_MODEL_VIEW_TARGET_CHARS:
            if model_output.get("case_details"):
                removed_total = (
                    model_output.get("case_details_truncated", {}).get("total")
                    or len(model_output["case_details"])
                )
                model_output["case_details"].pop()
                if not model_output["case_details"]:
                    model_output.pop("case_details")
                model_output["case_details_truncated"] = {
                    "returned": len(model_output.get("case_details") or []),
                    "total": removed_total,
                    "full_result_reference": "ToolCall.output_json_redacted",
                }
                continue
            if model_output.get("cases"):
                removed_total = (
                    model_output.get("cases_truncated", {}).get("total")
                    or model_output.get("counts", {}).get("total")
                    or len(model_output["cases"])
                )
                model_output["cases"].pop()
                model_output["cases_truncated"] = {
                    "returned": len(model_output["cases"]),
                    "total": removed_total,
                    "full_result_reference": "ToolCall.output_json_redacted",
                }
                continue
            break

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json_size(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, default=str))
