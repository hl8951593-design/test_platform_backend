# 场景运行详情契约

`GET /api/v1/scenario-runs/{run_id}?project_id={id}` 返回运行身份、状态、耗时、变量快照和
`step_results`。运行身份必须同时包含 dataset 与 record 的 ID/name；同一 dataset 的不同 record
不能合并审计。

执行中详情包含 `current_step_id/index`、`last_event_sequence` 以及 pending/running 结果。
每个步骤结果包含节点位置、状态、起止时间、请求/响应快照、断言、attempt history、变量提取、
绑定追踪和错误信息。敏感字段按统一快照规则掩码。
