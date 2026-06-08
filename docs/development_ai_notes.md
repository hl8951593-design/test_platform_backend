# AI 数据源接入开发记录

## 模块职责

AI 数据源模块负责把 DeepSeek 接入平台后端，为后续接口用例生成、失败原因分析、断言推荐、报告摘要等 AI 功能提供统一调用入口。

当前阶段只做基础接入，不绑定具体业务逻辑。

## 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| Config | `app/core/config.py` | DeepSeek key、base_url、默认模型和超时配置 |
| Schema | `app/schemas/ai.py` | AI 请求和响应结构 |
| Service | `app/services/ai_service.py` | DeepSeek Chat Completions 调用封装 |
| API Router | `app/api/v1/routers/ai.py` | AI 数据源配置查询和聊天补全接口 |
| API Aggregator | `app/api/v1/api.py` | 注册 `/api/v1/ai` 路由 |
| API Doc | `docs/api_ai.md` | AI 数据源接口文档 |
| Technical Guide | `docs/ai_deepseek_technical_guide.md` | DeepSeek 后续 AI 能力开发指南 |

## 配置规则

真实 key 只允许写入本地 `.env`：

```text
DEEPSEEK_API_KEY=<your-deepseek-api-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=60
```

`.env.example` 只提供占位符，不能写入真实 key。

## 技术选型

DeepSeek 使用 OpenAI 兼容接口，本项目当前选择 `httpx` 直接调用，而不是引入 OpenAI SDK。

原因：

- 项目已有 `httpx` 依赖，测试用例执行器也使用 `httpx`。
- 依赖更少，后续部署更简单。
- 调用过程可控，便于统一错误处理、日志脱敏和供应商切换。
- 后续可以在 `AIService` 内扩展 provider，而不影响业务层。

## 业务流程

```text
POST /api/v1/ai/chat
-> 校验当前登录用户
-> 校验 DeepSeek API Key 是否配置
-> 组装 OpenAI 兼容 chat/completions 请求
-> 通过 httpx 请求 DeepSeek
-> 提取 choices[0].message.content、usage、finish_reason
-> 返回统一 success 结构
```

## 权限规则

当前 AI 数据源接口要求登录访问。后续如果 AI 功能读取项目、环境、用例、执行记录等数据，必须按对应项目权限校验。

## 错误处理

| 场景 | 处理 |
| --- | --- |
| DeepSeek API Key 未配置 | 返回 500，提示配置缺失 |
| DeepSeek HTTP 状态异常 | 返回 502，并提取上游 error.message |
| 网络错误或超时 | 返回 503 |

## 已实现

- DeepSeek 基础配置读取。
- `/api/v1/ai/provider` 数据源配置查询。
- `/api/v1/ai/chat` 对话补全。
- 文本模式和 JSON 模式。
- 可选传入 `thinking` 和 `reasoning_effort`。
- 上游错误转换为后端统一异常。

## 待扩展

- AI 调用日志与 token 用量记录。
- 敏感信息脱敏。
- 项目级 AI 功能权限控制。
- AI 生成测试用例草稿。
- AI 分析执行失败原因。
- AI 推荐断言和提取器。
- 对话前缀续写和 FIM 补全。

## WebSocket 用例 AI 能力

WebSocket AI 生成与扩写由 `app/services/ai_websocket_test_case_service.py` 独立实现，避免 HTTP 提示词中的 method、query、body 和状态码概念污染 WebSocket 用例。

```text
WebSocket 文档或源用例
-> WebSocket 专用 system prompt
-> DeepSeek JSON Output
-> 过滤 HTTP 字段和非法断言
-> 自动校正 receive_count
-> WebSocketTestCaseCreateRequest 校验
-> 返回用例草稿
```

扩写类型包括握手鉴权、子协议、消息顺序、消息字段异常、畸形消息、推送数量、超时、连接关闭和业务会话变体。
