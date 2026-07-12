from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentIntentAction:
    action: str | None
    target_domain: str | None
    source_domains: tuple[str, ...] = ()
    explicit: bool = False
    is_deictic_followup: bool = False
    confidence: float = 1.0
    source: str = "deterministic_fallback"
    write_authorized: bool = True
    reason_codes: tuple[str, ...] = ()


CREATE_TERMS = ("创建", "生成", "新建", "create", "generate")
TRANSFORM_CREATE_TERMS = ("转成", "转为", "转换为", "形成", "convert to", "turn into")
EXECUTE_TERMS = ("执行", "运行", "run", "execute")
UPDATE_TERMS = ("更新", "修改", "修复", "保存", "update", "fix", "save")
ANALYZE_TERMS = ("分析", "诊断", "总结", "analyze", "diagnose", "summary")
DEICTIC_TERMS = ("它", "这个", "这些", "这份", "刚才", "上面", "those", "it", "that")

DOMAIN_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("defect", ("缺陷", "bug", "Bug", "问题单", "工单")),
    ("test_plan", ("测试计划", "计划", "plan")),
    ("visual_flow", ("可视化流程", "流程", "flow")),
    ("scenario", ("场景", "scenario")),
    ("test_case", ("测试用例", "用例", "case", "接口")),
    ("execution", ("执行记录", "执行失败", "失败执行", "运行记录", "execution")),
    ("report", ("报告", "报表", "report")),
    ("media", ("截图", "附件", "图片", "media", "image")),
)


def parse_agent_intent_action(
    intent: str,
    *,
    working_context: dict[str, Any] | None = None,
) -> AgentIntentAction:
    del working_context
    lowered = (intent or "").casefold()
    reason_codes: list[str] = []
    is_deictic = any(term.casefold() in lowered for term in DEICTIC_TERMS)
    if is_deictic:
        reason_codes.append("intent:deictic_followup")

    action = _first_action(lowered, reason_codes)
    domain_spans = _mentioned_domain_spans(lowered)
    mentioned_domains = tuple(dict.fromkeys(domain for domain, _, _ in domain_spans))
    target_domain = _safe_fallback_target_domain(mentioned_domains)
    if target_domain is None and len(mentioned_domains) > 1:
        source_domains = ()
        reason_codes.append("intent:fallback_cross_domain_ambiguous")
    else:
        source_domains = tuple(domain for domain in mentioned_domains if domain != target_domain)
    explicit = bool(action or target_domain)
    if target_domain:
        reason_codes.append(f"intent:target_domain:{target_domain}")
    for domain in source_domains:
        reason_codes.append(f"intent:source_domain:{domain}")

    return AgentIntentAction(
        action=action,
        target_domain=target_domain,
        source_domains=source_domains,
        explicit=explicit,
        is_deictic_followup=is_deictic,
        reason_codes=tuple(reason_codes),
    )


def _first_action(lowered: str, reason_codes: list[str]) -> str | None:
    if any(term.casefold() in lowered for term in (*CREATE_TERMS, *TRANSFORM_CREATE_TERMS)):
        reason_codes.append("intent:action:create")
        return "create"
    if any(term.casefold() in lowered for term in EXECUTE_TERMS):
        reason_codes.append("intent:action:execute")
        return "execute"
    if any(term.casefold() in lowered for term in UPDATE_TERMS):
        reason_codes.append("intent:action:update")
        return "update"
    if any(term.casefold() in lowered for term in ANALYZE_TERMS):
        reason_codes.append("intent:action:analyze")
        return "analyze"
    return None


def _mentioned_domains(lowered: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(domain for domain, _, _ in _mentioned_domain_spans(lowered)))


def _mentioned_domain_spans(lowered: str) -> tuple[tuple[str, int, int], ...]:
    matches: list[tuple[str, int, int]] = []
    for domain, terms in DOMAIN_TERMS:
        positions = [
            (position, position + len(term))
            for term in terms
            if (position := lowered.find(term.casefold())) >= 0
        ]
        if positions:
            start, end = min(positions, key=lambda item: (item[0], -(item[1] - item[0])))
            matches.append((domain, start, end))
    matches.sort(key=lambda item: (item[1], item[2], item[0]))
    return tuple(matches)


def _safe_fallback_target_domain(mentioned_domains: tuple[str, ...]) -> str | None:
    """Resolve only unambiguous single-domain fallbacks.

    Cross-domain role assignment belongs to the structured LLM decision. A
    deterministic fallback may preserve all mentioned domains as evidence, but
    must not turn token order into business target semantics.
    """
    if len(mentioned_domains) == 1:
        return mentioned_domains[0]
    return None
