from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


AGENT_SKILL_ROOT = Path(__file__).resolve().parents[1] / "agent_skills"
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n?", re.S)


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    triggers: tuple[str, ...]
    routing_hints: dict[str, tuple[str, ...]]
    private_values: dict[str, str]
    body: str
    path: Path

    def metadata(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
        }

    def prompt_block(self) -> str:
        return (
            f"Agent Skill: {self.name}\n"
            f"Description: {self.description}\n\n"
            f"{self.body.strip()}"
        )


class AgentSkillRegistry:
    """Codex-style progressive-disclosure registry for TestAuto Agent skills."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or AGENT_SKILL_ROOT
        self._skills = _load_agent_skills(self.root)

    def list_skills(self) -> list[AgentSkill]:
        return [self._skills[name] for name in sorted(self._skills)]

    def catalog(self) -> list[dict[str, str]]:
        return [skill.metadata() for skill in self.list_skills()]

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
        text = _normalize_text(intent)
        scored: list[tuple[int, str, AgentSkill]] = []
        for skill in self.list_skills():
            score = _skill_score(skill, text)
            if score > 0:
                scored.append((score, skill.name, skill))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [skill for _, _, skill in scored[:limit]]


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
        if _normalize_text(phrase) in normalized_intent:
            score += 3
    return score


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
