---
name: http-test-case
description: Generate, expand, or summarize HTTP API test case drafts for the test platform from API docs, curl snippets, existing cases, request/response samples, and natural language requirements.
---

# HTTP Test Case Skill

Use this skill when an agent needs to generate or expand HTTP API test case drafts, or when the UI needs a concise saved-case description from an HTTP request or request/response sample.

## Inputs

- `mode`: `generate`, `expand`, or `summarize_description`
- `project_id`
- `environment`
- `environment_variables`
- `payload`
- `source_test_case`: required for `expand`; optional context for `summarize_description`
- `request`: required for `summarize_description`
- `response`: optional for `summarize_description`; present when summarizing after a debug run

## Output

For `generate` and `expand`, return platform-compatible `AIGeneratedTestCaseResponse` data. Every generated case must be normalized and validated against `TestCaseCreateRequest`.

For `summarize_description`, return `AIHttpTestCaseDescriptionSummaryResponse`:

```json
{
  "description": "A concise Chinese description for the test case description field.",
  "source_summary": "request",
  "warnings": []
}
```

The description is a draft for the `test_cases.description` field. It is returned to the frontend and is not saved automatically.

## Runtime Notes

- Use `prompts/generate_system.md` for new case generation.
- Use `prompts/expand_system.md` for expansion from an existing case.
- The runtime adapter owns context construction, AI invocation settings, JSON parsing, normalization, and schema validation.
- `summarize_description` uses the unified skill runner operation `POST /api/v1/ai/skills/http-test-case/run` with `operation=summarize_description`.
- The summary adapter must mask sensitive headers and tokens before sending context to the model.
