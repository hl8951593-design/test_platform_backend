from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.schemas.ai import AIChatMessage, AIChatRequest
from app.services.agent_intent_action import AgentIntentAction
from app.services.ai_service import AIService


AgentIntentActionName = Literal[
    "analyze",
    "query",
    "create",
    "update",
    "execute",
    "delete",
    "transition",
    "export",
]

TARGET_REQUIRED_ACTIONS = frozenset({"create", "update", "execute", "delete", "transition", "export"})


class AgentIntentDecision(BaseModel):
    action: AgentIntentActionName | None = None
    target_domain: str | None = None
    source_domains: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class ValidatedAgentIntentDecision:
    action: str | None
    target_domain: str | None
    source_domains: tuple[str, ...]
    confidence: float
    source: str
    reason_codes: tuple[str, ...] = ()
    write_authorized: bool = True

    def as_intent_action(self) -> AgentIntentAction:
        return AgentIntentAction(
            action=self.action,
            target_domain=self.target_domain,
            source_domains=self.source_domains,
            explicit=bool(self.action or self.target_domain),
            is_deictic_followup=False,
            confidence=self.confidence,
            source=self.source,
            write_authorized=self.write_authorized,
            reason_codes=self.reason_codes,
        )

    def model_view(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target_domain": self.target_domain,
            "source_domains": list(self.source_domains),
            "confidence": self.confidence,
            "source": self.source,
            "write_authorized": self.write_authorized,
            "reason_codes": list(self.reason_codes),
        }


class AgentIntentDecisionError(ValueError):
    pass


class AgentIntentDecisionService:
    def __init__(self, *, ai_service: AIService | None = None, minimum_confidence: float = 0.55) -> None:
        self.ai_service = ai_service or AIService()
        self.minimum_confidence = minimum_confidence

    def decide(
        self,
        *,
        intent: str,
        working_context: dict[str, Any] | None,
        domains: tuple[str, ...],
    ) -> ValidatedAgentIntentDecision:
        response = self.ai_service.chat(self._request(intent=intent, working_context=working_context, domains=domains))
        try:
            parsed = AgentIntentDecision.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise AgentIntentDecisionError("intent decision is not valid structured JSON") from exc
        return self._validate(parsed, domains=domains)

    def _validate(
        self,
        decision: AgentIntentDecision,
        *,
        domains: tuple[str, ...],
    ) -> ValidatedAgentIntentDecision:
        registered = set(domains)
        if decision.confidence < self.minimum_confidence:
            raise AgentIntentDecisionError("intent decision confidence is below the safe threshold")
        if decision.action in TARGET_REQUIRED_ACTIONS and decision.target_domain is None:
            raise AgentIntentDecisionError("intent decision action requires a registered target domain")
        if decision.target_domain is not None and decision.target_domain not in registered:
            raise AgentIntentDecisionError("intent decision target domain is not registered")
        sources = tuple(dict.fromkeys(decision.source_domains))
        if any(source not in registered for source in sources):
            raise AgentIntentDecisionError("intent decision source domain is not registered")
        if decision.target_domain is not None and decision.target_domain in sources:
            raise AgentIntentDecisionError("intent target domain cannot also be an evidence source")
        return ValidatedAgentIntentDecision(
            action=decision.action,
            target_domain=decision.target_domain,
            source_domains=sources,
            confidence=decision.confidence,
            source="llm_intent",
            reason_codes=("intent_decision:validated",),
            write_authorized=True,
        )

    def _request(
        self,
        *,
        intent: str,
        working_context: dict[str, Any] | None,
        domains: tuple[str, ...],
    ) -> AIChatRequest:
        compact_context = _compact_artifact_context(working_context)
        return AIChatRequest(
            messages=[
                AIChatMessage(
                    role="system",
                    content=(
                        "你是 Agent 意图规划器。只输出 JSON 对象，字段为 action、target_domain、"
                        "source_domains、confidence。target_domain 是用户要操作或创建的业务对象；"
                        "source_domains 只是证据来源。不得根据领域词注册顺序决定目标。"
                    ),
                ),
                AIChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "intent": intent,
                            "registered_domains": list(domains),
                            "supported_actions": [
                                "analyze",
                                "query",
                                "create",
                                "update",
                                "execute",
                                "delete",
                                "transition",
                                "export",
                            ],
                            "artifact_context": compact_context,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ],
            temperature=0,
            max_tokens=256,
            response_format="json",
        )


def _compact_artifact_context(working_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(working_context, dict):
        return []
    items: list[dict[str, Any]] = []
    for key in ("active_artifact_action", "active_artifact_handles", "current_artifact_candidates"):
        value = working_context.get(key)
        candidates = value if isinstance(value, list) else [value]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            compact = {
                field: item.get(field)
                for field in (
                    "artifact_id",
                    "artifact_type",
                    "artifact_class",
                    "artifact_trust",
                    "domain",
                    "action",
                    "available_followup_actions",
                )
                if item.get(field) is not None
            }
            if compact:
                items.append(compact)
            if len(items) >= 12:
                return items
    return items
