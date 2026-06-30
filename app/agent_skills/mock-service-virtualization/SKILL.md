---
name: mock-service-virtualization
description: Use when the user asks to design mock APIs, stubs, service virtualization, fake dependencies, contract simulation, unavailable upstream replacement, or deterministic responses for TestAuto testing.
triggers:
  - mock
  - Mock
  - stub
  - fake
  - 服务虚拟化
  - 模拟服务
  - 挡板
  - 契约模拟
  - 依赖不可用
  - 稳定响应
routing_requires_tool:
  - real mock service
  - current API definition
  - existing stub
  - upstream contract
  - 真实Mock服务
  - 当前接口定义
  - 已有挡板
  - 上游契约
---

# Mock Service Virtualization

## Workflow

1. Identify whether the user needs a one-off response example, a reusable mock rule, or full service virtualization across scenario steps.
2. Prefer existing API definitions, captured traffic, testcase schemas, and recent execution responses as the source of mock contracts.
3. Define request matching, response templates, latency, error injection, stateful behavior, and teardown needs.
4. Keep mock data deterministic unless the test explicitly requires randomness. Document any generated fields and variable bindings.
5. If the platform lacks a mock creation tool, provide a draft contract and explain that no mock has been persisted.

## Final Reply

- Separate proposed mock behavior from actually configured mock services.
- Mention which upstream dependency or API contract still needs confirmation.
- Do not invent a live mock URL, rule id, or persisted stub.
