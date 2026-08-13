# TestAuto Desktop UI 执行 API

> 状态：已实现（运行、SSE、本地导入、产物交付和统一投影闭环）
>
> 最近核验：2026-07-18
>
> Alembic revision：`0048_ui_execution_runtime` + `0049_ui_execution_artifact_delivery` + `0050_ui_execution_patch_requests`

## 1. 身份与响应

- 平台用户接口使用 `Authorization: Bearer <user_access_token>`，并校验项目权限。
- Desktop 写接口使用独立 `Authorization: Bearer <device_access_token>`，用户 token 不可替代设备 token。
- 成功响应沿用 `{code,message,data}`；运行时冲突的 `detail.error` 是稳定机器码。
- 时间字段统一返回 RFC 3339 UTC，例如 `2026-07-16T11:30:00.000Z`。

## 2. 创建、列表与详情

| 方法 | 路径 | 身份 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/ui-test-cases/{case_id}/execute?project_id={id}` | 用户 `test:execute` | 创建 queued 执行，返回 `202` |
| `GET` | `/api/v1/ui-executions?project_id={id}` | 用户 `report:view` | 分页列表、筛选和队列 facets |
| `GET` | `/api/v1/ui-executions/available?limit={n}` | 设备 | 返回当前设备可领取的 queued/assigned 执行 |
| `GET` | `/api/v1/ui-executions/{execution_id}` | 用户 `report:view` | 摘要、步骤、修补和命令详情 |
| `GET` | `/api/v1/ui-executions/{execution_id}/events` | 用户 `report:view` | 按 `after_sequence` 增量读取事件 |
| `GET` | `/api/v1/ui-executions/{execution_id}/events/stream` | 用户 `report:view` | SSE 实时事件与断线重放 |
| `POST` | `/api/v1/ui-executions/import-local-run?project_id={id}` | 用户 `test:execute` | 导入已完成的本地调试运行 |

创建请求：

```json
{
  "client_request_id": "desktop-20260716-0001",
  "version": 4,
  "environment_id": 3,
  "requested_device_id": "dev_01J...",
  "source": "platform_task",
  "runtime_options": {
    "trace": "retain-on-failure",
    "screenshot": "only-on-failure"
  }
}
```

创建成功返回：

```json
{
  "code": 0,
  "message": "UI execution accepted",
  "data": {
    "execution_id": "ui_exec_01J...",
    "status": "queued",
    "delivery_status": "pending",
    "created_at": "2026-07-16T11:30:00.000Z"
  }
}
```

`client_request_id` 在 `project_id + trigger_user_id` 范围唯一。完全相同的重试返回同一执行；同一幂等键承载不同 payload 返回 `409 client_request_id_payload_conflict`。

列表支持 `status`、`delivery_status`、`attention_only`、`assigned_device_id`、`environment_id`、`source`、`keyword`、`page/page_size`。摘要直接返回 `project_name` 与 `environment_name`，Desktop 不需要显示内部 ID 或逐行补查名称。`facets` 同批返回 `queued/running/waiting_user/delivery_failed`，客户端不需要额外发送四次 count 请求。

设备队列恢复使用独立设备 token 调用 `GET /api/v1/ui-executions/available`，`limit` 默认为 20、范围为 1..200。返回 `data.items/total`；每项沿用执行摘要并增加 `expected_status`，Desktop 应把它原样传给 claim：

平台列表在两次仓储 SQL 内返回分页项、过滤总数和四类 facets；设备 available 在一次候选查询内同时返回 items/total。该约束只减少轮询数据库往返，不改变过滤、排序、并发容量或 claim 的最终仲裁。

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "execution_id": "ui_exec_01J...",
        "project_id": 10,
        "project_name": "TestAuto 主平台",
        "case_id": "ui_case_01J...",
        "case_name": "用户登录",
        "environment_id": 3,
        "environment_name": "测试环境",
        "status": "queued",
        "expected_status": "queued",
        "requested_device_id": null,
        "assigned_device": null,
        "source": "platform_task",
        "created_at": "2026-07-16T11:30:00.000Z"
      }
    ],
    "total": 1
  }
}
```

