# WebSocket 测试用例接口技术文档

WebSocket 测试用例与 HTTP 测试用例完全独立：使用 `/api/v1/websocket-test-cases` 接口前缀、独立代码模块、独立数据表和独立执行记录；仅复用项目环境、环境变量和项目权限。

## 数据表

| 表名 | 用途 |
| --- | --- |
| `websocket_test_cases` | 保存 WebSocket 会话用例 |
| `websocket_test_case_environments` | 保存用例与多个环境的关联 |
| `websocket_test_case_executions` | 保存每次 WebSocket 会话执行记录 |

数据库迁移：`migrations/versions/0009_create_websocket_test_case_tables.py`。

## 接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/websocket-test-cases?project_id={project_id}` | `case:view` | 查询用例 |
| POST | `/websocket-test-cases?project_id={project_id}` | `case:manage` | 新增用例 |
| PUT | `/websocket-test-cases/{id}?project_id={project_id}` | `case:manage` | 更新用例 |
| POST | `/websocket-test-cases/{id}/execute?project_id={project_id}` | `test:execute` | 执行已保存用例 |
| POST | `/websocket-test-cases/execute-unsaved?project_id={project_id}` | `test:execute` | 执行未保存用例 |
| POST | `/websocket-test-cases/batch-execute?project_id={project_id}` | `test:execute` | 按顺序批量执行 |

## 配置示例

```json
{
  "name": "连接并校验欢迎消息",
  "environment_id": 1,
  "path": "/ws/chat/{{room_id}}",
  "headers": {"Authorization": "Bearer {{token}}"},
  "subprotocols": ["json"],
  "messages": [
    {"type": "json", "data": {"action": "join", "user_id": "{{user_id}}"}}
  ],
  "receive_count": 1,
  "connect_timeout_ms": 10000,
  "receive_timeout_ms": 10000,
  "assertions": [
    {"type": "message_count", "expected": 1},
    {"type": "message_json_equals", "message_index": 0, "path": "event", "expected": "welcome"}
  ],
  "extractors": [
    {"name": "connection_id", "message_index": 0, "path": "connection_id"}
  ]
}
```

`messages[].type` 支持 `text` 和 `json`。执行器按顺序发送消息，再接收 `receive_count` 条消息。

## URL 与变量

- 完整 `ws://` 或 `wss://` URL 可以不绑定环境。
- 相对路径会复用环境 `base_url`；`http://` 转为 `ws://`，`https://` 转为 `wss://`。
- path、headers、subprotocols 和发送消息支持 `{{变量名}}` 替换。

## 断言与提取

| 类型 | 说明 |
| --- | --- |
| `message_count` | 校验接收消息数量 |
| `message_contains` | 校验指定消息文本包含预期内容 |
| `message_json_equals` | 校验指定消息 JSON 路径等于预期值 |

`message_index` 从 `0` 开始，JSON 路径使用点分格式。提取器会从指定响应消息的 JSON 路径读取值，供后续批量用例使用。

## 执行结果

执行状态为 `passed`、`failed` 或 `error`。独立执行记录包含：

- `session_snapshot`：连接 URL、headers、subprotocols、发送消息和超时配置
- `response_snapshot`：发送消息、接收消息及协商后的 subprotocol
- `assertion_results`、`error_message`、`duration_ms`

## 实现位置

| 层 | 文件 |
| --- | --- |
| Router | `app/api/v1/routers/websocket_test_cases.py` |
| Schema | `app/schemas/websocket_test_case.py` |
| Model | `app/models/websocket_test_case.py` |
| Repository | `app/repositories/websocket_test_case_repository.py` |
| Service / Executor | `app/services/websocket_test_case_service.py` |
| 执行验证 | `scripts/test_websocket_test_case_execution.py` |

## 测试用 WebSocket Mock 服务

项目提供独立的 WebSocket mock 服务，不会挂载到业务 API：

```powershell
.\.venv\Scripts\python.exe scripts\websocket_mock_server.py
```

默认监听 `127.0.0.1:18081`，可指定地址、端口和日志级别：

```powershell
.\.venv\Scripts\python.exe scripts\websocket_mock_server.py --host 127.0.0.1 --port 19090 --log-level debug
```

| WebSocket 地址 | 场景 |
| --- | --- |
| `/` | Echo 根路径别名，便于仅使用环境 Base URL 建立连接 |
| `/ws/echo` | 原样返回客户端发送的文本或二进制消息 |
| `/ws/session/{user_id}` | 接收一条消息，返回欢迎 JSON 和 `done` 文本；回传鉴权 header 并支持 `json` 子协议 |
| `/ws/sequence/{count}` | 连续推送指定数量的 JSON 消息 |
| `/ws/auth` | 仅接受 `Authorization: Bearer mock-token`，用于测试握手鉴权成功和拒绝 |
| `/ws/close/{code}` | 连接后使用指定关闭码主动关闭 |

