from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentRun, AgentToolCall
from app.models.project import ProjectEnvironment, ProjectEnvironmentVariable
from app.models.test_case import TestCase
from app.models.websocket_test_case import WebSocketTestCase


TEST_CASE_QUERY_ARTIFACT_TYPE = "test_case_query_snapshot"
TEST_CASE_QUERY_TOOL_NAME = "testcase.query_project_cases"


@dataclass(frozen=True)
class ResolvedScenarioSource:
    project_id: int
    environment_id: int
    case_snapshot_id: str | None
    http_case_ids: tuple[int, ...]
    websocket_case_ids: tuple[int, ...]
    case_snapshots: tuple[dict[str, Any], ...]
    evidence_sources: tuple[dict[str, Any], ...]
    environment_variable_names: tuple[str, ...] = ()


class AgentScenarioSourceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(
        self,
        *,
        project_id: int,
        user_id: int,
        conversation_id: str | None,
        case_source: dict[str, Any],
        environment_id: int,
    ) -> ResolvedScenarioSource:
        artifact_id = str(case_source.get("artifact_id") or "").strip()
        output_hash = str(case_source.get("output_hash") or "").strip()
        parsed = _parse_case_source_artifact_id(artifact_id)
        if parsed is None or not output_hash:
            self._invalid("artifact_reference_invalid", artifact_id=artifact_id)
        tool_call_id = parsed["tool_call_id"]

        row = self.db.execute(
            select(AgentToolCall, AgentRun)
            .join(AgentRun, AgentRun.run_id == AgentToolCall.run_id)
            .where(
                AgentToolCall.tool_call_id == tool_call_id,
                AgentToolCall.tool_name == TEST_CASE_QUERY_TOOL_NAME,
                AgentToolCall.status == "succeeded",
                AgentRun.project_id == project_id,
                AgentRun.user_id == user_id,
            )
        ).first()
        if row is None:
            self._invalid("tool_call_not_accessible", artifact_id=artifact_id)
        call, source_run = row
        if conversation_id is not None and source_run.conversation_id != conversation_id:
            self._invalid("conversation_mismatch", artifact_id=artifact_id)
        if call.output_hash != output_hash:
            self._invalid("output_hash_mismatch", artifact_id=artifact_id)
        output = call.output_json_redacted
        if not isinstance(output, dict):
            self._invalid("tool_output_missing", artifact_id=artifact_id)
        if _optional_int(output.get("project_id")) != project_id:
            self._invalid("output_project_mismatch", artifact_id=artifact_id)
        output_environment_id = _optional_int(output.get("environment_id"))
        if output_environment_id is not None and output_environment_id != environment_id:
            self._invalid("output_environment_mismatch", artifact_id=artifact_id)

        environment = self.db.scalar(
            select(ProjectEnvironment).where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )
        if environment is None:
            self._invalid("environment_not_accessible", environment_id=environment_id)

        manifest = output.get("case_id_manifest") if isinstance(output.get("case_id_manifest"), dict) else {}
        http_ids = _int_tuple(manifest.get("http_test_case_ids") or output.get("http_test_case_ids"))
        websocket_ids = _int_tuple(
            manifest.get("websocket_test_case_ids") or output.get("websocket_test_case_ids")
        )
        http_cases = {
            item.id: item
            for item in self.db.scalars(
                select(TestCase).where(
                    TestCase.project_id == project_id,
                    TestCase.id.in_(http_ids or [-1]),
                )
            ).all()
        }
        websocket_cases = {
            item.id: item
            for item in self.db.scalars(
                select(WebSocketTestCase).where(
                    WebSocketTestCase.project_id == project_id,
                    WebSocketTestCase.id.in_(websocket_ids or [-1]),
                )
            ).all()
        }
        missing_http = sorted(set(http_ids) - set(http_cases))
        missing_websocket = sorted(set(websocket_ids) - set(websocket_cases))
        if missing_http or missing_websocket:
            self._invalid(
                "case_reference_stale",
                missing_http_test_case_ids=missing_http,
                missing_websocket_test_case_ids=missing_websocket,
            )

        object_refs = _object_refs_by_identity(output)
        snapshots: list[dict[str, Any]] = []
        for case_id in http_ids:
            case = http_cases[case_id]
            self._require_environment_compatible(case, environment_id=environment_id, case_type="http")
            snapshots.append({
                "id": case.id,
                "reference_id": case.id,
                "object_ref": object_refs.get(("http", case.id)),
                "case_type": "http",
                "name": case.name,
                "method": case.method,
                "path": case.path,
                "environment_ids": list(case.environment_ids),
                "headers": case.headers or {},
                "query_params": case.query_params or {},
                "body_type": case.body_type,
                "body": case.body,
                "assertions": case.assertions or [],
                "extractors": case.extractors or [],
                "retry_policy": case.retry_policy or {},
            })
        for case_id in websocket_ids:
            case = websocket_cases[case_id]
            self._require_environment_compatible(case, environment_id=environment_id, case_type="websocket")
            snapshots.append({
                "id": case.id,
                "reference_id": case.id,
                "object_ref": object_refs.get(("websocket", case.id)),
                "case_type": "websocket",
                "name": case.name,
                "path": case.path,
                "environment_ids": list(case.environment_ids),
                "headers": case.headers or {},
                "subprotocols": case.subprotocols or [],
                "messages": case.messages or [],
                "assertions": case.assertions or [],
                "extractors": case.extractors or [],
                "retry_policy": case.retry_policy or {},
            })

        case_snapshot = output.get("case_snapshot") if isinstance(output.get("case_snapshot"), dict) else {}
        environment_variable_names = tuple(self.db.scalars(
            select(ProjectEnvironmentVariable.name)
            .where(ProjectEnvironmentVariable.environment_id == environment_id)
            .order_by(ProjectEnvironmentVariable.id.asc())
        ).all())
        return ResolvedScenarioSource(
            project_id=project_id,
            environment_id=environment_id,
            case_snapshot_id=(str(case_snapshot.get("snapshot_id")) if case_snapshot.get("snapshot_id") else None),
            http_case_ids=http_ids,
            websocket_case_ids=websocket_ids,
            case_snapshots=tuple(snapshots),
            evidence_sources=({
                "artifact_id": artifact_id,
                "tool_call_id": call.tool_call_id,
                "run_id": call.run_id,
                "tool_name": call.tool_name,
                "output_hash": call.output_hash,
                "redaction": "output_json_redacted",
                "case_snapshot_id": case_snapshot.get("snapshot_id"),
            },),
            environment_variable_names=environment_variable_names,
        )

    def _require_environment_compatible(
        self,
        case: TestCase | WebSocketTestCase,
        *,
        environment_id: int,
        case_type: str,
    ) -> None:
        environment_ids = set(case.environment_ids)
        if environment_ids and environment_id not in environment_ids:
            self._invalid(
                "case_environment_mismatch",
                case_type=case_type,
                case_id=case.id,
                environment_id=environment_id,
            )

    @staticmethod
    def _invalid(reason: str, **details: Any) -> None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "agent_scenario_case_source_invalid",
                "reason": reason,
                **details,
            },
        )