服务端只返回设备已启用且允许接单的项目绑定内任务，并排除 requested/assigned 给其他设备、Desktop/DSL/IPC 版本不兼容以及设备或项目绑定并发已满的任务。available 是断线恢复与任务发现的权威读取面，但不是领取锁；多 Desktop 并发时仍必须调用 claim，由 claim 在事务内做最终状态、指定设备、版本和并发仲裁。

创建未指定 `requested_device_id` 的执行时，后端会向该项目所有 active、允许接单且支持 `ui-case-v1 + desktop-ipc-v1` 的设备发送 `execution.available`。同进程连接直接发送，同时经 Redis pub/sub 扇出到其他 API 进程；指定设备的执行只通知目标设备。WSS/Redis 均只负责提示，数据库查询与 claim 是权威恢复和并发仲裁面。

## 3. claim 与 lease

| 方法 | 路径 | 身份 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/ui-executions/{id}/claim` | 设备 | 原子领取并取得快照和 lease |
| `POST` | `/ui-executions/{id}/lease/renew` | 设备 | 续租、校准序号并拉取待执行命令 |
| `POST` | `/ui-executions/{id}/lease/release` | 设备 | 在 `claimed/launching` 阶段释放任务 |

claim 请求必须声明设备身份和兼容版本：

```json
{
  "device_id": "dev_01J...",
  "expected_status": "queued",
  "supported_dsl_versions": ["ui-case-v1"],
  "supported_ipc_versions": ["desktop-ipc-v1"]
}
```

响应包含 `internal_execution_id`、public `execution_id`、服务端生成的 lease、`last_client_sequence`、不可变用例/环境快照、`required_secret_refs` 和 runtime policy。快照不包含密钥值；Desktop 使用 `last_client_sequence` 从服务端断点继续本地 Outbox 序号。

续租与后续所有设备写请求携带：

```json
{
  "lease_id": "lease_...",
  "lease_version": 1
}
```

续租成功由服务端递增 version 并计算新过期时间；同一旧 version 的直接重放返回当前 lease 且标记 `idempotent_replay=true`。后台扫描器定期把过期活动执行转为 `lost`，写入 `lease.lost` 事件和统一执行投影。

## 4. 事件、步骤与人工修补

```http
POST /api/v1/ui-executions/{execution_id}/events/batch
Authorization: Bearer <device_access_token>
```

```json
{
  "lease_id": "lease_...",
  "lease_version": 1,
  "events": [
    {
      "client_event_id": "evt-0001",
      "client_sequence": 1,
      "event_type": "execution.running",
      "occurred_at": "2026-07-16T11:30:02Z",
      "level": "info",
      "payload": {}
    }
  ]
}
```

- 序号从 1 连续递增；同 ID/序号/内容可重放，不同内容返回 `409 event_sequence_conflict`。
- 单批最多 100 个事件、512 KiB；单事件脱敏后最多 16 KiB，均可配置。
- 服务端在同一事务写事件、更新运行状态和步骤、同步 `execution_record_index` 与 `execution_step_diagnostics`。
- `step.retry`、`step.skipped`、`user.intervention`、`execution.assisted` 会锁定 `assisted=true`。
- payload 在持久化前统一脱敏。

SSE 使用 `Last-Event-ID` 作为服务端事件序号断点，返回 `id/event/data`，空闲期间发送注释心跳。WSS 不保存历史事实；页面重连时以 SSE 或 REST 增量读取为准。

平台发起当前运行修补请求：

```http
POST /api/v1/ui-executions/{execution_id}/patch-requests
Authorization: Bearer <user_access_token>
```

接口要求用户拥有 `test:execute`，执行已由设备领取且当前处于 `paused` 或 `waiting_user`。成功返回 `202`，并创建 `command_type=patch` 的可靠控制命令：

```json
{
  "client_request_id": "patch-request-0001",
  "step_id": "step_004",
  "patch_type": "locator",
  "before": {
    "locator_by": "css",
    "locator_value": "#login-button"
  },
  "after": {
    "locator_by": "role",
    "locator_value": "button: 登录"
  },
  "reason": "原定位器已失效",
  "expires_in_seconds": 300
}
```

`before` 可省略；传入时作为乐观并发条件，若与服务端按不可变快照和已应用 runtime patches 计算出的当前值不同，返回 `409 patch_request_stale`。字段白名单为：`locator -> locator_by/locator_value`、`input -> input_value`、`timeout -> timeout_ms`、`failure_policy -> failure_policy`；失败策略值为 `停止运行`、`重试一次`、`继续下一步` 或 `等待人工处理`。修补后的候选步骤必须重新通过 `ui-case-v1` 单步校验，空操作返回 `409 patch_request_noop`。

`client_request_id` 在 `project + user` 范围内幂等。WSS 只发送 `command.available` 提醒，Desktop 必须通过 lease renew 获取权威 patch 命令。执行详情的 `commands[]` 返回请求状态和 payload；摘要额外返回 `case_version/case_checksum`，平台可据此读取被冻结的用例版本。

Desktop 应用后记录当前运行修补：

```http
POST /api/v1/ui-executions/{execution_id}/patches
Authorization: Bearer <device_access_token>
```

如果修补来自平台命令，Desktop 必须在请求体携带对应 `command_id`。后端校验命令已投递、未过期且 `step_id/patch_type/before/after/reason` 完全一致；篡改返回 `409 patch_request_payload_conflict`。成功记录会返回同一 `command_id`，并把 `actor_user_id` 归属到平台发起用户、`actor_device_id` 归属到实际执行设备。未携带 `command_id` 的原有 Desktop 本地人工修补保持兼容。

只接受 `scope=current_run` 和 `locator/input/timeout/failure_policy`。相同命令或相同本地设备、步骤和内容的重试幂等；任何已应用修补都会锁定 assisted，绝不反写不可变用例版本。Desktop 随后使用现有 `/commands/{command_id}/ack` 返回 acknowledged 或 rejected。

## 5. 控制命令与完成

| 方法 | 路径 | 身份 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/ui-executions/{id}/commands` | 用户 `test:execute` | 下发 `pause/resume/cancel` |
| `POST` | `/ui-executions/{id}/patch-requests` | 用户 `test:execute` | 在 paused/waiting_user 下发当前运行修补 |
| `POST` | `/ui-executions/{id}/commands/{command_id}/ack` | 设备 | 确认或拒绝命令 |
| `POST` | `/ui-executions/{id}/complete` | 设备 | 幂等提交终态和步骤汇总 |

