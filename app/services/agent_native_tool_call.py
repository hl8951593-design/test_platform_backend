from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.schemas.ai import AIChatFunctionDefinition, AIChatToolDefinition


RUNTIME_REQUEST_CAPABILITY_ALIAS = "runtime_request_capability"
NATIVE_ARGUMENT_JSON_REPAIR_MAX_CLOSERS = 8


class NativeToolCallError(ValueError):
    pass


@dataclass(frozen=True)
class NativeToolRequest:
    tool_name: str
    tool_input: dict[str, Any]
    reason: str | None = None
    evidence_refs: tuple[dict[str, Any], ...] = ()
    provider_tool_call_id: str | None = None


@dataclass(frozen=True)
class NativeCapabilityRequest:
    tool_names: tuple[str, ...]
    reason: str
    provider_tool_call_id: str | None = None


class NativeToolCallAccumulator:
    def __init__(self, *, tool_aliases: dict[str, str]) -> None:
        self.tool_aliases = dict(tool_aliases)
        self._index: int | None = None
        self._tool_call_id: str | None = None
        self._name_parts: list[str] = []
        self._argument_parts: list[str] = []

    @property
    def has_data(self) -> bool:
        return self._index is not None

    def feed(self, delta: dict[str, Any]) -> None:
        index = delta.get("index")
        if not isinstance(index, int):
            raise NativeToolCallError("native tool call delta is missing an integer index")
        if self._index is None:
            self._index = index
        elif index != self._index:
            raise NativeToolCallError("parallel native tool calls are not supported")
        tool_call_id = delta.get("id")
        if tool_call_id:
            if self._tool_call_id is not None and self._tool_call_id != tool_call_id:
                raise NativeToolCallError("native tool call id changed during streaming")
            self._tool_call_id = str(tool_call_id)
        function = delta.get("function")
        if not isinstance(function, dict):
            raise NativeToolCallError("native tool call delta is missing function data")
        name = function.get("name")
        if name:
            self._name_parts.append(str(name))
        arguments = function.get("arguments")
        if arguments:
            self._argument_parts.append(str(arguments))

    def finalize(self) -> NativeToolRequest | NativeCapabilityRequest:
        alias = "".join(self._name_parts)
        canonical_name = self.tool_aliases.get(alias)
        if canonical_name is None and alias != RUNTIME_REQUEST_CAPABILITY_ALIAS:
            raise NativeToolCallError("native tool call used an unknown provider alias")
        raw_arguments = "".join(self._argument_parts)
        payload = _load_native_argument_payload(raw_arguments)
        if alias == RUNTIME_REQUEST_CAPABILITY_ALIAS:
            if not isinstance(payload, dict):
                raise NativeToolCallError("capability request arguments must be an object")
            raw_tool_names = payload.get("tool_names")
            if (
                not isinstance(raw_tool_names, list)
                or not raw_tool_names
                or not all(isinstance(item, str) and item.strip() for item in raw_tool_names)
            ):
                raise NativeToolCallError("capability request tool_names must be a non-empty string array")
            reason = payload.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise NativeToolCallError("capability request reason must be a non-empty string")
            return NativeCapabilityRequest(
                tool_names=tuple(dict.fromkeys(item.strip() for item in raw_tool_names)),
                reason=reason.strip(),
                provider_tool_call_id=self._tool_call_id,
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("input"), dict):
            raise NativeToolCallError("native tool call arguments require an input object")
        evidence_refs = payload.get("evidence_refs") or []
        if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
            raise NativeToolCallError("native tool call evidence_refs must be an array of objects")
        reason = payload.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise NativeToolCallError("native tool call reason must be a string")
        return NativeToolRequest(
            tool_name=canonical_name,
            tool_input=dict(payload["input"]),
            reason=reason,
            evidence_refs=tuple(dict(item) for item in evidence_refs),
            provider_tool_call_id=self._tool_call_id,
        )


def build_native_tool_definitions(
    *,
    allowed_tools: list[str],
    tool_aliases: dict[str, str],
    runtime_tools: list[dict[str, Any]],
) -> list[AIChatToolDefinition]:
    specs = {
        str(item.get("name") or ""): item
        for item in runtime_tools
        if isinstance(item, dict) and item.get("name")
    }
    canonical_to_alias = {canonical: alias for alias, canonical in tool_aliases.items()}
    definitions: list[AIChatToolDefinition] = [
        AIChatToolDefinition(
            function=AIChatFunctionDefinition(
                name=RUNTIME_REQUEST_CAPABILITY_ALIAS,
                description=(
                    "Request activation of registered Tools for the current goal. "
                    "This revises the Capability Plan but never executes a business Tool."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "tool_names": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
                    },
                    "required": ["tool_names", "reason"],
                    "additionalProperties": False,
                },
            )
        )
    ]
    for tool_name in allowed_tools:
        spec = specs.get(tool_name)
        alias = canonical_to_alias.get(tool_name)
        if spec is None or alias is None:
            continue
        input_schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {}
        definitions.append(AIChatToolDefinition(
            function=AIChatFunctionDefinition(
                name=alias,
                description=str(spec.get("summary") or tool_name)[:1024],
                parameters={
                    "type": "object",
                    "properties": {
                        "input": input_schema,
                        "reason": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                    "required": ["input"],
                    "additionalProperties": False,
                },
            )
        ))
    return definitions


def _load_native_argument_payload(raw_arguments: str) -> Any:
    candidates = [raw_arguments]
    completed = _complete_missing_native_argument_closers(raw_arguments)
    if completed is not None and completed != raw_arguments:
        candidates.append(completed)
    last_error: Exception | None = None
    for candidate in candidates:
        for strict in (True, False):
            try:
                return json.loads(candidate, strict=strict)
            except (TypeError, ValueError) as exc:
                last_error = exc
    raise NativeToolCallError("native tool call arguments are not valid JSON") from last_error


def _complete_missing_native_argument_closers(raw: str) -> str | None:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char == "}":
            if not stack or stack[-1] != "{":
                return None
            stack.pop()
        elif char == "]":
            if not stack or stack[-1] != "[":
                return None
            stack.pop()
    if in_string or escaped or len(stack) > NATIVE_ARGUMENT_JSON_REPAIR_MAX_CLOSERS:
        return None
    closers = "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return f"{raw}{closers}" if closers else raw
