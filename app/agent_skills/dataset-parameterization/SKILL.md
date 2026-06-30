---
name: dataset-parameterization
description: Use when the user asks to design, review, generate, debug, or explain TestAuto datasets, dataset records, parameterization, request overrides, per-record runs, variables, CSV/JSON data, boundary data, or data-driven scenario execution.
triggers:
  - dataset
  - datasets
  - data-driven
  - parameterization
  - parameterized
  - CSV
  - JSON data
  - 数据集
  - 参数化
  - 数据驱动
  - 测试数据
  - record
  - records
routing_requires_tool:
  - current dataset
  - real dataset
  - dataset records
  - 当前数据集
  - 真实数据集
  - 数据集记录
---

# Dataset Parameterization

## Workflow

1. For test data strategy, boundary data, CSV/JSON shape, and parameterization advice, answer directly.
2. For real project dataset facts, use available project/scenario/read tools first and state when no dataset-specific read tool exists.
3. For scenario composition that should include datasets, follow `scenario-composition` guidance and request dataset-aware draft behavior through safe draft tools.
4. Do not claim that datasets, records, overrides, or CSV imports were saved unless a dedicated backend tool succeeds.

## Data Quality

- Prefer records with stable ids/names, explicit enabled state, and per-step path/header/query/body overrides.
- Keep environment variables, dataset variables, and upstream extracted variables distinct.
- Cover positive, negative, boundary, empty, duplicate, special character, permission, and idempotency data.
- Avoid putting secrets, passwords, or real tokens in records.

## Final Reply

- State whether the answer is a data design, draft, validation note, or unsupported save/import action.
- Summarize variable names, record structure, risk cases, and next verification step.
