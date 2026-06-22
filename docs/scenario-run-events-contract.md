# 场景运行事件契约

SSE 地址为 `GET /api/v1/scenario-runs/{run_id}/events?project_id={id}`，使用 Bearer Token，
通过 `Last-Event-ID` 请求断点后的事件。事件先持久化再发送；单个 run 的 `sequence` 严格递增，
客户端以 `run_id + sequence` 去重。

事件包括 `run_queued`、`run_started`、`step_started`、`step_completed`、`step_failed`、
`step_skipped`、`transition_started`、`run_completed`、`run_failed` 和 `heartbeat`。步骤载荷
包含 `step_id/index`，结果与详情同时包含 `node_id/index/phase`。当前事件不自动过期，因此尚不
产生 `EVENT_HISTORY_EXPIRED`；若未来增加清理，必须先实现 409 与详情校准契约。
