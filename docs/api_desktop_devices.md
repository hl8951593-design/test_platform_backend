# TestAuto Desktop 设备控制面 API

> 状态：已实现（设备控制面第一批）
>
> 最近核验：2026-07-17
>
> Alembic revision：`0046_desktop_devices`
>
> 客户端基线：PyQt6 TestAuto Desktop `0.3.0-dev`

本文档描述已实现的 Desktop 设备控制面。UI 用例、执行、claim/lease、事件补传和产物上传见
[UI 用例 API](api_ui_test_cases.md) 与 [UI 执行 API](api_ui_executions.md)。

## 1. 接口边界

Desktop 保持出站连接，不需要开放本机入站端口：

```text
PyQt6 Desktop
  -> HTTPS REST：注册、刷新、列表、设置、项目绑定、心跳、状态校准
  -> WSS Control：轻量通知、ping/pong、提示 REST resync

FastAPI
  -> MySQL：设备身份、凭据哈希、项目绑定、降频心跳快照
  -> Redis：短 TTL 在线态、跨进程 WSS pub/sub
```

平台不保存浏览器可执行文件路径、Profile 目录、缓存目录、QSettings 或 Desktop IPC 内容。Desktop 只上报脱敏的版本、
协议和能力摘要。

所有 REST 路径以 `/api/v1/desktop` 开头，响应继续使用平台统一 envelope：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

请求和响应字段使用 `snake_case`。请求兼容本文列出的部分 `camelCase` alias，但 Desktop Adapter 应统一发送
`snake_case`。

## 2. 两类身份

### 2.1 用户身份

以下接口使用平台登录返回的用户 access token：

```http
Authorization: Bearer <user_access_token>
```

- 获取 runtime policy；
- 注册或重新注册设备；
- 查看、重命名、调整或撤销自己的设备；
- 把自己的设备绑定到有权访问的项目。

### 2.2 设备身份

设备注册成功后返回独立的短期 access token 和可轮换 refresh token。设备 access JWT 的
`type=desktop_device_access`，不能当作用户 token 调用项目或用例管理接口；用户 JWT 也不能调用 heartbeat 或 WSS
控制通道。

设备 refresh token 是不透明值：

```text
dcred_<credential-id>.<random-secret>
```

后端只保存随机 secret 的 SHA-256 哈希，不保存可还原 refresh token。每次 refresh 都返回新 token，旧 token 立即失效。
同一用户用相同 `installation_id` 重新注册时复用 `device_id`、轮换设备凭据并使旧设备 access/refresh token 失效。

设备 access token 鉴权在一次数据库读取中联结 credential、device 和 owner，但仍逐项校验凭据撤销/过期、设备 public ID/owner/active 状态及 owner active 状态；该优化不缓存鉴权结果，因此撤销语义不变。

客户端应把 refresh token 保存到 Windows Credential Manager 或等价安全存储，不得写入普通日志、SQLite 明文字段或
QSettings。

## 3. 当前接口清单

| 方法 | 路径 | 身份 | 作用 |
| --- | --- | --- | --- |
| `GET` | `/runtime-policy` | 用户 | 获取最低版本、协议和心跳策略 |
| `POST` | `/devices/register` | 用户 | 注册或重新注册当前安装实例 |
| `POST` | `/devices/token/refresh` | refresh token | 单次轮换设备凭据 |
| `GET` | `/devices` | 用户 | 查询自己的设备 |
| `GET` | `/devices?project_id={id}` | 用户 + 项目访问 | 查询已绑定该项目的活动设备 |
| `GET` | `/devices/{device_id}` | 设备所有者或管理员 | 查询设备详情 |
| `PATCH` | `/devices/{device_id}` | 设备所有者或管理员 | 修改名称、接单开关和并发上限 |
| `PUT` | `/devices/{device_id}/projects/{project_id}` | 设备所有者或管理员 + 项目访问 | 创建或更新项目绑定 |
| `POST` | `/devices/{device_id}/heartbeat` | 设备 | 上报在线态、能力和本地负载摘要 |
| `DELETE` | `/devices/{device_id}` | 设备所有者或管理员 | 撤销设备和全部活动凭据 |
| `WS` | `/devices/{device_id}/control` | 设备 | 建立轻量控制通知通道 |

## 4. Runtime policy

