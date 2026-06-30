---
name: ai-skill-runtime-governance
description: Use when the user asks about TestAuto AI Skill packages, AI draft generation, manifest/schema constraints, prompt repair, JSON parsing failures, model settings, AI Skill Run observability, or generated draft validation.
triggers:
  - AI Skill
  - ai_skill
  - ai skill run
  - 草稿生成
  - 生成用例
  - 扩写用例
  - JSON 修复
  - manifest
  - schema
  - prompt
  - 模型输出
  - DeepSeek
  - provider
routing_requires_tool:
  - real AI skill run
  - current AI provider
  - generated draft
  - schema validation result
  - model output failure
  - 真实AI Skill运行
  - 当前AI数据源
  - 生成草稿
  - schema校验结果
  - 模型输出失败
---

# AI Skill Runtime Governance

## Workflow

1. Identify the formal AI Skill package involved: `http-test-case`, `websocket-test-case`, `scenario-composer`, or a future registered skill.
2. For real provider status, run ids, generated drafts, validation warnings, or model failures, use tool evidence before stating facts.
3. Keep generated outputs as drafts until schema validation, normalization, and user/platform save actions succeed.
4. Diagnose failures by separating provider connectivity, timeout, JSON mode, prompt/schema mismatch, local JSON repair, Pydantic validation, and business normalization.
5. Do not bypass the formal Skill manifest or invent operations not registered in `/ai/skills`.

## Final Reply

- State whether the issue is provider, prompt, parser, schema, normalization, or business validation.
- Mention the exact Skill id and operation only when known.
- Do not claim generated drafts were saved as formal cases or scenarios unless a save tool confirms it.
