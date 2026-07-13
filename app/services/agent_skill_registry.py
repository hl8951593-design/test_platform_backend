from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


AGENT_SKILL_ROOT = Path(__file__).resolve().parents[1] / "agent_skills"
AGENT_SKILL_PROMPT_BLOCK_MAX_CHARS = 4000
AGENT_SKILL_PROMPT_TRUNCATION_MARKER = (
    "\n\n[agent_skill_prompt_truncated: full SKILL.md body is not injected into model context]"
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n?", re.S)
PHRASE_KEY_SEPARATOR_RE = re.compile(r"[\s,，.。:：;；、/\\\-_\[\]【】()（）\"'`]+")
CJK_OPERATION_TERMS = (
    "批量执行",
    "生成",
    "创建",
    "组合",
    "保存",
    "执行",
    "运行",
    "查询",
    "读取",
    "获取",
    "拉取",
    "查看",
    "修复",
    "校验",
    "验证",
    "扩写",
    "导出",
    "归档",
    "导入",
    "更新",
    "删除",
    "复制",
    "重命名",
    "分析",
    "诊断",
    "总结",
)
EXPLANATORY_INTENT_CUES = (
    "是什么",
    "什么是",
    "有啥区别",
    "有什么区别",
    "区别是什么",
    "设计原则",
    "基本原则",
    "概念",
    "原理",
    "理论",
    "如何理解",
    "解释",
    "说明一下",
    "介绍一下",
    "讲解",
)
OPERATIONAL_CONTEXT_CUES = (
    "完成",
    "基于",
    "按照",
    "根据",
    "把",
    "给我",
    "为我",
    "直接",
    "先",
    "继续",
    "重新",
    "当前",
    "最近",
    "已有",
    "真实",
    "实际",
    "项目",
    "read",
    "show",
    "list",
    "get",
    "fetch",
    "create",
    "run",
    "execute",
    "query",
    "summarize",
    "analyze",
    "fix",
    "repair",
    "validate",
    "export",
)
WEAK_OPERATION_PHRASE_TERMS = (
    "\u6279\u91cf\u6267\u884c",
    "\u751f\u6210",
    "\u521b\u5efa",
    "\u7ec4\u5408",
    "\u4fdd\u5b58",
    "\u6267\u884c",
    "\u8fd0\u884c",
    "\u67e5\u8be2",
    "\u8bfb\u53d6",
    "\u83b7\u53d6",
    "\u62c9\u53d6",
    "\u67e5\u770b",
    "\u4fee\u590d",
    "\u6821\u9a8c",
    "\u9a8c\u8bc1",
    "\u6269\u5199",
    "\u5bfc\u51fa",
    "\u5f52\u6863",
    "\u5bfc\u5165",
    "\u66f4\u65b0",
    "\u5220\u9664",
    "\u590d\u5236",
    "\u91cd\u547d\u540d",
    "\u5206\u6790",
    "\u8bca\u65ad",
    "\u603b\u7ed3",
    "save",
    "generate",
    "create",
    "compose",
    "run",
    "execute",
    "query",
    "read",
    "get",
    "fetch",
    "list",
    "view",
    "show",
    "fix",
    "repair",
    "validate",
    "verify",
    "export",
    "archive",
    "import",
    "update",
    "delete",
    "copy",
    "rename",
    "analyze",
    "diagnose",
    "summarize",
)


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    triggers: tuple[str, ...]
    capabilities: tuple[str, ...]
    required_context: tuple[str, ...]
    tool_names: tuple[str, ...]
    artifact_types: tuple[str, ...]
    dependencies: tuple[str, ...]
    examples: tuple[str, ...]
    owns: tuple[str, ...]
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    routing_hints: dict[str, tuple[str, ...]]
    private_values: dict[str, str]
    body: str
    path: Path

    def metadata(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
        }

    def planner_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "required_context": list(self.required_context),
            "tool_names": list(self.tool_names),
            "artifact_types": list(self.artifact_types),
            "dependencies": list(self.dependencies),
            "examples": list(self.examples),
            "owns": list(self.owns),
            "consumes": list(self.consumes),
            "produces": list(self.produces),
        }

    def snapshot_manifest(self) -> dict[str, Any]:
        """Return the immutable Skill contract and prompt used by one runtime snapshot."""
        return {
            **self.planner_metadata(),
            "triggers": list(self.triggers),
            "routing_hints": {key: list(values) for key, values in self.routing_hints.items()},
            "private_values": dict(self.private_values),
            "body": self.body,
            "path": str(self.path),
        }

    def prompt_block(self) -> str:
        block = (
            f"Agent Skill: {self.name}\n"
            f"Description: {self.description}\n\n"
            f"{self.body.strip()}"
        )
        return _cap_prompt_block(block)


