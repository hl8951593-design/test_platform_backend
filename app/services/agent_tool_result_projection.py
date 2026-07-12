from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.schemas.execution_diagnostic import ExecutionDiagnosticQuery
from app.services.execution_diagnostic_projection import (
    ExecutionDiagnosticProjectionService,
)


TOOL_RESULT_PROJECTION_VERSION = "tool_result_projection_v1"
QUERY_PROJECT_CASES_MODEL_VIEW_TARGET_CHARS = 3800
QUERY_PROJECT_CASES_CASES_TARGET_CHARS = 2900
QUERY_PROJECT_CASES_DETAILS_TARGET_CHARS = 500
QUERY_PROJECT_CASES_MAX_CASES = 60
QUERY_PROJECT_CASES_MAX_DETAILS = 20
PLATFORM_QUERY_MODEL_VIEW_TARGET_CHARS = 4200
PLATFORM_QUERY_ITEMS_TARGET_CHARS = 3300
PLATFORM_QUERY_MAX_ITEMS = 50
EXECUTION_DIAGNOSTIC_MODEL_MAX_CHARS = 12000
EXECUTION_DIAGNOSTIC_MESSAGE_MAX_CHARS = 14000
PLATFORM_QUERY_CONFIG: dict[str, tuple[str, tuple[str, ...]]] = {
    "execution.query_records": (
        "executions",
        (
            "id", "execution_type", "execution_id", "object_ref", "resource_id", "resource_name",
            "environment_id", "status", "trigger_type", "duration_ms", "error_message", "started_at",
        ),
    ),
    "plan.query_project_plans": (
        "plans",
        (
            "id", "object_ref", "name", "version", "enabled", "trigger_type", "execution_mode",
            "failure_policy", "environment_ids", "target_count", "last_run_at", "next_run_at",
        ),
    ),
    "plan.query_runs": (
        "runs",
        (
            "id", "object_ref", "plan_id", "plan_name", "plan_version", "environment_id", "status",
            "trigger", "target_count", "passed_count", "failed_count", "error_message", "started_at",
        ),
    ),
    "flow.query_project_flows": (
        "flows",
        ("id", "object_ref", "name", "description", "status", "node_count", "current_version", "updated_at"),
    ),
    "defect.query_project_defects": (
        "defects",
        (
            "id", "object_ref", "title", "assignee_name", "bug_type", "urgency", "status",
            "reporter_name", "attachment_count", "updated_at",
        ),
    ),
}


@dataclass(frozen=True)
class ToolResultProjection:
    model_output: Any
    full_output_size_chars: int
    model_view_chars: int
    compacted: bool
    projection_version: str | None = None
    message_budget_chars: int | None = None


