import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.ai import AIChatRequest
from app.services.ai_run_event_service import AIRunTrace
from app.services.ai_service import AIService


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
        return skill.parse_response(response.content, context)

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
        result = skill.parse_response(raw_content, context)
        trace.step_completed("校验 AI 返回结构")
        return result
