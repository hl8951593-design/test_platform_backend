---
name: websocket-test-case
description: Generate or expand WebSocket session test case drafts for the test platform from protocol docs, captured traffic, existing cases, and natural language requirements.
---

# WebSocket Test Case Skill

Use this skill when an agent needs to generate or expand WebSocket test case drafts.

## Inputs

- `mode`: `generate` or `expand`
- `project_id`
- `environment`
- `environment_variables`
- `payload`
- `source_websocket_test_case`: required for `expand`

## Output

Return platform-compatible `AIGeneratedWebSocketTestCaseResponse` data. Every generated case must be normalized and validated against `WebSocketTestCaseCreateRequest`.

## Runtime Notes

- Use `prompts/generate_system.md` for new WebSocket case generation.
- Use `prompts/expand_system.md` for expansion from an existing WebSocket case.
- The runtime adapter owns context construction, AI invocation settings, JSON parsing, normalization, and schema validation.