例如连接 echo 服务：

```text
ws://127.0.0.1:18081/ws/echo
```

真实 mock 集成验证：

```powershell
.\.venv\Scripts\python.exe scripts\test_websocket_test_case_execution.py
```

测试脚本会自动选择空闲端口、启动 mock 服务、执行 WebSocket 用例并关闭服务。

## AI 生成与扩写

WebSocket AI 接口与 HTTP AI 用例接口独立，使用专用 WebSocket 提示词和输出校验：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/ai/websocket-test-cases/generate?project_id={project_id}&environment_id={environment_id}` | 根据 WebSocket 协议文档、连接地址和消息示例生成用例草稿 |
| POST | `/ai/websocket-test-cases/{test_case_id}/expand?project_id={project_id}&environment_id={environment_id}` | 基于已保存 WebSocket 用例扩写会话变体 |

生成请求示例：

```json
{
  "websocket_text": "连接 /ws/chat，使用 json 子协议。发送 join 消息后服务端返回 welcome 和 user_joined 事件。",
  "generate_count": 3,
  "include_assertions": true,
  "extra_requirements": "覆盖鉴权、消息顺序和服务端连续推送"
}
```

扩写请求示例：

```json
{
  "requirement": "扩写握手失败、消息乱序和接收超时场景",
  "generate_count": 5,
  "expansion_types": [
    "handshake_auth",
    "subprotocol",
    "message_sequence",
    "timeout",
    "connection_close"
  ],
  "include_assertions": true
}
```

WebSocket AI 提示词重点：

- 围绕握手、鉴权 headers、subprotocol 协商和长连接会话生成。
- 关注消息类型、消息顺序、重复消息、缺少前置消息、连续推送、超时和连接关闭。
- 仅生成 `message_count`、`message_contains`、`message_json_equals` 断言。
- 生成非法 JSON 场景时使用 `text` 消息保存原始错误文本。
- 禁止生成 HTTP 用例的 `method`、`query_params`、`body_type`、`body` 和 `status_code`。
- AI 结果经过 `WebSocketTestCaseCreateRequest` 校验，只返回草稿，不直接保存。

AI 实现位置：`app/services/ai_websocket_test_case_service.py`。

## 长连接调试会话

`execute-unsaved` 和已保存用例执行属于自动化执行：连接、发送、接收指定数量消息、断言、关闭。前端“调试”功能需要改用长连接调试会话接口。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/websocket-test-cases/debug-sessions?project_id={project_id}` | 建立目标 WebSocket 长连接并返回 `session_id` |
| GET | `/websocket-test-cases/debug-sessions/{session_id}?project_id={project_id}&after_sequence={sequence}` | 查询状态和增量消息 |
| POST | `/websocket-test-cases/debug-sessions/{session_id}/messages?project_id={project_id}` | 通过现有连接发送文本或 JSON 消息 |
| POST | `/websocket-test-cases/debug-sessions/{session_id}/ping?project_id={project_id}` | 发送 WebSocket ping 心跳 |
| DELETE | `/websocket-test-cases/debug-sessions/{session_id}/messages?project_id={project_id}` | 清空当前会话的服务端消息日志，保持连接 |
| DELETE | `/websocket-test-cases/debug-sessions/{session_id}?project_id={project_id}` | 主动断开连接 |

创建连接：

```json
{
  "environment_id": 1,
  "path": "/ws/echo",
  "headers": {
    "Authorization": "Bearer {{token}}"
  },
  "subprotocols": ["json"],
  "connect_timeout_ms": 10000,
  "idle_timeout_seconds": 1800
}
```

发送消息：

```json
{
  "type": "json",
  "data": {
    "event": "join",
    "room_id": "100"
  }
}
```

消息日志包含递增的 `sequence`、`direction`、`type`、`data`、解析后的 `json` 和时间。会话响应中的 `latest_sequence` 表示当前最新序号；前端保存该序号，并通过 `after_sequence` 增量轮询。清空日志不会重置序号，连接仍可继续收发消息。

推荐前端交互：

```text
连接 -> 保存 session_id -> 定时增量查询消息 -> 多次发送消息/心跳或清空日志 -> 主动断开
```

后端会持续持有目标连接，不受单次 HTTP 请求结束影响。会话仅允许创建它的用户访问，要求 `test:execute` 权限；默认空闲 30 分钟后自动断开，单会话最多保留最近 5000 条消息。

前端在编辑器组件卸载、切换用例或用户点击断开时，应调用会话 `DELETE` 接口。页面关闭场景可使用支持 `keepalive` 的请求尽力发送断开操作；如果请求未送达，后端仍会在空闲超时后自动清理连接。

当前调试会话保存在应用进程内存中。使用多个 Uvicorn Worker 或多实例部署时必须配置粘性路由，后续生产化可将会话路由和消息日志迁移到 Redis，并由专用连接 Worker 持有目标连接。