### `GET /api/v1/desktop/runtime-policy`

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "min_desktop_version": "0.1.0",
    "supported_dsl_versions": ["ui-case-v1"],
    "supported_ipc_versions": ["desktop-ipc-v1"],
    "heartbeat_interval_seconds": 20,
    "offline_after_seconds": 75,
    "max_concurrency": 4,
    "control_transport": "wss_rest"
  }
}
```

`control_transport=wss_rest` 表示 WSS 只负责轻量通知，断线重连和权威状态都通过 REST 校准。

## 5. 注册设备

### `POST /api/v1/desktop/devices/register`

请求示例：

```json
{
  "installation_id": "10c814c2-c1cb-4306-93a2-b47c16183ad7",
  "name": "DESKTOP-QA-01",
  "desktop_version": "0.1.0",
  "os_name": "Windows",
  "os_version": "11 24H2",
  "architecture": "x86_64",
  "supported_protocols": {
    "dsl": ["ui-case-v1"],
    "ipc": ["desktop-ipc-v1"]
  },
  "capabilities": {
    "browsers": ["chromium", "chrome", "edge"],
    "playwright_installed": true
  },
  "device_public_key": null
}
```

`installation_id` 必须是 Desktop 首次启动生成并持久化的随机 ID，不得使用 MAC、磁盘序列号或硬件指纹。后端保存
`HMAC(owner_id, installation_id)`，不会返回原始值。

成功状态为 `201`。响应中的 credential 只在本次注册响应出现：

```json
{
  "code": 0,
  "message": "desktop_device_registered",
  "data": {
    "device": {
      "device_id": "dev_9_1Nq4uZpN5QmSN1qT2vYb0R",
      "owner_id": 12,
      "name": "DESKTOP-QA-01",
      "registration_status": "active",
      "online": false,
      "accepting_jobs": true,
      "concurrency_limit": 1,
      "desktop_version": "0.1.0",
      "os_name": "Windows",
      "os_version": "11 24H2",
      "architecture": "x86_64",
      "supported_protocols": {
        "dsl": ["ui-case-v1"],
        "ipc": ["desktop-ipc-v1"]
      },
      "capabilities": {
        "browsers": ["chromium", "chrome", "edge"],
        "playwright_installed": true
      },
      "runtime_state": {},
      "last_heartbeat_at": null,
      "registered_at": "2026-07-16 15:30:00",
      "revoked_at": null,
      "project_bindings": []
    },
    "credential": {
      "access_token": "<device-access-jwt>",
      "refresh_token": "<opaque-device-refresh-token>",
      "token_type": "bearer",
      "access_expires_in": 900,
      "refresh_expires_at": "2026-10-14 15:30:00"
    }
  }
}
```

## 6. 刷新设备凭据

### `POST /api/v1/desktop/devices/token/refresh`

该接口不使用用户 Authorization header，请求体直接提交当前设备 refresh token：

```json
{
  "refresh_token": "dcred_xxx.yyy"
}
```

成功响应 `data` 与注册响应中的 `credential` 相同。轮换是单次消费语义；旧 token、过期 token、已撤销 credential、
已撤销设备或已停用用户都返回 `401 desktop_device_refresh_token_invalid`。

## 7. 查询和管理设备

### 查询列表和详情

```http
GET /api/v1/desktop/devices
GET /api/v1/desktop/devices?project_id=10
GET /api/v1/desktop/devices/dev_xxx
```

不带 `project_id` 时只返回当前用户自己的设备，包括已撤销设备。带 `project_id` 时先校验项目访问权，再返回该项目已启用
绑定的活动设备。设备 `online` 优先读取 Redis TTL；Redis 不可用时按最近 MySQL 心跳快照和
`offline_after_seconds` 退化判断。

### 修改设备

```http
PATCH /api/v1/desktop/devices/dev_xxx
Content-Type: application/json

{
  "name": "DESKTOP-QA-PRIMARY",
  "accepting_jobs": true,
  "concurrency_limit": 2
}
```

字段均可选。`concurrency_limit` 范围为 `1..runtime_policy.max_concurrency`。

### 项目绑定

设备默认不属于任何项目，也不会因为用户能访问项目就自动接收该项目任务：

```http
PUT /api/v1/desktop/devices/dev_xxx/projects/10
Content-Type: application/json

{
  "enabled": true,
  "accepting_jobs": true,
  "concurrency_limit": 1
}
```

重复调用是 upsert。后续 UI 执行任务只有在设备和项目绑定均启用时才能进入该设备的候选集合。

### 撤销设备

```http
DELETE /api/v1/desktop/devices/dev_xxx
```

撤销后：

- `registration_status=revoked`；
- `accepting_jobs=false`；
- 全部活动设备 credential 立即撤销；
- Redis presence 被删除；
- 旧 access token、refresh token 和新 WSS 握手全部失效。

重新启用必须由用户使用相同 installation ID 再次执行注册，后端会返回新凭据。

## 8. Heartbeat

### `POST /api/v1/desktop/devices/{device_id}/heartbeat`

必须使用与路径 `device_id` 一致的设备 access token：

```json
{
  "desktop_version": "0.1.0",
  "supported_protocols": {
    "dsl": ["ui-case-v1"],
    "ipc": ["desktop-ipc-v1"]
  },
  "capabilities": {
    "browsers": ["chromium"],
    "playwright_installed": true
  },
  "active_execution_ids": [],
  "local_outbox_events": 0,
  "local_outbox_artifacts": 0,
  "current_load": 0
}
```

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "device_id": "dev_xxx",
    "server_time": "2026-07-16 15:32:00",
    "online": true,
    "runtime_compatible": true,
    "accepting_jobs": true,
    "heartbeat_interval_seconds": 20,
    "commands_cursor": null
  }
}
```