命令创建使用 `client_request_id` 幂等。WSS `command.available` 仅作为轻量提醒；Desktop 通过 renew 响应取得权威待执行命令。queued/assigned 执行的 cancel 由服务端直接完成。

complete 的 `final_client_sequence` 必须等于服务端已接收序号，步骤计数必须与执行快照一致。存在人工介入或运行修补时提交 `passed` 返回 `409 assisted_status_required`，客户端必须提交 `assisted`。完全相同的终态重试返回 `idempotent_replay=true`，不同终态或汇总返回冲突。complete 时没有产物会把 `delivery_status=pending` 收敛为 `complete`；仍存在未完成上传会把交付状态收敛为 `failed` 并设置 `attention_reason=artifact_delivery_failed`，但不会改写真实执行终态。

## 6. 状态与统一执行读取

```text
queued -> claimed -> launching -> running
running <-> paused
running <-> waiting_user
active -> passed | assisted | failed | cancelled | lost
claimed/launching -> queued  (lease release)
```

UI 执行同步加入公共执行记录：

- `GET /api/v1/execution-records?project_id={id}&execution_type=ui`
- `GET /api/v1/execution-records/ui/{internal_execution_id}?project_id={id}`

运行状态与产物交付状态分离：`delivery_status=failed` 不会覆盖 `passed/assisted/failed` 等执行终态。

## 7. 产物交付

