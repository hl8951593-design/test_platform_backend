# AI 数据源接入开发记录

## 模块职责

AI 数据源模块负责把 DeepSeek 接入平台后端，并通过正式 AI skill runtime 承载 HTTP/WebSocket 用例生成与扩写、场景组合、浏览器采集分析等业务能力。

当前阶段已经不是单纯数据源接入：基础 `/ai/chat` 仍保留，业务能力统一向 skill 包、runtime adapter 和可观测 run/event 语义收敛。

## 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| Config | `app/core/config.py` | DeepSeek key、base_url、默认模型和超时配置 |
| Schema | `app/schemas/ai.py` | AI 请求和响应结构 |
| Service | `app/services/ai_service.py` | DeepSeek Chat Completions 调用封装 |
| Skill Runtime | `app/ai_skills/base.py` | AI skill 调用、JSON 解析修复、模型修复兜底和流式事件写入 |
| Skill Packages | `app/ai_skills/packages/` | `SKILL.md`、`manifest.json`、prompt 和后续可复用资源 |
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
- `AIService.chat_stream` 支持 DeepSeek SSE 增量读取，当前用于可观测 AI Skill Run 的 `model.delta` 事件。
- HTTP/WebSocket 测试用例生成与扩写已迁移到正式 skill 包。
- `scenario-composer` 已支持候选用例样本读取、场景草稿生成和自验证修复。
- AI Skill Run 支持创建 run、查询 run、SSE 订阅事件、敏感 payload 脱敏和创建者/管理员访问控制。
- Skill Runtime 支持本地 JSON 兼容修复和一次模型 JSON 修复兜底。

## 待扩展

- 持久化 AI 调用日志、模型版本、token 用量、耗时和费用。
- 项目级 AI 功能权限控制。
- AI 分析执行失败原因。
- AI 推荐断言和提取器。
- 对话前缀续写和 FIM 补全。

## WebSocket 用例 AI 能力

HTTP 与 WebSocket 的 AI 生成、扩写已经改造为正式 skill 包：

```text
app/ai_skills/packages/http-test-case/
app/ai_skills/packages/websocket-test-case/
app/ai_skills/packages/scenario-composer/
```

每个 skill 包包含 `SKILL.md` 元数据和 `prompts/` 资源。后端通过 `app/ai_skills/registry.py` 注册 skill，通过 `AISkillRunner` 统一调用 AI 数据源。业务 service 只负责权限、环境、源用例等上下文准备。

WebSocket skill 独立维护提示词和输出归一化规则，避免 HTTP 提示词中的 method、query、body 和状态码概念污染 WebSocket 用例。

```text
WebSocket 文档或源用例
-> websocket-test-case skill
-> WebSocket 专用 system prompt 资源
-> DeepSeek JSON Output
-> 过滤 HTTP 字段和非法断言
-> 自动校正 receive_count
-> WebSocketTestCaseCreateRequest 校验
-> 返回用例草稿
```

扩写类型包括握手鉴权、子协议、消息顺序、消息字段异常、畸形消息、推送数量、超时、连接关闭和业务会话变体。

## Skill 架构约定

AI skill 分为三层：

| 层级 | 位置 | 职责 |
| --- | --- | --- |
| Skill 包 | `app/ai_skills/packages/{skill_id}/` | 保存 `SKILL.md`、`manifest.json`、prompt 和后续可复用资源 |
| Runtime adapter | `app/ai_skills/{skill_module}.py` | 把业务上下文转换成 AI 请求，解析和归一化模型输出 |
| Business service | `app/services/*_service.py`、`app/services/ai_skill_service.py` | 权限校验、查询项目资源、统一 list/run 分发 |

当前内置 skill：

| Skill ID | 说明 |
| --- | --- |
| `http-test-case` | HTTP 测试用例生成和扩写 |
| `websocket-test-case` | WebSocket 测试用例生成和扩写 |
| `scenario-composer` | 从候选测试用例、请求响应样本和业务目标智能组合场景草稿 |

统一发现与运行接口：

```text
GET  /api/v1/ai/skills
GET  /api/v1/ai/skills/{skill_id}
POST /api/v1/ai/skills/{skill_id}/run
```

可观测异步运行接口：

```text
POST /api/v1/ai/skills/{skill_id}/runs
GET  /api/v1/ai/skill-runs/{run_id}
GET  /api/v1/ai/skill-runs/{run_id}/events
```

`AI Skill Run` 是平台级可观测执行层，不绑定具体 agent 实现。当前 skill、后续平台 agent、
更复杂的多步编排都应复用同一套 run/event/trace 语义。事件只记录可展示的执行轨迹、工具调用、
模型流式输出和校验摘要，不暴露模型原始 Chain of Thought。

事件 payload 必须脱敏，run 默认只允许创建者和管理员读取。

旧业务接口继续保留兼容，内部也走 skill runtime。

## 新增 Skill 流程

1. 在 `app/ai_skills/packages/{skill_id}/` 新建正式 skill 包。
2. `SKILL.md` frontmatter 只写 `name` 和 `description`，正文写 agent 使用说明。
3. `manifest.json` 写版本、领域、协议、operation、输入输出 schema 和资源路径。
4. 把 prompt、模板或参考资料放到包内资源目录，例如 `prompts/`。
5. 新增 `app/ai_skills/{skill_module}.py` runtime adapter，并调用 `register_ai_skill(...)` 注册。
6. 如需通用 `/ai/skills/{skill_id}/run` 支持，在 `AISkillService.run_skill` 中添加该 skill 的业务分发。
7. 补测试：manifest 可发现、JSON Schema 可返回、统一 run 可分发、旧业务接口行为不变。

设计原则：

- service 不写长 prompt，只准备业务上下文。
- prompt 和 agent 可读说明必须放在正式 skill 包里。
- adapter 只做 AI 请求构造、响应解析、归一化和 schema 校验。
- 每个 operation 都必须声明输入输出 schema，方便前端和 agent 自动编排。
- 新增 skill 时不要影响已有 skill 的 prompt、响应结构和权限边界。
- 需要 JSON 输出的 prompt 必须声明完整根对象、字段名不可拆行、字符串中不得输出真实控制字符，并给出可直接解析的 JSON 样例。
- HTTP 用例断言必须使用 `expected` 字段；禁止让模型输出 `value`、`expect` 或 `actual` 作为断言期望值。
- Runtime adapter 不信任模型输出。所有结果必须经过 `load_model_json`、业务归一化和 Pydantic Schema 校验后才能返回前端。
- 本地 JSON 修复只处理格式兼容问题，不新增业务语义；模型修复兜底只能调用一次，仍失败时返回 502 并记录日志。

`scenario-composer` 特别约定：

- 默认读取候选用例最近一次执行样本，让模型基于真实 request/response 理解接口字段、断言和变量依赖。
- 只有请求显式传 `execute_candidates=true` 时才实际执行候选用例；该模式额外要求 `test:execute` 权限。
- 实际执行可能造成业务副作用，因此前端默认应保持 `execute_candidates=false`，仅在用户确认调试/探测时开启。
- 默认 `self_validate=true`。生成草稿后会复用 `ScenarioService.validate_unsaved_scenario` 执行未保存场景，失败时将结构化执行问题反馈给模型修复，最多 3 次。
- 自验证能力位于场景服务层，后续平台 agent 可以复用；不要在某个前端页面或单个 skill 中重复实现执行逻辑。
- AI 返回后，adapter 仍会强制过滤非候选 `reference_id`，并通过 `ScenarioCreateRequest` 校验。
