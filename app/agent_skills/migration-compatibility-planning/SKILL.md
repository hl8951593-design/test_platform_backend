---
name: migration-compatibility-planning
description: Use when the user asks to plan or diagnose database migrations, backward compatibility, legacy data repair, schema upgrades, API compatibility, rollout order, rollback, or old-client behavior for TestAuto.
triggers:
  - 迁移
  - 数据迁移
  - Alembic
  - 兼容性
  - 升级
  - 回滚
  - 历史数据
  - 旧客户端
  - schema upgrade
  - backward compatibility
  - rollout
  - rollback
routing_requires_tool:
  - real migration state
  - current alembic head
  - legacy data sample
  - compatibility issue
  - rollback status
  - 真实迁移状态
  - 当前迁移版本
  - 历史数据样本
  - 兼容性问题
  - 回滚状态
---

# Migration Compatibility Planning

## Workflow

1. Identify whether the change affects database schema, API request/response shape, frontend contract, historical execution/report data, or background workers.
2. For real migration state, verify Alembic head, model fields, existing data, and API contract before saying the system is upgraded.
3. Plan forward migration, idempotent data repair, compatibility fallback, rollout order, monitoring, and rollback limits.
4. Preserve historical execution/report snapshots when possible; do not rewrite audit records unless there is an explicit migration requirement.
5. If no tool can inspect the target environment, present verification commands and risk checks rather than claiming current production state.

## Final Reply

- Separate proposed migration steps, verified current state, and rollback caveats.
- Mention docs/API contract updates when request or response shape changes.
- Do not invent Alembic versions, database rows, legacy-client behavior, or rollback success.
