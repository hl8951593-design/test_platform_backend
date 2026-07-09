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
capabilities:
  - inspect environment configs
  - create environment config
  - update environment config
  - delete environment config
  - inspect environment variables
  - upsert environment variable
  - delete environment variable
  - update Lingxi-Auth token
required_context:
  - current project environment
  - default environment
  - environment variable inventory
tools:
  - project.read_context
  - environment.query_project_configs
  - environment.create_config
  - environment.update_config
  - environment.delete_config
  - environment.upsert_variable
  - environment.delete_variable
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
3. For environment inventory or variable names, use `environment.query_project_configs`; secret values must stay masked.
4. For creating, updating, or deleting environments, use `environment.create_config`, `environment.update_config`, or `environment.delete_config` and wait for approval.
5. For creating, updating, or deleting variables, use `environment.upsert_variable` or `environment.delete_variable` and wait for approval.
6. Do not claim that an environment or variable was created, updated, deleted, or marked default unless the dedicated backend tool succeeds.
7. If the user asks how to fix unauthorized API responses, separate environment-variable configuration from test case or scenario draft issues.

## Guidance

- Prefer environment variables for auth tokens, tenant ids, host-specific headers, dynamic account data, and secrets.
- Never put plaintext passwords, bearer tokens, cookies, or private keys into final replies or drafts.
- For auth/token/cookie variables such as `Lingxi-Auth`, set `is_secret=true`.
- Explain whether a value should be global to an environment, extracted from an upstream response, or supplied by the user at execution time.
- When diagnosing binding failures, check variable name spelling, `{{variable}}` syntax, scope, default environment, and whether the execution path actually renders variables before sending the request.

## Final Reply

- Separate confirmed environment facts from configuration recommendations.
- For successful secret updates, confirm the variable name/environment only; do not echo the secret value.
- If approval is pending or rejected, say that the environment has not been changed yet.
