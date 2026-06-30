---
name: data-privacy-redaction
description: Use when the user asks about sensitive data masking, token redaction, privacy handling, PII, secret leakage, AI prompt redaction, report/log sanitization, signed URL exposure, or data retention risk in TestAuto.
triggers:
  - 脱敏
  - 敏感数据
  - 隐私
  - PII
  - secret
  - token 泄露
  - 密钥
  - 日志脱敏
  - 报告脱敏
  - prompt 脱敏
  - signed URL
  - redaction
routing_requires_tool:
  - real sensitive leak
  - current redaction policy
  - raw execution snapshot
  - report sensitive field
  - signed URL exposure
  - 真实敏感泄露
  - 当前脱敏策略
  - 原始执行快照
  - 报告敏感字段
  - 签名URL暴露
---

# Data Privacy Redaction

## Workflow

1. Classify sensitive data: credentials, bearer tokens, cookies, API keys, passwords, personal data, request/response bodies, screenshots, logs, signed URLs, and AI prompts.
2. For real leaks, require the specific artifact, request id, run id, report id, or tool evidence before stating scope.
3. Prefer redaction at capture, storage, model prompt construction, final reply, report export, and frontend display boundaries.
4. Preserve debugging utility by keeping field names, hashes, lengths, status codes, and structural paths where safe.
5. Do not reproduce raw secrets in the final answer, even if the user pasted them.

## Final Reply

- State the affected surface and recommended redaction layer.
- Include safe examples using placeholders such as `<redacted_token>`.
- Do not expose or repeat secrets, PII, cookies, signed URLs, or raw credentials.
