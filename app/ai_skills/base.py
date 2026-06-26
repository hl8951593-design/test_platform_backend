import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.schemas.ai import AIChatMessage, AIChatRequest
from app.services.ai_run_event_service import AIRunTrace
from app.services.ai_service import AIService


logger = logging.getLogger(__name__)


def load_model_json(raw_content: str, *, allow_list: bool = False) -> dict[str, Any] | list[Any]:
    text = _clean_model_json_text(raw_content)
    if not text:
        raise ValueError("empty content")

    candidates = [text]
    extracted = _extract_json_candidate(text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    for candidate in list(candidates):
        repaired = _repair_json_candidate(candidate)
        if repaired not in candidates:
            candidates.append(repaired)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            data = _normalize_json_object_keys(data)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
    else:
        raise ValueError(str(last_error or "invalid JSON")) from None

    if isinstance(data, list):
        if allow_list:
            return data
        raise ValueError("root is not object")
    if not isinstance(data, dict):
        raise ValueError("root is not object")
    return data


def _clean_model_json_text(raw_content: str) -> str:
    text = (raw_content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_candidate(text: str) -> str | None:
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        return None
    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    end = text.rfind(closing)
    return text[start : end + 1] if end > start else None


def _repair_json_candidate(text: str) -> str:
    text = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = _repair_control_characters_in_strings(text)
    return _escape_unescaped_inner_quotes(text)


def _repair_control_characters_in_strings(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if not in_string:
            result.append(char)
            if char == '"':
                in_string = True
            continue

        if escape:
            result.append(char)
            escape = False
            continue
        if char == "\\":
            result.append(char)
            escape = True
            continue
        if char == '"':
            result.append(char)
            in_string = False
            continue
        if ord(char) < 0x20:
            if char == "\n":
                next_index = _next_non_space_index(text, index + 1)
                next_non_space = text[next_index] if next_index is not None else ""
                after_next = (
                    _next_non_space(text, next_index + 1)
                    if next_index is not None
                    else ""
                )
                if next_non_space in {",", "}", "]"}:
                    result.append('"\n')
                    in_string = False
                    continue
                if next_non_space == '"' and after_next in {":", ",", "}", "]"}:
                    continue
                result.append("\\n")
                continue
            if char == "\t":
                result.append("\\t")
                continue
            if char == "\b":
                result.append("\\b")
                continue
            if char == "\f":
                result.append("\\f")
                continue
            result.append(f"\\u{ord(char):04x}")
            continue
        result.append(char)
    return "".join(result)


def _escape_unescaped_inner_quotes(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if not in_string:
            result.append(char)
            if char == '"':
                in_string = True
            continue

        if escape:
            result.append(char)
            escape = False
            continue
        if char == "\\":
            result.append(char)
            escape = True
            continue
        if char == '"':
            next_non_space = _next_non_space(text, index + 1)
            if next_non_space in {":", ",", "}", "]", ""}:
                result.append(char)
                in_string = False
            else:
                result.append('\\"')
            continue
        result.append(char)
    return "".join(result)


def _next_non_space(text: str, start: int) -> str:
    index = _next_non_space_index(text, start)
    return text[index] if index is not None else ""


def _next_non_space_index(text: str, start: int) -> int | None:
    for index in range(start, len(text)):
        if not text[index].isspace():
            return index
    return None


def _normalize_json_object_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _normalize_json_key(key): _normalize_json_object_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_json_object_keys(item) for item in value]
    return value


def _normalize_json_key(key: Any) -> Any:
    if not isinstance(key, str):
        return key
    return re.sub(r"[\x00-\x1f]+", "", key).strip()


def _preview(value: str, limit: int = 2000) -> str:
    text = (value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text[:limit]


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    version: str = "1.0.0"


@dataclass(frozen=True)
class SkillPackageInfo:
    metadata: SkillMetadata
    domain: str
    protocol: str
    operations: list[dict[str, Any]]
    resources: dict[str, str]


class SkillPackage:
    def __init__(self, package_dir: Path):
        self.package_dir = package_dir
        self.manifest = self._load_manifest()
        self.metadata = self._load_metadata()

    def read_text(self, relative_path: str) -> str:
        path = (self.package_dir / relative_path).resolve()
        if not path.is_relative_to(self.package_dir.resolve()):
            raise ValueError("skill resource path escapes package directory")
        return path.read_text(encoding="utf-8").strip()

    def _load_metadata(self) -> SkillMetadata:
        skill_md = self.package_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        frontmatter = self._extract_frontmatter(text)
        return SkillMetadata(
            name=frontmatter.get("name") or self.package_dir.name,
            description=frontmatter.get("description") or "",
            version=str(self.manifest.get("version") or "1.0.0"),
        )

    def _load_manifest(self) -> dict[str, Any]:
        manifest_path = self.package_dir / "manifest.json"
        if not manifest_path.exists():
            return {
                "version": "1.0.0",
                "domain": "",
                "protocol": "",
                "operations": [],
                "resources": {},
            }
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"skill manifest must be an object: {manifest_path}")
        return data

    def _extract_frontmatter(self, text: str) -> dict[str, str]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        result: dict[str, str] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, separator, value = line.partition(":")
            if separator:
                result[key.strip()] = value.strip().strip('"').strip("'")
        return result

    def info(self) -> SkillPackageInfo:
        operations = self.manifest.get("operations")
        resources = self.manifest.get("resources")
        return SkillPackageInfo(
            metadata=self.metadata,
            domain=str(self.manifest.get("domain") or ""),
            protocol=str(self.manifest.get("protocol") or ""),
            operations=operations if isinstance(operations, list) else [],
            resources=resources if isinstance(resources, dict) else {},
        )


class AISkill(ABC):
    skill_id: str
    name: str
    description: str
    package: SkillPackage

    @abstractmethod
    def build_chat_request(self, context: dict[str, Any]) -> AIChatRequest:
        """Build the model request from a validated business context."""

    @abstractmethod
    def parse_response(self, raw_content: str, context: dict[str, Any]) -> Any:
        """Parse and validate model output for this skill."""


class AISkillRunner:
    def __init__(self, ai_service: AIService | None = None):
        self.ai_service = ai_service or AIService()

    def run(self, skill: AISkill, context: dict[str, Any]) -> Any:
        response = self.ai_service.chat(skill.build_chat_request(context))
        return self._parse_response_with_json_repair(skill, response.content, context)

    def run_traced(self, skill: AISkill, context: dict[str, Any], trace: AIRunTrace) -> Any:
        chat_request = skill.build_chat_request(context)
        trace.model_started(chat_request.model)
        raw_content = ""
        finish_reason = None
        usage = None
        model = chat_request.model
        if hasattr(self.ai_service, "chat_stream"):
            for event in self.ai_service.chat_stream(chat_request):
                if event.get("type") == "delta":
                    content = str(event.get("content") or "")
                    raw_content += content
                    trace.model_delta(content)
                elif event.get("type") == "done":
                    finish_reason = event.get("finish_reason")
                    usage = event.get("usage")
                    model = event.get("model") or model
        else:
            response = self.ai_service.chat(chat_request)
            raw_content = response.content
            finish_reason = getattr(response, "finish_reason", None)
            usage = getattr(response, "usage", None)
            model = getattr(response, "model", model)
            trace.model_delta(raw_content)
        trace.model_completed(model=model, finish_reason=finish_reason, usage=usage)
        trace.step_started("校验 AI 返回结构")
        result = self._parse_response_with_json_repair(
            skill,
            raw_content,
            context,
            trace=trace,
        )
        trace.step_completed("校验 AI 返回结构")
        return result

    def _parse_response_with_json_repair(
        self,
        skill: AISkill,
        raw_content: str,
        context: dict[str, Any],
        *,
        trace: AIRunTrace | None = None,
    ) -> Any:
        try:
            return skill.parse_response(raw_content, context)
        except HTTPException as exc:
            if not self._is_invalid_json_error(exc):
                raise
            logger.warning(
                "AI skill returned invalid JSON; attempting model repair skill_id=%s error=%s raw_preview=%s",
                getattr(skill, "skill_id", "-"),
                exc.detail,
                _preview(raw_content),
            )
            repaired = self._repair_json_content(raw_content, str(exc.detail), trace=trace)
            try:
                return skill.parse_response(repaired, context)
            except HTTPException:
                logger.exception(
                    "AI skill JSON repair failed skill_id=%s repaired_preview=%s",
                    getattr(skill, "skill_id", "-"),
                    _preview(repaired),
                )
                raise

    def _repair_json_content(
        self,
        raw_content: str,
        error_message: str,
        *,
        trace: AIRunTrace | None = None,
    ) -> str:
        request = AIChatRequest(
            messages=[
                AIChatMessage(
                    role="system",
                    content=(
                        "你是严格的 JSON 修复器。只输出修复后的合法 JSON，不要 Markdown，"
                        "不要解释，不要新增业务内容。保留原始字段、数组顺序和语义；"
                        "只修复引号、逗号、转义、代码块或多余说明文字等格式问题。"
                    ),
                ),
                AIChatMessage(
                    role="user",
                    content=(
                        "下面的内容需要修复为合法 JSON。\n"
                        f"解析错误：{error_message}\n"
                        "原始内容：\n"
                        f"{raw_content}"
                    ),
                ),
            ],
            thinking="disabled",
            temperature=0,
            max_tokens=7000,
            response_format="json",
        )
        if trace is not None:
            trace.step_started("修复 AI JSON 输出")
        response = self.ai_service.chat(request)
        if trace is not None:
            trace.step_completed("修复 AI JSON 输出")
        return response.content

    @staticmethod
    def _is_invalid_json_error(exc: HTTPException) -> bool:
        detail = str(exc.detail)
        return (
            exc.status_code == 502
            and "JSON" in detail
            and "结构校验" not in detail
            and "缁撴瀯鏍￠獙" not in detail
        )
