from __future__ import annotations

from typing import Any

from app.core.sensitive_data import request_fingerprint
from app.models.agent import AgentRun


AGENT_EXECUTION_PLAN_SCHEMA_VERSION = "agent_execution_plan_v1"
AGENT_EXECUTION_PLAN_ID_PREFIX = "agent-execution-plan"


def agent_execution_plan_id(
    *,
    run_id: str,
    iteration: int,
    step_index: int,
    tool_name: str,
) -> str:
    token = request_fingerprint(
        {
            "run_id": run_id,
            "iteration": iteration,
            "step_index": step_index,
            "tool_name": tool_name,
        }
    )[:16]
    return f"{AGENT_EXECUTION_PLAN_ID_PREFIX}://{run_id}/{iteration}/{step_index}/{token}"


def agent_execution_plan_payload(
    *,
    run: AgentRun,
    iteration: int,
    tool_name: str,
    tool_input: dict[str, Any],
    reason: str | None,
    evidence_refs: list[dict[str, Any]],
    plan_id: str | None = None,
) -> dict[str, Any]:
    resolved_plan_id = plan_id or agent_execution_plan_id(
        run_id=run.run_id,
        iteration=iteration,
        step_index=run.current_step_index,
        tool_name=tool_name,
    )
    return {
        "schema_version": AGENT_EXECUTION_PLAN_SCHEMA_VERSION,
        "plan_id": resolved_plan_id,
        "planner": "llm_tool_planner",
        "executor": "tool_runtime",
        "verifier": "runtime_verifier",
        "run_id": run.run_id,
        "project_id": run.project_id,
        "iteration": iteration,
        "step_index": run.current_step_index,
        "steps": [
            {
                "step_id": f"{resolved_plan_id}/step/1",
                "tool_name": tool_name,
                "input_hash": request_fingerprint(tool_input),
                "input_keys": sorted(str(key) for key in tool_input),
                "evidence_ref_count": len(evidence_refs),
                "reason": reason or "",
            }
        ],
    }
