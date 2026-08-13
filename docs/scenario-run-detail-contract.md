# 场景运行详情契约

`GET /api/v1/scenario-runs/{run_id}?project_id={id}` 返回运行身份、状态、耗时、变量快照和
`step_results`。运行身份必须同时包含 dataset 与 record 的 ID/name；同一 dataset 的不同 record
不能合并审计。

`GET /api/v1/scenario-runs` 是轻量历史列表。启用归一化步骤存储时，列表项的原始
`step_results` 可以为空；这表示“步骤详情尚未加载”，不能解释为该运行有 0 个步骤。调用方应在
用户展开记录时请求上述详情接口，再依据组装后的 `step_results` 展示通过数和总步骤数。

## 归一化步骤存储与兼容组装

`GET /api/v1/scenario-runs/{run_id}` 的返回结构不变。默认配置 `EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED=true` 时，运行热路径不再反复覆盖 `test_scenario_runs.step_results`；每个 running/completed/skipped/timeout 步骤写入 `execution_step_diagnostics` 的独立行。

详情读取按照与执行器相同的节点顺序规则组装：每个节点依次为 `before_actions -> test_case -> after_actions`。已持久化的 running/completed/skipped 行覆盖快照生成的 pending 行；尚未开始的步骤保持原 `step_id/step_index/kind/name/node_id/node_index/node_phase` 和 `status=pending`。历史运行尚未回填时，兼容层使用原 `step_results`，因此切换不会把旧完成记录误显示为 pending。

小型脱敏 request/response/log/retry 内容内联保存；大字段以 `artifact_ref` 保存。公共完整详情在项目权限和执行身份校验后恢复 artifact，并继续执行原有 HTTP/WebSocket 子执行快照补全；Agent 诊断视图只返回引用、omission 和 continuation，不读取完整 blob。

SSE 的事件顺序、`current_step_id/current_step_index/last_event_sequence`、终态、重试和变量语义不变。变化仅限持久化方式：单步完成只写当前步骤和变量/run 摘要，不再产生随历史长度增长的 JSON 写放大。

回滚时先执行：

```powershell
.venv\Scripts\python.exe scripts/backfill_execution_diagnostics.py --project-id <id> --execution-type scenario --batch-size 500 --restore-legacy-snapshots
```

确认批次完成后再设置 `EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED=false`。恢复命令可重复运行，按执行 ID 分批提交。

执行中详情包含 `current_step_id/index`、`last_event_sequence` 以及 pending/running 结果。
每个步骤结果包含节点位置、状态、起止时间、请求/响应快照、断言、attempt history、变量提取、
绑定追踪和错误信息。敏感字段按统一快照规则掩码。
