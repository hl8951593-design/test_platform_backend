from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentBackendContract
from app.services.agent_tool_service import ToolRegistry, ToolSpec


ROLLOUT_LEVELS = {
    "L0": {
        "summary": "read-only tools",
        "allowed_side_effect_classes": {"read_only"},
        "blocked_side_effect_classes": {
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
            "business_update",
            "external_effect",
            "destructive",
        },
        "required_gates": ["Run/Event/Snapshot available"],
    },
    "L1": {
        "summary": "deterministic compute and draft-only tools",
        "allowed_side_effect_classes": {"read_only", "deterministic_compute", "draft_only"},
        "blocked_side_effect_classes": {
            "execution_record",
            "business_create",
            "business_update",
            "external_effect",
            "destructive",
        },
        "required_gates": ["Ledger/Worker available"],
    },
    "L2": {
        "summary": "execution-record tools with reconcile support",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
        },
        "blocked_side_effect_classes": {"business_create", "business_update", "external_effect", "destructive"},
        "required_gates": ["Reconcile minimum support"],
    },
    "L3": {
        "summary": "business-create tools",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
        },
        "blocked_side_effect_classes": {"business_update", "external_effect", "destructive"},
        "required_gates": ["Approval", "Reconcile", "Execute-time permission check"],
    },
    "L4": {
        "summary": "receipt-first business operations",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
            "business_update",
        },
        "blocked_side_effect_classes": {"external_effect", "destructive"},
        "required_gates": ["durable receipt", "operation-level capability"],
    },
    "L5": {
        "summary": "external-effect and destructive operations",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
            "business_update",
            "external_effect",
            "destructive",
        },
        "blocked_side_effect_classes": set(),
        "required_gates": ["strong approval", "full evidence", "rollback/manual path"],
    },
}

CURRENT_AGENT_ROLLOUT_LEVEL = "L2"
LOCKED_EXPANSION_REASONS = {
    "L3": [
        "business_create tools remain intentionally unregistered",
        "Approval UI is outside the current backend-only scope",
        "P0 fault-injection gate is not yet certified",
    ],
    "L4": [
        "receipt_first backend operations are not yet certified for business writes",
        "durable receipt contract rollout is not complete",
    ],
    "L5": [
        "external_effect/destructive tools are explicitly disabled",
        "rollback/manual path is not implemented",
    ],
}


class AgentReleaseGateService:
    def __init__(self, db: Session):
        self.db = db
        self.registry = ToolRegistry()

    def snapshot(self) -> dict[str, Any]:
        current = ROLLOUT_LEVELS[CURRENT_AGENT_ROLLOUT_LEVEL]
        tools = [self._tool_row(spec) for spec in self.registry.list_specs()]
        violations = [
            {
                "tool_name": item["tool_name"],
                "reason": "tool_side_effect_exceeds_current_rollout_level",
                "side_effect_class": item["side_effect_class"],
            }
            for item in tools
            if not item["rollout_allowed"]
        ]
        return {
            "current_level": CURRENT_AGENT_ROLLOUT_LEVEL,
            "current_level_summary": current["summary"],
            "allowed_side_effect_classes": sorted(current["allowed_side_effect_classes"]),
            "blocked_side_effect_classes": sorted(current["blocked_side_effect_classes"]),
            "tool_matrix": tools,
            "expansion_gates": self._expansion_gates(),
            "violations": violations,
        }

    def _tool_row(self, spec: ToolSpec) -> dict[str, Any]:
        contract = self._contract_for(spec)
        rollout_allowed = (
            spec.side_effect_class in ROLLOUT_LEVELS[CURRENT_AGENT_ROLLOUT_LEVEL]["allowed_side_effect_classes"]
            and (contract is None or contract.compatibility_status == "active")
        )
        return {
            "tool_name": spec.name,
            "tool_version": spec.version,
            "side_effect_class": spec.side_effect_class,
            "replay_policy": spec.replay_policy,
            "required_permissions": list(spec.required_permissions),
            "backend_name": spec.backend_contract.backend_name if spec.backend_contract else None,
            "backend_operation": spec.backend_contract.backend_operation if spec.backend_contract else None,
            "backend_contract_version": spec.backend_contract.backend_contract_version if spec.backend_contract else None,
            "backend_effect_capability": spec.backend_contract.effect_capability if spec.backend_contract else None,
            "backend_contract_status": contract.compatibility_status if contract else None,
            "rollout_allowed": rollout_allowed,
            "rollout_decision": "allowed" if rollout_allowed else "blocked",
        }

    def _contract_for(self, spec: ToolSpec) -> AgentBackendContract | None:
        if spec.backend_contract is None:
            return None
        return self.db.scalar(
            select(AgentBackendContract).where(
                AgentBackendContract.backend_name == spec.backend_contract.backend_name,
                AgentBackendContract.backend_operation == spec.backend_contract.backend_operation,
                AgentBackendContract.backend_contract_version == spec.backend_contract.backend_contract_version,
            )
        )

    def _expansion_gates(self) -> list[dict[str, Any]]:
        gates: list[dict[str, Any]] = []
        levels = list(ROLLOUT_LEVELS)
        current_index = levels.index(CURRENT_AGENT_ROLLOUT_LEVEL)
        for index, level in enumerate(levels):
            level_spec = ROLLOUT_LEVELS[level]
            unlocked = index <= current_index
            gates.append({
                "level": level,
                "summary": level_spec["summary"],
                "required_gates": list(level_spec["required_gates"]),
                "unlocked": unlocked,
                "blocked_reasons": [] if unlocked else LOCKED_EXPANSION_REASONS.get(level, ["rollout_not_enabled"]),
            })
        return gates