class ToolResultProjectionService:
    """Project full tool results into bounded model-facing views.

    ToolCall.output_json_redacted remains the ledger view. This service only
    decides which fields are safe and useful enough to re-enter model context.
    """

    def project(self, tool_name: str | None, output: Any) -> ToolResultProjection | None:
        if tool_name == "execution.read_detail" and isinstance(output, dict):
            return self.project_execution_read_detail(output)
        if tool_name == "testcase.query_project_cases" and isinstance(output, dict):
            return self.project_query_project_cases(output)
        if tool_name == "scenario.compose_draft" and isinstance(output, dict):
            return self.project_scenario_compose_draft(output)
        if tool_name in PLATFORM_QUERY_CONFIG and isinstance(output, dict):
            return self.project_platform_query(tool_name, output)
        return None

    def project_execution_read_detail(
        self, output: dict[str, Any]
    ) -> ToolResultProjection:
        execution = (
            output.get("execution")
            if isinstance(output.get("execution"), dict)
            else {}
        )
        summary = (
            execution.get("summary")
            if isinstance(execution.get("summary"), dict)
            else {}
        )
        status = str(summary.get("status") or "").lower()
        view = "failures" if status in {"failed", "timeout", "error"} else "summary"
        envelope = ExecutionDiagnosticProjectionService().project(
            execution_type=str(output.get("execution_type") or "http"),
            execution=execution,
            query=ExecutionDiagnosticQuery(
                view=view,
                max_chars=EXECUTION_DIAGNOSTIC_MODEL_MAX_CHARS,
            ),
        ).model_dump(mode="json")
        return ToolResultProjection(
            model_output=envelope,
            full_output_size_chars=self._json_size(output),
            model_view_chars=self._json_size(envelope),
            compacted=True,
            projection_version="execution_diagnostic_projection_v1",
            message_budget_chars=EXECUTION_DIAGNOSTIC_MESSAGE_MAX_CHARS,
        )

    def project_scenario_compose_draft(self, output: dict[str, Any]) -> ToolResultProjection:
        draft = output.get("draft") if isinstance(output.get("draft"), dict) else {}
        scenario = draft.get("scenario") if isinstance(draft.get("scenario"), dict) else {}
        nodes = [item for item in (scenario.get("nodes") or []) if isinstance(item, dict)]
        reference_ids: list[int] = []
        for node in nodes:
            step = node.get("test_case") if isinstance(node.get("test_case"), dict) else {}
            reference_id = self._safe_int(step.get("reference_id", step.get("referenceId")))
            if reference_id is not None:
                reference_ids.append(reference_id)
        grounding = draft.get("scenario_grounding") if isinstance(draft.get("scenario_grounding"), dict) else {}
        validation = draft.get("scenario_validation") if isinstance(draft.get("scenario_validation"), dict) else {}
        case_source_summary = (
            draft.get("case_source_summary")
            if isinstance(draft.get("case_source_summary"), dict)
            else {}
        )
        source_reference_ids = [
            value
            for value in (
                self._safe_int(item)
                for item in [
                    *(case_source_summary.get("http_test_case_ids") or []),
                    *(case_source_summary.get("websocket_test_case_ids") or []),
                ]
            )
            if value is not None
        ]
        excluded_nodes = [
            {
                key: item.get(key)
                for key in ("node_id", "reference_id", "reason", "unresolved_variables")
                if item.get(key) not in (None, [], {})
            }
            for item in (grounding.get("excluded_nodes") or [])
            if isinstance(item, dict)
        ]
        excluded_reference_ids = [
            reference_id
            for reference_id in (self._safe_int(item.get("reference_id")) for item in excluded_nodes)
            if reference_id is not None
        ]
        candidate_reference_set = set(reference_ids) | set(excluded_reference_ids)
        candidate_reference_ids = [
            item for item in source_reference_ids if item in candidate_reference_set
        ] or list(dict.fromkeys([*reference_ids, *excluded_reference_ids]))
        omitted_by_composer_reference_ids = [
            item for item in source_reference_ids if item not in candidate_reference_set
        ]
        model_output = {
            "projection_version": TOOL_RESULT_PROJECTION_VERSION,
            "tool_name": "scenario.compose_draft",
            "scenario": {
                "name": scenario.get("name"),
                "environment_id": scenario.get("environment_id"),
                "node_count": len(nodes),
                "reference_ids": reference_ids,
                "dependency_edge_count": validation.get("dependency_edge_count", 0),
            },
            "source": {
                "case_count": case_source_summary.get("case_count", len(source_reference_ids)),
                "reference_ids": source_reference_ids,
            },
            "candidate": {
                "node_count": grounding.get("referenced_node_count", len(candidate_reference_ids)),
                "reference_ids": candidate_reference_ids,
                "omitted_by_composer_reference_ids": omitted_by_composer_reference_ids,
                "omitted_reason_status": "not_recorded_do_not_infer",
            },
            "grounding": {
                "source_case_count": grounding.get("source_case_count"),
                "candidate_node_count": grounding.get("referenced_node_count"),
                "grounded_node_count": grounding.get("grounded_node_count", len(nodes)),
                "excluded_node_count": grounding.get("excluded_node_count", len(excluded_nodes)),
                "excluded_nodes": excluded_nodes,
                "dependency_policy": grounding.get("dependency_policy"),
            },
            "validation": {
                "valid": validation.get("valid") is True,
                "referenced_case_count": validation.get("referenced_case_count"),
                "unresolved_reference_count": validation.get("unresolved_reference_count"),
                "resolved_template_count": validation.get("resolved_template_count"),
                "unresolved_template_count": validation.get("unresolved_template_count"),
                "quality_issue_count": len(validation.get("quality_issues") or []),
                "graph_error_count": len(validation.get("graph_errors") or []),
            },
            "execution": {
                "executed": False,
                "self_validated": False,
            },
            "persistence": {"saved": False},
            "next_actions": (
                ["review_draft", "save_with_approval", "execute_explicit_dry_run"]
                if validation.get("valid") is True
                else ["repair_draft"]
            ),
            "authoritative_summary": (
                f"Source cases={len(source_reference_ids)}; composer candidates={len(candidate_reference_ids)}; "
                f"grounded final nodes={len(nodes)}; omitted by composer={omitted_by_composer_reference_ids} "
                "(reason is not recorded; do not infer one); excluded by grounding="
                f"{excluded_reference_ids}; validation valid={validation.get('valid') is True}; "
                "executed=false; saved=false."
            ),
        }
        model_output = self._drop_none(model_output)
        return ToolResultProjection(
            model_output=model_output,
            full_output_size_chars=self._json_size(output),
            model_view_chars=self._json_size(model_output),
            compacted=True,
            projection_version=TOOL_RESULT_PROJECTION_VERSION,
        )

    def project_platform_query(self, tool_name: str, output: dict[str, Any]) -> ToolResultProjection:
        list_key, allowed_keys = PLATFORM_QUERY_CONFIG[tool_name]
        rows = [
            {
                key: self._compact_value(item.get(key), max_string_chars=220)
                for key in allowed_keys
                if key in item and item.get(key) is not None
            }
            for item in (output.get(list_key) or [])
            if isinstance(item, dict)
        ]
        projected_rows = self._fit_items_by_chars(
            rows,
            target_chars=PLATFORM_QUERY_ITEMS_TARGET_CHARS,
            max_items=PLATFORM_QUERY_MAX_ITEMS,
        )
        manifest = output.get("object_reference_manifest")
        snapshot = {
            key: value
            for key, value in {
                "snapshot_id": manifest.get("snapshot_id") if isinstance(manifest, dict) else None,
                "validity_scope": manifest.get("validity_scope") if isinstance(manifest, dict) else None,
            }.items()
            if value is not None
        }
        model_output: dict[str, Any] = {
            "projection_version": TOOL_RESULT_PROJECTION_VERSION,
            "tool_name": tool_name,
            "project_id": output.get("project_id"),
            "detail_level": output.get("detail_level"),
            "total": output.get("total", len(rows)),
            "page": output.get("page"),
            "page_size": output.get("page_size"),
            "snapshot": snapshot,
            list_key: projected_rows,
        }
        if tool_name == "execution.query_records":
            for key in (
                "pagination_mode",
                "returned",
                "limit",
                "has_more",
                "next_cursor",
            ):
                if key in output:
                    model_output[key] = output.get(key)
        if len(projected_rows) < len(rows):
            model_output[f"{list_key}_truncated"] = {
                "returned": len(projected_rows),
                "total": len(rows),
                "full_result_reference": "ToolCall.output_json_redacted",
            }
        while self._json_size(model_output) > PLATFORM_QUERY_MODEL_VIEW_TARGET_CHARS and model_output[list_key]:
            model_output[list_key].pop()
            model_output[f"{list_key}_truncated"] = {
                "returned": len(model_output[list_key]),
                "total": len(rows),
                "full_result_reference": "ToolCall.output_json_redacted",
            }
        return ToolResultProjection(
            model_output=model_output,
            full_output_size_chars=self._json_size(output),
            model_view_chars=self._json_size(model_output),
            compacted=True,
            projection_version=TOOL_RESULT_PROJECTION_VERSION,
        )

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

    @classmethod
    def _drop_none(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._drop_none(item)
                for key, item in value.items()
                if item is not None
            }
        if isinstance(value, list):
            return [cls._drop_none(item) for item in value]
        return value

    @staticmethod
    def _json_size(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, default=str))