| 方法 | 路径 | 身份 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/ui-executions/{id}/artifacts/presign` | 设备 + lease | 创建幂等上传会话与预签名 PUT |
| `POST` | `/ui-executions/{id}/artifacts/finalize` | 设备 + lease | HEAD 校验后写统一产物元数据 |
| `GET` | `/ui-executions/{id}/artifacts` | 用户 `report:view` | 列出产物与交付状态 |
| `GET` | `/ui-executions/{id}/artifacts/{artifact_ref}/url` | 用户 `report:view` | 获取短时预签名 GET |
| `DELETE` | `/ui-executions/{id}/artifacts/{artifact_ref}` | 项目创建者或管理员 | 删除对象与元数据 |

presign 请求包含 lease、`client_request_id/step_id/section/content_type/original_filename/size_bytes/sha256`。响应返回不透明 `artifact_ref/upload_id`、PUT URL、必需 headers、过期时间和最大大小。finalize 只接收 lease、`upload_id` 与 `artifact_ref`，服务端通过对象存储 HEAD 对大小、媒体类型和 `x-amz-meta-sha256` 做一致性校验；伪造或过期上传不会创建产物元数据。

上传会话使用 `client_request_id` 幂等；重复 finalize 返回同一产物并标记重放。定时清理器删除过期未完成会话对应的孤儿对象。`delivery_status` 在 `pending/uploading/complete/failed` 中独立变化，不覆盖执行终态。Desktop 在终态产物自动重试达到上限后可以放弃该次上传、保留本地文件并调用 complete；平台以 `delivery_status=failed` 呈现产物交付失败，同时释放执行 lease。

## 8. 本地运行导入

`POST /ui-executions/import-local-run?project_id={id}` 只导入已结束运行，成功返回 `201`。请求必须引用项目内 `case_id/version/environment_id`，携带 `client_request_id`、终态、汇总、开始/结束时间、可选设备和唯一的 `(step_id, attempt)` 结果。失败终态必须有 `primary_error`，assisted 汇总必须使用 `status=assisted`。相同请求幂等重放，不同内容使用同一键返回冲突。

## 9. 主要业务错误

| HTTP | `detail.error` | 含义 |
| --- | --- | --- |
| `403` | `device_identity_mismatch` | body 设备 ID 与 token 身份不同 |
| `403` | `device_project_not_bound` | 设备未有效绑定执行项目 |
| `403` | `lease_device_mismatch` | 执行已由其他设备领取 |
| `409` | `execution_claim_conflict` | 状态、指定设备或并发领取冲突 |
| `409` | `runtime_incompatible` | Desktop、DSL 或 IPC 版本不兼容 |
| `409` | `lease_expired` | lease 已过期，执行已转 lost |
| `409` | `lease_version_conflict` | lease ID/version 不匹配 |
| `409` | `event_sequence_conflict` | 事件序号不连续或幂等内容冲突 |
| `409` | `command_state_conflict` | 当前状态不允许暂停、恢复、取消或平台修补 |
| `409` | `patch_request_stale` | 平台提交的 before 已不是当前生效值 |
| `409` | `patch_request_noop` | after 与当前生效值相同 |
| `409` | `patch_request_not_delivered` | Desktop 尚未通过权威 REST 取得修补命令 |
| `409` | `patch_request_not_applied` | Desktop 在写入关联运行时补丁前确认了修补命令 |
| `409` | `patch_request_payload_conflict` | Desktop 上报内容与平台修补命令不一致 |
| `409` | `assisted_status_required` | 存在人工介入却提交 passed |
| `409` | `artifact_upload_conflict` | 同一上传幂等键承载不同元数据 |
| `409` | `artifact_upload_expired` | 上传会话已过期或不可完成 |
| `409` | `artifact_metadata_mismatch` | HEAD 结果与声明的大小、类型或 SHA 不一致 |
| `413` | `desktop_payload_too_large` | 批次或事件超过配置上限 |
| `413` | `patch_request_too_large` | 平台修补命令超过运行时 payload 上限 |
| `422` | `patch_request_invalid` | 修补后的候选步骤不符合 ui-case-v1 |