def _parse_case_source_artifact_id(artifact_id: str) -> dict[str, str] | None:
    prefix = "agent-tool-artifact://"
    if not artifact_id.startswith(prefix):
        return None
    remainder = artifact_id[len(prefix):]
    tool_call_id, separator, artifact_type = remainder.rpartition("/")
    if not separator or not tool_call_id or artifact_type != TEST_CASE_QUERY_ARTIFACT_TYPE:
        return None
    return {"tool_call_id": tool_call_id, "artifact_type": artifact_type}


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    items: list[int] = []
    for raw in value:
        parsed = _optional_int(raw)
        if parsed is not None and parsed > 0 and parsed not in items:
            items.append(parsed)
    return tuple(items)


def _object_refs_by_identity(output: dict[str, Any]) -> dict[tuple[str, int], str]:
    manifest = output.get("object_reference_manifest")
    rows = manifest.get("object_references") if isinstance(manifest, dict) else []
    result: dict[tuple[str, int], str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        case_id = _optional_int(row.get("id"))
        object_ref = row.get("object_ref")
        object_type = str(row.get("object_type") or "")
        if case_id is None or not isinstance(object_ref, str):
            continue
        case_type = "websocket" if object_type == "websocket_test_case" else "http"
        result[(case_type, case_id)] = object_ref
    return result
