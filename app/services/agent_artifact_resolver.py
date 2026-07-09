from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ARTIFACT_CLASS_AUTHORITATIVE = "AUTHORITATIVE"
ARTIFACT_CLASS_DERIVED = "DERIVED"
ARTIFACT_CLASS_SUMMARY = "SUMMARY"
ARTIFACT_TRUST_SOURCE = "SOURCE"
ARTIFACT_TRUST_DERIVED = "DERIVED"
ARTIFACT_TRUST_SUMMARY = "SUMMARY"

ARTIFACT_TRUST_LEVELS = frozenset({
    ARTIFACT_TRUST_SOURCE,
    ARTIFACT_TRUST_DERIVED,
    ARTIFACT_TRUST_SUMMARY,
})

AUTHORITATIVE_ARTIFACT_TYPES = frozenset({
    "scenario_draft",
    "saved_scenario",
    "scenario_run_failure",
    "test_case_query_snapshot",
})
DERIVED_ARTIFACT_TYPES = frozenset({
    "testcase_assertion_draft",
    "testcase_extractor_draft",
    "testcase_draft",
})

ARTIFACT_HANDLE_FIELDS = (
    "artifact_id",
    "artifact_type",
    "artifact_class",
    "artifact_trust",
    "domain",
    "tool_name",
    "available_followup_actions",
    "output_hash",
    "artifact_summary",
)


@dataclass(frozen=True)
class ArtifactAvailability:
    artifact_id: str
    artifact_type: str
    artifact_class: str
    artifact_trust: str
    domain: str
    tool_name: str | None = None
    available_followup_actions: tuple[str, ...] = ()
    output_hash: str | None = None
    artifact_summary: dict[str, Any] | None = None

    @property
    def is_authoritative(self) -> bool:
        return self.artifact_class == ARTIFACT_CLASS_AUTHORITATIVE

    @property
    def is_source_trusted(self) -> bool:
        return self.artifact_trust == ARTIFACT_TRUST_SOURCE

    @property
    def is_decision_source(self) -> bool:
        return self.is_source_trusted

    def model_handle(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "artifact_class": self.artifact_class,
            "artifact_trust": self.artifact_trust,
            "domain": self.domain,
        }
        if self.tool_name:
            payload["tool_name"] = self.tool_name
        if self.available_followup_actions:
            payload["available_followup_actions"] = list(self.available_followup_actions)
        if self.output_hash:
            payload["output_hash"] = self.output_hash
        if self.artifact_summary:
            payload["artifact_summary"] = self.artifact_summary
        return payload


class AgentArtifactResolver:
    """Classifies ledger/UI artifacts and projects model-safe artifact handles."""

    def artifact_class_for_type(self, artifact_type: str | None) -> str:
        if artifact_type in AUTHORITATIVE_ARTIFACT_TYPES:
            return ARTIFACT_CLASS_AUTHORITATIVE
        if artifact_type in DERIVED_ARTIFACT_TYPES:
            return ARTIFACT_CLASS_DERIVED
        return ARTIFACT_CLASS_SUMMARY

    def artifact_trust_for_item(self, item: dict[str, Any], *, artifact_class: str | None = None) -> str:
        explicit = item.get("artifact_trust")
        if explicit in ARTIFACT_TRUST_LEVELS:
            return str(explicit)
        if item.get("source") == "tool_call_ledger" or item.get("tool_call_id"):
            return ARTIFACT_TRUST_SOURCE
        resolved_class = artifact_class or item.get("artifact_class")
        if resolved_class == ARTIFACT_CLASS_SUMMARY or item.get("source_run_id"):
            return ARTIFACT_TRUST_SUMMARY
        if resolved_class == ARTIFACT_CLASS_DERIVED:
            return ARTIFACT_TRUST_DERIVED
        if resolved_class == ARTIFACT_CLASS_AUTHORITATIVE:
            return ARTIFACT_TRUST_SOURCE
        return ARTIFACT_TRUST_SUMMARY

    def ensure_artifact_class(self, item: dict[str, Any]) -> dict[str, Any]:
        artifact_type = str(item.get("artifact_type") or "")
        artifact_class = item.get("artifact_class")
        if artifact_class not in {
            ARTIFACT_CLASS_AUTHORITATIVE,
            ARTIFACT_CLASS_DERIVED,
            ARTIFACT_CLASS_SUMMARY,
        }:
            artifact_class = self.artifact_class_for_type(artifact_type)
        artifact_trust = self.artifact_trust_for_item(item, artifact_class=str(artifact_class))
        return {**item, "artifact_class": artifact_class, "artifact_trust": artifact_trust}

    def availability_from_item(self, item: dict[str, Any]) -> ArtifactAvailability | None:
        classified = self.ensure_artifact_class(item)
        artifact_id = str(classified.get("artifact_id") or "")
        artifact_type = str(classified.get("artifact_type") or "")
        if not artifact_id or not artifact_type:
            return None
        actions = classified.get("available_followup_actions")
        return ArtifactAvailability(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            artifact_class=str(classified.get("artifact_class") or ARTIFACT_CLASS_SUMMARY),
            artifact_trust=str(classified.get("artifact_trust") or ARTIFACT_TRUST_SUMMARY),
            domain=str(classified.get("domain") or artifact_type.split("_", 1)[0] or "artifact"),
            tool_name=str(classified.get("tool_name") or "") or None,
            available_followup_actions=tuple(str(action) for action in actions) if isinstance(actions, list) else (),
            output_hash=str(classified.get("output_hash") or "") or None,
            artifact_summary=classified.get("artifact_summary") if isinstance(classified.get("artifact_summary"), dict) else None,
        )

    def authoritative_availabilities(self, items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[ArtifactAvailability, ...]:
        availabilities = []
        for item in items:
            availability = self.availability_from_item(item)
            if availability is not None and availability.is_authoritative and availability.is_decision_source:
                availabilities.append(availability)
        return tuple(availabilities)

    def model_handles(self, items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        handles: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            availability = self.availability_from_item(item)
            if availability is None or not availability.is_decision_source:
                continue
            if availability.artifact_id in seen:
                continue
            seen.add(availability.artifact_id)
            handles.append(availability.model_handle())
        return handles


def artifact_model_handle(item: dict[str, Any]) -> dict[str, Any] | None:
    availability = AgentArtifactResolver().availability_from_item(item)
    if availability is None or not availability.is_decision_source:
        return None
    return availability.model_handle()
