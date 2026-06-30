---
name: environment-config-management
description: Use when the user asks to explain, inspect, design, troubleshoot, or plan TestAuto project environments, default environment, base_url, environment variables, variable substitution, auth token variables, or multi-environment binding.
triggers:
  - environment
  - env
  - base_url
  - variable
  - variables
  - default environment
  - 环境
  - 默认环境
  - 环境变量
  - 变量替换
  - base_url
  - Lingxi-Auth
routing_requires_tool:
  - current project environment
  - default environment
  - real environment
  - 当前项目环境
  - 默认环境
  - 真实环境
---

# Environment Config Management

## Workflow

1. For conceptual advice about environment design, variable naming, and token handling, answer directly.
2. For current project environment facts, use `project.read_context` before giving names, ids, default flags, or base URLs.
3. Do not claim that an environment or variable was created, updated, deleted, or marked default unless a dedicated backend tool succeeds.
4. If the user asks how to fix unauthorized API responses, separate environment-variable configuration from test case or scenario draft issues.

## Guidance

- Prefer environment variables for auth tokens, tenant ids, host-specific headers, dynamic account data, and secrets.
- Never put plaintext passwords, bearer tokens, cookies, or private keys into final replies or drafts.
- Explain whether a value should be global to an environment, extracted from an upstream response, or supplied by the user at execution time.
- When diagnosing binding failures, check variable name spelling, `{{variable}}` syntax, scope, default environment, and whether the execution path actually renders variables before sending the request.

## Final Reply

- Separate confirmed environment facts from configuration recommendations.
- State clearly when a missing environment write tool prevents direct changes.