每次 heartbeat 都刷新 Redis TTL。MySQL 只在元数据/运行摘要变化或达到
`DESKTOP_HEARTBEAT_PERSIST_SECONDS` 时写入，避免每个 ping 更新热行。版本低于 `min_desktop_version` 时
`runtime_compatible=false` 且服务端返回 `accepting_jobs=false`。

## 9. WSS Control

连接地址：

```text
wss://<host>/api/v1/desktop/devices/{device_id}/control
```

握手必须携带：

```http
Authorization: Bearer <device_access_token>
```

缺 token、用户 token、过期/撤销 token 分别关闭为 `4401`；token 与路径设备不一致关闭为 `4403`。

连接成功后服务端发送：

```json
{
  "schema_version": "desktop-control-v1",
  "type": "control.ready",
  "message_id": "msg_xxx",
  "device_id": "dev_xxx",
  "server_time": "2026-07-16T15:32:00.000Z"
}
```

当前客户端上行消息：

```json
{"type":"control.ping","message_id":"client_msg_1"}
```

服务端响应 `control.pong`，并通过 `reply_to` 回传请求 message ID。客户端断线重连后可以发送：

```json
{"type":"control.resync","message_id":"client_msg_2"}
```

服务端返回 `control.resync_required` 和 `authoritative_transport=rest`。这不是把历史状态从 WSS 重放给客户端；Desktop
必须重新调用 REST 列表和详情接口校准状态。Redis pub/sub 用于多进程通知 fan-out，WSS 内存连接本身不是权威状态源。

服务端还会发送 `execution.available` 和 `command.available`，两者只携带执行/命令身份与 envelope，不携带 DSL、密钥或权威状态。Desktop 收到通知、heartbeat 成功或 WSS 重连后，通过设备 token 调用 `GET /api/v1/ui-executions/available?limit=20` 重新拉取可领取队列，并通过 lease renew 拉取命令；因此通知丢失不会破坏事实一致性。

## 10. 稳定错误码

| HTTP/WSS | detail/reason | 含义 |
| --- | --- | --- |
| `401` | `desktop_device_access_token_required` | heartbeat 缺设备 token |
| `401` | `desktop_device_access_token_invalid` | access token 非法、过期或已撤销 |
| `401` | `desktop_device_refresh_token_invalid` | refresh token 非法、过期、旧值或已撤销 |
| `403` | `desktop_device_access_denied` | 当前用户不是设备所有者或管理员 |
| `403` | `desktop_device_token_device_mismatch` | token 设备与路径设备不一致 |
| `404` | `desktop_device_not_found` | 设备不存在 |
| `422` | `desktop_device_concurrency_limit_exceeded` | 并发上限超过 runtime policy |
| `4401` | token required/invalid | WSS 设备鉴权失败 |
| `4403` | token device mismatch | WSS 设备身份与路径不一致 |

项目不存在或无项目访问权时继续使用平台现有 `PermissionService` 错误语义。

## 11. 配置

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | presence 与 WSS pub/sub |
| `DESKTOP_DEVICE_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | 设备 access token 有效期 |
| `DESKTOP_DEVICE_REFRESH_TOKEN_EXPIRE_DAYS` | `90` | refresh token 有效期及每次轮换续期 |
| `DESKTOP_HEARTBEAT_INTERVAL_SECONDS` | `20` | 客户端目标心跳间隔 |
| `DESKTOP_HEARTBEAT_PERSIST_SECONDS` | `60` | 无变化 heartbeat 的 MySQL 最短持久化间隔 |
| `DESKTOP_DEVICE_OFFLINE_AFTER_SECONDS` | `75` | Redis TTL 与离线判断阈值 |
| `DESKTOP_REDIS_RETRY_SECONDS` | `5` | Redis 故障重连间隔 |
| `DESKTOP_MIN_VERSION` | `0.1.0` | 最低兼容 Desktop 版本 |
| `DESKTOP_MAX_CONCURRENCY` | `4` | 设备/项目绑定最大并发 |
| `DESKTOP_SUPPORTED_DSL_VERSIONS` | `["ui-case-v1"]` | 后端支持的 UI DSL |
| `DESKTOP_SUPPORTED_IPC_VERSIONS` | `["desktop-ipc-v1"]` | 后端认可的 Desktop IPC 版本 |

Redis 故障不会阻止 API 进程启动或设备注册，在线态会退化为 MySQL 心跳快照；生产发布门禁仍要求验证 Redis 恢复和多
Uvicorn worker 的 pub/sub fan-out。

## 12. 关联执行能力与部署门禁

`/ui-executions` 用户 queue/facets/详情、设备 `/available` 恢复、claim/lease、event batch、runtime patch、commands、complete、SSE、本地运行导入、产物交付和完整统一投影均已实现。发布前仍需在目标部署环境完成真实 Redis 多 Uvicorn worker fan-out/恢复、MinIO 和 Windows Desktop 的端到端验证；该外部门禁不改变本文 REST/WSS 契约。