@dataclass(frozen=True)
class AgentSkillRoute:
    primary_skill: AgentSkill | None
    supporting_skills: tuple[AgentSkill, ...]
    confidence: float
    score: int
    runner_mode: str

    @property
    def selected_skills(self) -> tuple[AgentSkill, ...]:
        if self.primary_skill is None:
            return ()
        return (self.primary_skill, *self.supporting_skills)

    @property
    def selected_skill_names(self) -> tuple[str, ...]:
        return tuple(skill.name for skill in self.selected_skills)

    def model_view(self) -> dict[str, Any]:
        return {
            "primary_skill": self.primary_skill.name if self.primary_skill else None,
            "supporting_skills": [skill.name for skill in self.supporting_skills],
            "selected_skill_names": list(self.selected_skill_names),
            "confidence": self.confidence,
            "score": self.score,
            "runner_mode": self.runner_mode,
        }


class AgentSkillRegistry:
    """Codex-style progressive-disclosure registry for TestAuto Agent skills."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or AGENT_SKILL_ROOT
        self._skills = _load_agent_skills(self.root)

    @classmethod
    def from_snapshot_manifests(cls, manifests: dict[str, Any]) -> "AgentSkillRegistry":
        """Rebuild a registry from a persisted RuntimeSnapshot without reading live files."""
        registry = cls.__new__(cls)
        registry.root = AGENT_SKILL_ROOT
        registry._skills = {}
        for name, raw in sorted((manifests or {}).items()):
            if not isinstance(raw, dict) or str(raw.get("name") or name) != str(name):
                continue
            registry._skills[str(name)] = AgentSkill(
                name=str(name),
                description=str(raw.get("description") or ""),
                triggers=tuple(str(item) for item in raw.get("triggers") or ()),
                capabilities=tuple(str(item) for item in raw.get("capabilities") or ()),
                required_context=tuple(str(item) for item in raw.get("required_context") or ()),
                tool_names=tuple(str(item) for item in raw.get("tool_names") or ()),
                artifact_types=tuple(str(item) for item in raw.get("artifact_types") or ()),
                dependencies=tuple(str(item) for item in raw.get("dependencies") or ()),
                examples=tuple(str(item) for item in raw.get("examples") or ()),
                owns=tuple(str(item) for item in raw.get("owns") or ()),
                consumes=tuple(str(item) for item in raw.get("consumes") or ()),
                produces=tuple(str(item) for item in raw.get("produces") or ()),
                routing_hints={
                    str(key): tuple(str(item) for item in values or ())
                    for key, values in (raw.get("routing_hints") or {}).items()
                },
                private_values={
                    str(key): str(value)
                    for key, value in (raw.get("private_values") or {}).items()
                },
                body=str(raw.get("body") or ""),
                path=Path(str(raw.get("path") or (AGENT_SKILL_ROOT / str(name) / "SKILL.md"))),
            )
        return registry

    def list_skills(self) -> list[AgentSkill]:
        return [self._skills[name] for name in sorted(self._skills)]

    def catalog(self) -> list[dict[str, str]]:
        return [skill.metadata() for skill in self.list_skills()]

    def validate_tool_declarations(
        self,
        registered_tool_names: Iterable[str],
    ) -> None:
        registered = {
            str(tool_name).strip()
            for tool_name in registered_tool_names
            if str(tool_name).strip()
        }
        unknown = {
            skill.name: sorted(set(skill.tool_names) - registered)
            for skill in self.list_skills()
            if set(skill.tool_names) - registered
        }
        if unknown:
            raise RuntimeError(
                f"Agent Skill unknown Tool declarations: {unknown}"
            )

    def private_list(self, skill_name: str, key: str) -> tuple[str, ...]:
        skill = self._skills.get(skill_name)
        if skill is None:
            return ()
        return skill.routing_hints.get(key, ())

    def private_value(self, skill_name: str, key: str) -> str | None:
        skill = self._skills.get(skill_name)
        if skill is None:
            return None
        return skill.private_values.get(key)

    def private_resource_text(self, skill_name: str, key: str) -> str | None:
        skill = self._skills.get(skill_name)
        if skill is None:
            return None
        resource_name = skill.private_values.get(key)
        if not resource_name:
            return None
        resource_path = (skill.path.parent / resource_name).resolve()
        skill_dir = skill.path.parent.resolve()
        if not resource_path.is_relative_to(skill_dir) or not resource_path.is_file():
            return None
        return resource_path.read_text(encoding="utf-8").strip()

    def select_for_intent(self, intent: str, *, limit: int = 3) -> list[AgentSkill]:
        return [skill for _, _, skill in self._scored_skills(intent)[:limit]]

    def get_skill(self, name: str) -> AgentSkill | None:
        return self._skills.get(name)

    def rank_for_intent(self, intent: str, *, limit: int | None = None) -> list[tuple[int, AgentSkill]]:
        ranked = [(score, skill) for score, _, skill in self._scored_skills(intent)]
        if limit is None:
            return ranked
        return ranked[:limit]

    def route_for_intent(self, intent: str, *, allow_supporting: bool = False) -> AgentSkillRoute:
        scored = self._scored_skills(intent)
        if not scored:
            return AgentSkillRoute(
                primary_skill=None,
                supporting_skills=(),
                confidence=0.0,
                score=0,
                runner_mode="no_skill",
            )
        top_score, _, primary = scored[0]
        supporting: tuple[AgentSkill, ...] = ()
        if allow_supporting:
            supporting = tuple(
                skill
                for score, _, skill in scored[1:3]
                if score >= max(2, top_score - 2)
            )
        return AgentSkillRoute(
            primary_skill=primary,
            supporting_skills=supporting,
            confidence=_skill_route_confidence(top_score),
            score=top_score,
            runner_mode="primary_skill_only" if not supporting else "primary_plus_supporting_skills",
        )

    def _scored_skills(self, intent: str) -> list[tuple[int, str, AgentSkill]]:
        text = _normalize_text(intent)
        scored: list[tuple[int, str, AgentSkill]] = []
        for skill in self.list_skills():
            score = _skill_score(skill, text)
            if score > 0:
                scored.append((score, skill.name, skill))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored


@lru_cache(maxsize=8)
def _load_agent_skills(root: Path) -> dict[str, AgentSkill]:
    skills: dict[str, AgentSkill] = {}
    if not root.exists():
        return skills
    for skill_file in sorted(root.glob("*/SKILL.md")):
        skill = _parse_skill_file(skill_file)
        if skill.name in skills:
            raise RuntimeError(f"Duplicate Agent skill name: {skill.name}")
        skills[skill.name] = skill
    return skills


def _parse_skill_file(path: Path) -> AgentSkill:
    content = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(content)
    if match is None:
        raise RuntimeError(f"Agent skill missing YAML frontmatter: {path}")
    frontmatter = _parse_simple_frontmatter(match.group("body"))
    name = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    if not name:
        raise RuntimeError(f"Agent skill missing name: {path}")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        raise RuntimeError(f"Agent skill name must be lowercase hyphen-case: {name}")
    if not description:
        raise RuntimeError(f"Agent skill missing description: {path}")
    body = content[match.end():].strip()
    if not body:
        raise RuntimeError(f"Agent skill body is empty: {path}")
    triggers = _coerce_frontmatter_list(frontmatter.get("triggers"))
    capabilities = _coerce_frontmatter_list(frontmatter.get("capabilities"))
    required_context = _coerce_frontmatter_list(frontmatter.get("required_context"))
    tool_names = _coerce_frontmatter_list(frontmatter.get("tools"))
    artifact_types = _coerce_frontmatter_list(frontmatter.get("artifacts"))
    dependencies = _coerce_frontmatter_list(frontmatter.get("dependencies"))
    examples = _coerce_frontmatter_list(frontmatter.get("examples"))
    owns = _coerce_frontmatter_list(frontmatter.get("owns"))
    consumes = _coerce_frontmatter_list(frontmatter.get("consumes"))
    produces = _coerce_frontmatter_list(frontmatter.get("produces"))
    routing_hints: dict[str, tuple[str, ...]] = {}
    private_values: dict[str, str] = {}
    for key, value in frontmatter.items():
        if not key.startswith(("guard_", "routing_")):
            continue
        if isinstance(value, list):
            values = _coerce_frontmatter_list(value)
            if values:
                routing_hints[key] = values
            continue
        text_value = str(value).strip()
        if text_value:
            private_values[key] = text_value
    return AgentSkill(
        name=name,
        description=description,
        triggers=triggers,
        capabilities=capabilities,
        required_context=required_context,
        tool_names=tool_names,
        artifact_types=artifact_types,
        dependencies=dependencies,
        examples=examples,
        owns=owns,
        consumes=consumes,
        produces=produces,
        routing_hints=routing_hints,
        private_values=private_values,
        body=body,
        path=path,
    )


def _parse_simple_frontmatter(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list_key and stripped.startswith("- "):
            values.setdefault(current_list_key, []).append(_unquote_frontmatter_value(stripped[2:].strip()))
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        value = _unquote_frontmatter_value(raw_value.strip())
        if value == "":
            values[key.strip()] = []
            current_list_key = key.strip()
            continue
        values[key.strip()] = value
    return values


def _unquote_frontmatter_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _coerce_frontmatter_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    return tuple(str(item).strip() for item in items if str(item).strip())


def _skill_score(skill: AgentSkill, normalized_intent: str) -> int:
    haystack = _normalize_text(f"{skill.name} {skill.description}")
    if not normalized_intent:
        return 0
    score = 0
    for token in _intent_tokens(normalized_intent):
        if token in haystack:
            score += 1
    for phrase in skill.triggers:
        if intent_matches_phrase(normalized_intent, phrase):
            score += 1 if _is_weak_operation_phrase(phrase) else 3
    for key, values in skill.routing_hints.items():
        if key.startswith("guard_"):
            continue
        for phrase in values:
            if intent_matches_routing_phrase(normalized_intent, phrase):
                score += 0 if _is_weak_operation_phrase(phrase) else 2
    return score


def _skill_route_confidence(score: int) -> float:
    if score <= 0:
        return 0.0
    return round(min(0.99, score / (score + 3)), 4)


def _intent_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_./-]+|[\u4e00-\u9fff]{2,}", text)
    stopwords = {
        "请",
        "帮我",
        "一下",
        "当前",
        "这个",
        "那个",
        "需要",
        "不要",
        "如何",
        "什么",
        "说明",
    }
    return [token for token in tokens if token not in stopwords]


def _normalize_text(text: str) -> str:
    return (text or "").casefold()


def intent_matches_phrase(intent: str, phrase: str) -> bool:
    intent_key = _phrase_key(intent)
    phrase_key = _phrase_key(phrase)
    if not intent_key or not phrase_key or phrase_key == "--":
        return False
    if phrase_key in intent_key:
        return True
    return any(variant in intent_key for variant in _phrase_order_variants(phrase_key))


def intent_matches_routing_phrase(intent: str, phrase: str) -> bool:
    if not intent_matches_phrase(intent, phrase):
        return False
    intent_key = _phrase_key(intent)
    if _looks_like_explanatory_only_intent(intent_key):
        return False
    return True


def _phrase_key(text: str) -> str:
    return PHRASE_KEY_SEPARATOR_RE.sub("", _normalize_text(text))


def _is_weak_operation_phrase(phrase: str) -> bool:
    return _phrase_key(phrase) in _weak_operation_phrase_keys()


@lru_cache(maxsize=1)
def _weak_operation_phrase_keys() -> frozenset[str]:
    return frozenset(_phrase_key(term) for term in WEAK_OPERATION_PHRASE_TERMS)


def _phrase_order_variants(phrase_key: str) -> tuple[str, ...]:
    variants: set[str] = set()
    for term in CJK_OPERATION_TERMS:
        term_key = _phrase_key(term)
        if phrase_key.startswith(term_key):
            rest = phrase_key[len(term_key):]
            if len(rest) >= 2:
                variants.add(f"{rest}{term_key}")
        if phrase_key.endswith(term_key):
            rest = phrase_key[:-len(term_key)]
            if len(rest) >= 2:
                variants.add(f"{term_key}{rest}")
    return tuple(sorted(variants))


def _looks_like_explanatory_only_intent(intent_key: str) -> bool:
    if not any(_phrase_key(cue) in intent_key for cue in EXPLANATORY_INTENT_CUES):
        return False
    return not any(_phrase_key(cue) in intent_key for cue in OPERATIONAL_CONTEXT_CUES)


def _cap_prompt_block(block: str) -> str:
    if len(block) <= AGENT_SKILL_PROMPT_BLOCK_MAX_CHARS:
        return block
    marker = AGENT_SKILL_PROMPT_TRUNCATION_MARKER
    prefix_length = max(0, AGENT_SKILL_PROMPT_BLOCK_MAX_CHARS - len(marker))
    return f"{block[:prefix_length]}{marker}"
