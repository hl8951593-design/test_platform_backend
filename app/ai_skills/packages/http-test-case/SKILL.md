---
name: http-test-case
description: Generate or expand HTTP API test case drafts for the test platform from API docs, curl snippets, existing cases, and natural language requirements.
---

# HTTP Test Case Skill

Use this skill when an agent needs to generate or expand HTTP API test case drafts.

## Inputs

- `mode`: `generate` or `expand`
- `project_id`
- `environment`
- `environment_variables`
- `payload`
- `source_test_case`: required for `expand`

## Output

Return platform-compatible `AIGeneratedTestCaseResponse` data. Every generated case must be normalized and validated against `TestCaseCreateRequest`.

## Runtime Notes

- Use `prompts/generate_system.md` for new case generation.
- Use `prompts/expand_system.md` for expansion from an existing case.
- The runtime adapter owns context construction, AI invocation settings, JSON parsing, normalization, and schema validation.
