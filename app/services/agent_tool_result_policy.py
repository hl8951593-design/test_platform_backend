from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResultIssue:
    path: str
    message: str

    def display(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


@dataclass(frozen=True)
class ToolResultPolicyDecision:
    tool_name: str
    status: str
    issues: list[ToolResultIssue]
    auto_fixable: list[ToolResultIssue]
    blocked: list[ToolResultIssue]
    needs_model_judgement: list[ToolResultIssue]
    repair_guidance: str
    followup_instruction: str

    @property
    def should_continue_reasoning(self) -> bool:
        return bool(self.auto_fixable or self.needs_model_judgement)


TOOL_RESULT_ISSUE_FIELD_NAMES = {
    "warning",
    "warnings",
    "issue",
    "issues",
    "diagnostic",
    "diagnostics",
    "error",
    "errors",
    "failure",
    "failures",
    "problem",
    "problems",
    "validation_error",
    "validation_errors",
}

TOOL_RESULT_BLOCKED_ISSUE_KEYWORDS = (
    "鉴权",
    "授权",
    "未授权",
    "认证",
    "登录",
    "token",
    "令牌",
    "secret",
    "credential",
    "密钥",
    "账号",
    "密码",
    "权限不足",
    "审批",
    "私有输入",
    "用户私有",
    "用户提供",
    "用户配置",
    "用户确认",
    "请用户",
    "请前端确认",
    "手动配置",
    "外部配置",
    "没有平台来源",
    "无法从平台",
)

TOOL_RESULT_AUTOFIX_ISSUE_KEYWORDS = (
    "硬编码",
    "未动态",
    "动态绑定",
    "提取器",
    "提取路径",
    "绑定",
    "断言",
    "expected",
    "路径",
    "数据集",
    "dataset",
    "schema",
    "validation",
    "invalid",
    "missing",
    "required",
    "format",
    "type",
    "json",
    "字段",
    "缺少",
    "格式",
    "类型",
    "无效",
    "非法",
    "校验",
    "已忽略",
    "已修正",
    "修正为",
    "不支持",
    "未返回",
    "无法推断",
    "companyName",
    "ipPatentId",
    "groupIds",
)

FINAL_RESPONSE_BUDGET_INSTRUCTION = (
    "如果下一步不再请求工具而要输出最终用户回复，请默认控制为简洁总结："
    "1）已完成什么；2）已自动修复/验证什么；3）仍需用户或外部配置处理的阻断项；4）建议下一步。"
    "不要默认展开完整场景步骤大表、完整 JSON 或长篇逐字段说明；详细结构以工具结果、run summary、"
    "ToolCall 详情或报告详情为准。只有用户明确要求详细步骤时才展开。"
)

DEFAULT_TOOL_RESULT_REPAIR_GUIDANCE = (
    "优先选择当前可用的 read/query/draft/validate 类安全工具补齐上下文、生成修复版或再次验证；不要编造缺失事实或私密凭据。"
)


class ToolResultPolicy:
    """Classify tool outputs and build model follow-up instructions."""

    def evaluate(self, call: Any) -> ToolResultPolicyDecision:
        tool_name = str(getattr(call, "tool_name", "") or "")
        status = str(getattr(call, "status", "") or "")
        if status != "succeeded":
            issues = [self._failed_tool_issue(call)]
        else:
            issues = self.quality_issues(getattr(call, "output_json_redacted", None))
        auto_fixable, blocked, needs_model_judgement = self.classify_issues(issues)
        repair_guidance = self.repair_guidance(tool_name)
        followup_instruction = self.followup_instruction(
            tool_name=tool_name,
            status=status,
            auto_fixable=auto_fixable,
            blocked=blocked,
            needs_model_judgement=needs_model_judgement,
            repair_guidance=repair_guidance,
        )
        return ToolResultPolicyDecision(
            tool_name=tool_name,
            status=status,
            issues=issues,
            auto_fixable=auto_fixable,
            blocked=blocked,
            needs_model_judgement=needs_model_judgement,
            repair_guidance=repair_guidance,
            followup_instruction=followup_instruction,
        )

    def build_message(self, call: Any) -> str:
        payload = {
            "tool_call_id": getattr(call, "tool_call_id", None),
            "tool_name": getattr(call, "tool_name", None),
            "status": getattr(call, "status", None),
            "approval_required": getattr(call, "approval_required", None),
            "output": getattr(call, "output_json_redacted", None),
            "error_code": getattr(call, "error_code", None),
            "error_message": getattr(call, "error_message", None),
        }
        decision = self.evaluate(call)
        return (
            "工具执行结果如下。请根据这个结果继续完成用户请求；"
            "如果工具失败，请先判断是否属于可修复的输入、schema、validation、草稿结构或字段绑定问题；"
            "可修复时必须优先修复并重试安全工具，不要再次声明已经执行成功。"
            f"{decision.followup_instruction}"
            f"\n\n{FINAL_RESPONSE_BUDGET_INSTRUCTION}\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def followup_instruction(
        self,
        *,
        tool_name: str,
        status: str,
        auto_fixable: list[ToolResultIssue],
        blocked: list[ToolResultIssue],
        needs_model_judgement: list[ToolResultIssue],
        repair_guidance: str,
    ) -> str:
        if not auto_fixable and not needs_model_judgement:
            return ""
        if status != "succeeded":
            return (
                f"\n\n工具失败修复闭环：本次 {tool_name} 失败，但错误看起来可能由工具输入、schema、validation、草稿结构或字段格式导致。"
                "不要直接把这类可修复错误交给用户。请先基于错误信息、原工具输入、用户目标和平台上下文修正参数，"
                "并在安全范围内再次调用同一工具或推荐的 draft/validate 工具。"
                "只有鉴权令牌、账号密码、密钥、权限审批、用户私有输入或没有平台来源的信息才作为阻断项交给用户。"
                f"\n推荐修复路径：{repair_guidance}"
                f"\n可自动修复项：{json.dumps([item.display() for item in auto_fixable], ensure_ascii=False)}"
                f"\n需要用户输入或外部配置的阻断项：{json.dumps([item.display() for item in blocked], ensure_ascii=False)}"
                f"\n需要模型继续判断的项：{json.dumps([item.display() for item in needs_model_judgement], ensure_ascii=False)}"
            )
        return (
            f"\n\n通用工具结果质量闭环：本次 {tool_name} 已成功执行，但工具输出包含 warnings/issues/diagnostics。"
            "不要直接把可修复项总结给用户。请先结合用户目标、当前工具请求、工具输出、历史工具结果和平台上下文逐项分析根因，"
            "把问题拆分为：1）可由已有平台数据、响应样本、草稿结构或安全工具再次执行推断并修复的项；"
            "2）必须用户提供或外部配置的阻断项；3）需要你继续判断的项。"
            "对于可自动修复项，如果存在 read/query/draft/validate/dry-run 等安全修复路径，下一轮必须优先调用合适工具生成修复版或再次验证，"
            "不要结束 run；只有可修复项已经修复、验证通过或重试后证明无法继续自动修复时，才输出最终答复。"
            "鉴权令牌、账号密码、密钥、权限审批、没有平台来源的私有输入等，不要编造，只作为用户阻断项说明。"
            f"\n推荐修复路径：{repair_guidance}"
            f"\n可自动修复项：{json.dumps([item.display() for item in auto_fixable], ensure_ascii=False)}"
            f"\n需要用户输入或外部配置的阻断项：{json.dumps([item.display() for item in blocked], ensure_ascii=False)}"
            f"\n需要模型继续判断的项：{json.dumps([item.display() for item in needs_model_judgement], ensure_ascii=False)}"
        )

    def quality_issues(self, output: Any, *, max_items: int = 20) -> list[ToolResultIssue]:
        issues: list[ToolResultIssue] = []
        seen: set[str] = set()

        def add(path: str, value: Any) -> None:
            if len(issues) >= max_items:
                return
            message = self.compact_issue_message(value)
            if not message:
                return
            issue = ToolResultIssue(path=path, message=message)
            display = issue.display()
            if display in seen:
                return
            seen.add(display)
            issues.append(issue)

        def collect(value: Any, path: str, depth: int) -> None:
            if len(issues) >= max_items or depth > 6:
                return
            if isinstance(value, list):
                for index, item in enumerate(value[:max_items]):
                    if isinstance(item, (dict, list)):
                        item_path = f"{path}[{index}]"
                        add(item_path, item)
                        visit(item, item_path, depth + 1)
                    else:
                        add(f"{path}[{index}]", item)
                return
            if isinstance(value, dict):
                add(path, value)
                visit(value, path, depth + 1)
                return
            add(path, value)

        def visit(value: Any, path: str, depth: int) -> None:
            if len(issues) >= max_items or depth > 6:
                return
            if isinstance(value, dict):
                if value.get("valid") is False:
                    add(self.join_issue_path(path, "valid"), "valid=false")
                for key, child in value.items():
                    key_text = str(key)
                    child_path = self.join_issue_path(path, key_text)
                    if key_text.lower() in TOOL_RESULT_ISSUE_FIELD_NAMES:
                        collect(child, child_path, depth + 1)
                    elif isinstance(child, (dict, list)):
                        visit(child, child_path, depth + 1)
                return
            if isinstance(value, list):
                for index, child in enumerate(value[:max_items]):
                    visit(child, f"{path}[{index}]" if path else f"[{index}]", depth + 1)

        visit(output, "", 0)
        return issues

    def classify_issues(
        self,
        issues: list[ToolResultIssue],
    ) -> tuple[list[ToolResultIssue], list[ToolResultIssue], list[ToolResultIssue]]:
        auto_fixable: list[ToolResultIssue] = []
        blocked: list[ToolResultIssue] = []
        needs_model_judgement: list[ToolResultIssue] = []
        for issue in issues:
            if self.issue_matches(issue, TOOL_RESULT_BLOCKED_ISSUE_KEYWORDS):
                blocked.append(issue)
            elif self.issue_matches(issue, TOOL_RESULT_AUTOFIX_ISSUE_KEYWORDS):
                auto_fixable.append(issue)
            else:
                needs_model_judgement.append(issue)
        return auto_fixable, blocked, needs_model_judgement

    def repair_guidance(self, tool_name: str) -> str:
        if not tool_name:
            return DEFAULT_TOOL_RESULT_REPAIR_GUIDANCE
        from fastapi import HTTPException

        from app.services.agent_tool_service import ToolRegistry

        try:
            spec = ToolRegistry().get(tool_name)
        except HTTPException:
            return DEFAULT_TOOL_RESULT_REPAIR_GUIDANCE
        return spec.tool_result_repair_guidance or DEFAULT_TOOL_RESULT_REPAIR_GUIDANCE

    def compact_issue_message(self, value: Any, *, max_length: int = 500) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            text = value
        elif isinstance(value, dict):
            preferred: list[str] = []
            for key in ("code", "type", "msg", "message", "detail", "reason", "loc", "path", "field", "severity"):
                if key in value and value[key] not in (None, "", [], {}):
                    item = value[key]
                    if isinstance(item, (dict, list)):
                        item_text = json.dumps(item, ensure_ascii=False, default=str)
                    else:
                        item_text = str(item)
                    preferred.append(f"{key}={item_text}")
            text = "; ".join(preferred) if preferred else json.dumps(value, ensure_ascii=False, default=str)
        else:
            text = json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, list) else str(value)
        text = " ".join(text.split())
        if len(text) > max_length:
            return f"{text[:max_length]}..."
        return text

    @staticmethod
    def join_issue_path(parent: str, child: str) -> str:
        return f"{parent}.{child}" if parent else child

    @staticmethod
    def issue_matches(issue: ToolResultIssue, keywords: tuple[str, ...]) -> bool:
        text = issue.display().lower()
        return any(keyword.lower() in text for keyword in keywords)

    def _failed_tool_issue(self, call: Any) -> ToolResultIssue:
        message = " ".join(
            item
            for item in (str(getattr(call, "error_code", "") or ""), str(getattr(call, "error_message", "") or ""))
            if item
        )
        return ToolResultIssue(path="tool.error", message=message)


def build_tool_result_message(call: Any) -> str:
    return ToolResultPolicy().build_message(call)
