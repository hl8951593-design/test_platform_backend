---
name: security-auth-testing
description: Use when the user asks to design or diagnose authentication, authorization, token, session, cookie, permission boundary, rate limit, CSRF, replay, or security-negative tests for TestAuto APIs and scenarios.
triggers:
  - 鉴权
  - 认证
  - 授权
  - 权限边界
  - token
  - JWT
  - session
  - cookie
  - CSRF
  - 越权
  - 限流
  - 安全测试
  - 90001
routing_requires_tool:
  - real auth failure
  - current auth config
  - permission boundary
  - real security result
  - token variable
  - 真实鉴权失败
  - 当前鉴权配置
  - 权限边界
  - 真实安全结果
  - 令牌变量
---

# Security And Auth Testing

## Workflow

1. Separate platform login/authentication, target-system authentication, project permission, and API business authorization. Do not merge these into one vague "permission issue".
2. For real project facts, read context, environment variables, recent reports, or execution results before asserting token state, permission ownership, or failure cause.
3. Build negative cases for missing token, expired token, malformed token, wrong role, cross-project access, replay, CSRF when applicable, rate limit, and sensitive-field leakage.
4. Treat secrets, passwords, private tokens, and user-owned credentials as blockers unless they already exist in a safe platform variable or tool result.
5. When a scenario can be repaired without secrets, update extractors, variable names, assertions, and request bindings before asking the user.

## Final Reply

- State which security behavior is proven, inferred, or still blocked by missing credentials.
- Never print raw tokens, cookies, passwords, or secret headers.
- Do not claim a permission or token was configured unless a tool result confirms it.
