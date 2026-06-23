---
name: scenario-composer
description: Compose intelligent test scenarios from existing HTTP and WebSocket test cases for the test platform, including pre-actions, post-actions, assertions, extractors, and variable bindings inferred from request and response samples. Use when an agent needs to turn selected test cases, API flows, dependency hints, execution samples, or natural language business goals into an executable scenario draft.
---

# Scenario Composer Skill

Use this skill to compose a scenario draft from existing test cases.

## Inputs

- `mode`: `compose`
- `project_id`
- `environment`
- `payload`
- `candidate_cases`: selected HTTP and WebSocket test cases with assertions, extractors, request/session shape, environment bindings, and optional execution samples.

## Output

Return platform-compatible `AIGeneratedScenarioResponse` data. The `scenario` field must validate as `ScenarioCreateRequest`.

## Runtime Notes

- Use `prompts/compose_system.md`.
- Only reference candidate case IDs supplied by the runtime context.
- Prefer simple node ordering and explicit `_scenario_context.bindings` where a later request uses a variable extracted by an earlier step.
- Infer useful `assertions` and `extractors` from `execution_sample.response_snapshot` when the source case lacks them or the user asks for richer validation.
- Use `before_actions` and `after_actions` only for meaningful setup, gating, waits, cleanup, or computed variables.
- The runtime adapter owns AI invocation settings, JSON parsing, reference checks, normalization, and schema validation.
