---
name: test-asset-lifecycle
description: Use when the user asks to organize, copy, rename, delete, archive, version, tag, classify, or assess dependencies of TestAuto test cases, scenarios, flows, plans, API definitions, datasets, or reusable test assets.
triggers:
  - 测试资产
  - 用例目录
  - 标签
  - 复制用例
  - 重命名
  - 删除用例
  - 归档资产
  - 版本历史
  - 依赖关系
  - 资产清理
  - asset lifecycle
  - tags
routing_requires_tool:
  - real asset dependency
  - current asset list
  - asset version history
  - delete impact
  - archive status
  - 真实资产依赖
  - 当前资产列表
  - 资产版本历史
  - 删除影响
  - 归档状态
---

# Test Asset Lifecycle

## Workflow

1. Identify the asset type: HTTP case, WebSocket case, scenario, visual flow, test plan, API definition, dataset, report, media, or defect.
2. Before recommending delete, archive, rename, or copy operations for real assets, read current project context, dependencies, execution history, or reports when available.
3. Assess downstream impact: scenarios referencing cases, plans referencing cases/scenarios/flows, reports retaining historical snapshots, datasets bound to scenarios, and media linked to defects.
4. Prefer non-destructive actions such as tagging, archiving, duplicating, or disabling before deletion when historical runs or release gates depend on the asset.
5. If no write tool exists, provide an operation checklist and do not claim that assets were renamed, deleted, copied, tagged, or archived.

## Final Reply

- Separate confirmed asset facts from lifecycle recommendations.
- Include dependency and rollback considerations for destructive actions.
- Do not invent asset ids, tags, directories, versions, or archive status.
