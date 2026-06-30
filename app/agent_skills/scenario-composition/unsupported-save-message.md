当前 Agent 可用工具中没有“保存正式场景”的后端工具。`scenario.compose_draft` 只能生成草稿，`scenario.execute_dry_run` 只能执行 dry-run，都不会把草稿持久化为正式场景实体。

我不能假装已经保存，也不会重新生成一份草稿来冒充保存结果。请在前端保存当前草稿，或先补充后端 `scenario.save/create` 工具后再让我执行保存。
