---
name: api-definition-import
description: Use when the user asks to design, import, normalize, review, or troubleshoot API definitions, OpenAPI/Swagger specs, endpoint assets, interface catalogs, path/method/schema extraction, or generating test cases from API definitions.
triggers:
  - OpenAPI
  - Swagger
  - API definition
  - interface definition
  - endpoint catalog
  - import API
  - 接口定义
  - 接口资产
  - OpenAPI导入
  - Swagger导入
  - 从接口生成用例
routing_requires_tool:
  - current API definition
  - real API definition
  - imported API definition
  - 当前接口定义
  - 真实接口定义
  - 已导入接口
---

# API Definition Import

## Workflow

1. For OpenAPI design, review, normalization, and import planning, answer directly.
2. If the user asks for real imported API definitions or endpoint assets, use available project read tools first and state when no API-definition read tool exists.
3. If enough endpoint detail is provided, convert it into HTTP test case draft guidance or use `ai_skill.run_draft` with `skill_id=http-test-case`.
4. Do not claim that an OpenAPI file, endpoint asset, tag, schema, or generated test case was imported or saved unless a dedicated backend tool succeeds.

## Import Quality

- Normalize method, path, operationId, tags, parameters, requestBody, responses, auth schemes, examples, and server/base URL.
- Preserve schema constraints for assertions and data generation.
- Treat undocumented auth, dynamic ids, pagination, file upload, callbacks, and polymorphic schemas as review items.
- Redact secrets and avoid embedding production tokens from examples.

## Final Reply

- Separate import readiness, mapping assumptions, generated draft suggestions, and unsupported persistence actions.
