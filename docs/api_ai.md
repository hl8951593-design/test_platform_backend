# AI 数据源接口文档

本文档说明平台后端接入 DeepSeek 后提供的基础 AI 数据源接口。基础路径：

```text
http://127.0.0.1:8000/api/v1
```

## 接入说明

DeepSeek 提供 OpenAI 兼容接口，当前后端通过 `httpx` 调用：

```text
POST https://api.deepseek.com/chat/completions
```

本项目配置项：

| 配置项 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key，只允许配置在 `.env` 中 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 基础地址，默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 默认模型，默认 `deepseek-v4-flash` |
| `DEEPSEEK_TIMEOUT_SECONDS` | 请求超时时间，默认 60 秒 |
| `DEEPSEEK_STREAM_MAX_RETRIES` | 流式响应首个 delta/done 前的最大重试次数，默认 2 |
| `DEEPSEEK_STREAM_RETRY_BASE_SECONDS` | 首包前流式重试退避起点，默认 0.5 秒 |
| `DEEPSEEK_STREAM_RETRY_MAX_SECONDS` | 首包前流式重试退避上限，默认 4 秒 |

`.env.example` 只保留占位符，不记录真实 key。

## 查询 AI 数据源配置

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/provider` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 查询当前 AI 数据源、默认模型和 key 是否已配置 |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "default_model": "deepseek-v4-flash",
    "configured": true
  }
}
```

## DeepSeek 对话补全

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/chat` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 调用 DeepSeek Chat Completions，作为后续 AI 功能的数据源基础 |

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| messages | array | 是 | 对话消息列表 |
| model | string | 否 | 不传时使用 `DEEPSEEK_MODEL` |
| thinking | string | 否 | `enabled` 或 `disabled`，控制思考模式 |
| reasoning_effort | string | 否 | `high` 或 `max`，控制推理强度 |
| temperature | number | 否 | 采样温度，范围 0 到 2 |
| max_tokens | integer | 否 | 最大输出 token 数 |
| response_format | string | 否 | `text` 或 `json`，默认 `text` |

请求示例：

```json
{
  "messages": [
    {
      "role": "system",
      "content": "你是自动化测试平台的接口用例生成助手。"
    },
    {
      "role": "user",
      "content": "根据登录接口生成一条接口测试用例设计建议。"
    }
  ],
  "thinking": "disabled",
  "temperature": 0.3,
  "max_tokens": 800,
  "response_format": "text"
}
```

响应示例：

```json
{
  "code": 0,
  "message": "AI 调用成功",
  "data": {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "content": "建议覆盖登录成功、密码错误、账号不存在、禁用用户等场景。",
    "usage": {
      "prompt_tokens": 30,
      "completion_tokens": 18,
      "total_tokens": 48
    },
    "finish_reason": "stop"
  }
}
```

## JSON 模式

当 `response_format` 传 `json` 时，后端会向 DeepSeek 传入：

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

使用 JSON 模式时，调用方必须在 `messages` 中明确要求模型输出 JSON，否则模型可能无法稳定返回合法 JSON。

平台业务 skill 对 JSON 输出有额外约束：

- Prompt 必须给出完整根对象示例，并明确字段名不能拆行。
- 需要程序解析的字符串值不得包含真实换行、制表符或其他控制字符；如必须表达换行，应使用 `\n` 转义。
- HTTP 用例生成和扩写根对象固定为 `{"source_summary":"","cases":[],"warnings":[]}`。
- HTTP 用例断言只允许 `status_code`、`body_contains`、`json_equals`，并且必须使用 `expected` 字段；禁止使用 `value`、`expect`、`actual` 等替代字段。
- AI 返回内容会先经过本地 JSON 解析兼容层：去除代码块、提取 JSON 片段、修复尾逗号、未转义引号、字符串中的控制字符、字段名断行等常见模型输出问题。
- 本地解析仍失败时，`AISkillRunner` 会使用低温 JSON 修复请求重试一次；修复仍失败才返回 `502`。

## AI Skills

平台 AI 业务能力以正式 skill 包组织。每个 skill 包至少包含：

```text
SKILL.md
manifest.json
prompts/
```

`SKILL.md` 面向 agent 触发和阅读，`manifest.json` 面向后端、前端和 agent 编排，描述版本、协议、能力列表、输入 schema 和输出 schema。

当前内置 skill：

| Skill ID | 协议 | 能力 |
| --- | --- | --- |
| `http-test-case` | HTTP | 接口测试用例生成、扩写 |
| `websocket-test-case` | WebSocket | WebSocket 测试用例生成、扩写 |
| `scenario-composer` | Mixed | 从候选 HTTP/WebSocket 用例智能组合场景草稿 |

### 查询可用 Skills

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/skills` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 返回当前后端已注册的 AI skills、operation、输入输出 schema 和 JSON Schema |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": "http-test-case",
      "name": "http-test-case",
      "description": "Generate or expand HTTP API test case drafts...",
      "version": "1.0.0",
      "domain": "test_case",
      "protocol": "http",
      "operations": [
        {
          "name": "generate",
          "summary": "Generate HTTP API test case drafts...",
          "input_schema": "AITestCaseGenerateRequest",
          "output_schema": "AIGeneratedTestCaseResponse",
          "input_json_schema": {},
          "output_json_schema": {},
          "requires_environment": true,
          "requires_source": false
        }
      ]
    }
  ]
}
```

### 查询 Skill 详情

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/skills/{skill_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 查询单个 skill 的 manifest 信息 |

### 运行 Skill

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/skills/{skill_id}/run` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 统一运行 AI skill。后端根据 skill 和 operation 分发到对应业务适配器 |

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| operation | string | 是 | skill operation，例如 `generate`、`expand` |
| project_id | integer | 是 | 当前项目 ID |
| environment_id | integer/null | 否 | 当前环境 ID。生成类 operation 通常必填；扩写类不传时使用源用例环境 |
| source_id | integer/null | 否 | 源资源 ID。扩写测试用例时为源测试用例 ID |
| input | object | 是 | 按 operation 的 `input_schema` 提交 |

HTTP 用例生成示例：

```json
{
  "operation": "generate",
  "project_id": 1,
  "environment_id": 2,
  "input": {
    "interface_text": "GET /api/users/{id} returns {\"id\":1,\"name\":\"demo\"}",
    "generate_count": 3,
    "include_assertions": true
  }
}
```

HTTP 用例扩写示例：

```json
{
  "operation": "expand",
  "project_id": 1,
  "environment_id": 2,
  "source_id": 1001,
  "input": {
    "requirement": "扩写边界值和异常参数",
    "generate_count": 5,
    "include_assertions": true
  }
}
```

智能场景组合示例：

```json
{
  "operation": "compose",
  "project_id": 1,
  "environment_id": 2,
  "input": {
    "requirement": "组合登录后查询用户详情的主链路，登录步骤提取 token，详情查询使用 token",
    "scenario_name": "用户详情主链路",
    "http_test_case_ids": [1001, 1002],
    "websocket_test_case_ids": [],
    "include_bindings": true,
    "include_assertions": true,
    "include_hooks": true,
    "include_datasets": false,
    "include_latest_execution": true,
    "execute_candidates": false,
    "self_validate": true,
    "max_validation_attempts": 3,
    "max_nodes": 10
  }
}
```

`scenario-composer` 返回结构：

```json
{
  "code": 0,
  "message": "AI Skill 执行成功",
  "data": {
    "project_id": 1,
    "environment_id": 2,
    "environment_name": "UAT",
    "source_summary": "组合登录和用户详情查询",
    "scenario": {
      "name": "用户详情主链路",
      "description": "登录后查询用户详情",
      "environment_id": 2,
      "tags": ["ai-composed"],
      "nodes": [],
      "datasets": []
    },
    "warnings": [],
    "self_validated": true,
    "validation_attempts": [
      {
        "attempt": 1,
        "status": "passed",
        "run_id": 123,
        "duration_ms": 856,
        "summary": {
          "total_steps": 2,
          "passed": 2,
          "failed": 0,
          "timeout": 0,
          "skipped": 0
        },
        "issues": []
      }
    ]
  }
}
```

场景组合规则：

- `scenario-composer` 不直接保存场景，只返回草稿；前端确认后再调用场景创建接口。
- `reference_id` 只能引用 `http_test_case_ids` / `websocket_test_case_ids` 中传入的候选用例。
- 默认读取候选用例最近一次执行的请求/响应样本，帮助 AI 理解接口语义、响应字段和依赖关系。
- `execute_candidates=true` 时，后端会在组合前实际执行候选用例以获取样本；该开关可能产生业务副作用，调用方应谨慎启用。
- `self_validate=true` 默认开启。后端会在生成草稿后执行一次未保存场景进行自验证；如果执行失败，会把失败步骤、断言失败、变量提取错误和响应样本反馈给模型修复，最多 `max_validation_attempts=3` 轮。
- 自验证执行不落库保存场景，但会产生场景运行记录和底层用例执行记录，用于审计和查看执行详情。
- 实际执行候选用例或自验证场景时，除场景管理权限外，还需要 `test:execute` 权限。
- skill 会根据候选用例配置和请求/响应样本生成或补充 `assertions`、`extractors`、`_scenario_context.extractions`、`_scenario_context.bindings`。
- skill 可以生成必要的 `before_actions` / `after_actions`，用于固定变量、随机数据、等待、条件门禁、清理或轻量计算。
- 如果 AI 返回的 `before_actions` / `after_actions` 漏掉 `kind`，后端会在可确定时根据配置推断为 `fixed_value`、`delay`、`condition`、`random` 或 `script`；无法推断或配置不合法的动作会被丢弃并写入 warnings，避免单个非关键动作导致整个场景草稿校验失败。
- 后端会二次校验 AI 返回，丢弃非候选引用；如果没有可用节点则返回 `502`。
- `include_datasets=false` 时会丢弃 AI 返回的数据集草稿。
- 生成结果必须满足 `ScenarioCreateRequest`，因此可直接作为创建场景请求体使用。

响应结构与对应旧业务接口保持一致。旧接口继续可用，新接入的 agent 和前端编排建议优先使用 skill 列表和统一运行入口。

### 可观测 Skill Run

同步接口 `/ai/skills/{skill_id}/run` 仍然保留。需要类似 Codex 的过程展示时，前端应使用异步 run：

```text
POST /api/v1/ai/skills/{skill_id}/runs
GET  /api/v1/ai/skill-runs/{run_id}
GET  /api/v1/ai/skill-runs/{run_id}/events
```

创建 run 的请求体与同步运行一致：

```json
{
  "operation": "compose",
  "project_id": 1,
  "environment_id": 2,
  "input": {
    "requirement": "组合登录后查询用户详情的主链路",
    "http_test_case_ids": [1001, 1002],
    "include_latest_execution": true
  }
}
```

创建响应：

```json
{
  "code": 0,
  "message": "AI Skill Run 已创建",
  "data": {
    "run_id": "ai-run-...",
    "skill_id": "scenario-composer",
    "operation": "compose",
    "status": "queued"
  }
}
```

事件流使用 SSE，前端带 `Last-Event-ID` 可断点续读：

```text
event: run.started
data: {}

event: tool.started
data: {"name":"load_candidate_cases","http_test_case_ids":[1001,1002]}

event: model.delta
data: {"content":"..."}

event: step.completed
data: {"title":"校验 AI 返回结构"}

event: run.completed
data: {"result":{}}
```

事件类型约定：

| 事件 | 说明 |
| --- | --- |
| `run.queued` / `run.started` / `run.completed` / `run.failed` | Run 生命周期 |
| `step.started` / `step.completed` | 平台内部步骤，例如权限校验、结构校验 |
| `tool.started` / `tool.completed` | 工具或数据访问，例如读取候选用例、执行候选接口 |
| `model.started` / `model.delta` / `model.completed` | 模型调用过程和流式输出 |
| `model.stream_retrying` | DeepSeek 流式响应在首个 delta/done 前失败后准备重试；payload 不包含 key、prompt 或请求体 |
| `heartbeat` | SSE 心跳 |

安全规则：

- 事件 payload 会经过敏感字段脱敏，例如 authorization、cookie、password、token、secret。
- run 只能由创建者或管理员读取/订阅。
- 不返回模型原始 Chain of Thought；前端可展示执行轨迹、工具调用、模型流式内容和校验摘要。
- 当前 AI Skill Run 使用应用内执行工作池和内存事件仓库：适合过程展示和联调；服务重启后 run 事件不会恢复，生产治理阶段需要迁移到持久化 run/event 表或可靠队列。

## 错误处理

| 场景 | 后端状态码 | 说明 |
| --- | --- | --- |
| 未配置 `DEEPSEEK_API_KEY` | 500 | 本地服务配置缺失 |
| DeepSeek 返回 4xx/5xx | 502 | 上游 AI 服务返回异常 |
| 网络错误或超时 | 503 | 无法连接 DeepSeek；流式调用在首个 delta/done 前会按配置重试 |
| skill 不存在 | 404 | `skill_id` 未注册 |
| operation 不存在或缺少必要上下文 | 400 | operation 不属于该 skill，或缺少 `environment_id` / `source_id` |
| skill input 校验失败 | 422 | `input` 不符合 operation 的输入 schema |
| AI 返回 JSON 无法解析且修复失败 | 502 | 本地修复和一次模型修复均失败 |
| AI 返回结构无法通过业务 Schema 校验 | 502 | JSON 合法但字段不满足平台契约 |

## 后续扩展方向

- 持久化 AI run/event、模型版本、token 用量、耗时和费用。
- 增加项目级 AI 开关、调用额度和审计。
- 根据执行失败记录分析失败原因。
- 根据响应报文推荐断言。
- 根据接口文档批量生成测试用例草稿。
- 根据测试报告生成摘要。

## WebSocket 测试用例 AI 接口

WebSocket 用例使用独立 AI 能力，不复用 HTTP 用例提示词：

```text
POST /api/v1/ai/websocket-test-cases/generate
POST /api/v1/ai/websocket-test-cases/{test_case_id}/expand
```

专用提示词围绕 WebSocket 握手、鉴权 header、子协议协商、消息顺序、消息级断言、连续推送、接收超时和连接关闭设计。输出通过 `WebSocketTestCaseCreateRequest` 校验，禁止包含 HTTP method、body、query 和状态码断言。

## AI 生成接口测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/test-cases/generate?project_id={project_id}&environment_id={environment_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的项目成员 |
| 说明 | 根据前端粘贴的接口资料生成测试用例草稿，返回固定 JSON，不直接落库 |

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| interface_text | string | 是 | 用户粘贴的接口文档、curl、URL、请求参数、响应示例或业务说明 |
| request_method | string | 否 | 前端识别到的请求方式，自动识别时可为空 |
| generate_count | integer | 否 | 生成数量，范围 1 到 10，默认 3 |
| include_assertions | boolean | 否 | 是否生成断言，默认 true |
| extra_requirements | string | 否 | 用户额外要求 |

请求示例：

```json
{
  "interface_text": "POST /finance/api/login JSON body: {\"username\":\"admin\",\"password\":\"admin\"}; success returns {\"code\":0,\"data\":{\"access_token\":\"xxx\"}}",
  "request_method": "POST",
  "generate_count": 3,
  "include_assertions": true,
  "extra_requirements": "覆盖登录成功、密码错误、缺少用户名"
}
```

响应示例：

```json
{
  "code": 0,
  "message": "AI 测试用例生成成功",
  "data": {
    "project_id": 1,
    "environment_id": 1,
    "environment_ids": [1],
    "source_summary": "根据登录接口生成测试用例",
    "cases": [
      {
        "name": "登录成功",
        "description": "验证正确用户名和密码可以登录",
        "environment_id": 1,
        "environment_ids": [1],
        "method": "POST",
        "path": "/finance/api/login",
        "headers": {
          "Content-Type": "application/json"
        },
        "query_params": {},
        "body_type": "json",
        "body": {
          "username": "admin",
          "password": "{{password}}"
        },
        "assertions": [
          {
            "type": "status_code",
            "expected": 200
          },
          {
            "type": "json_equals",
            "path": "code",
            "expected": 0
          }
        ],
        "extractors": [
          {
            "name": "access_token",
            "path": "data.access_token"
          }
        ]
      }
    ],
    "warnings": [
      "密码字段建议使用环境变量"
    ]
  }
}
```

后端处理规则：

- 当前项目由 query 参数 `project_id` 确定。
- 当前环境由 query 参数 `environment_id` 确定。
- 生成结果中的每条用例都会强制写入当前 `environment_id` 和 `environment_ids=[environment_id]`。
- AI 调用使用 DeepSeek JSON Output。
- 提示词要求输出完整 JSON 对象、完整字段名、单行字符串、固定用例结构和 `expected` 断言字段。
- 如果模型返回代码块、根数组、`test_cases` 别名、完整 URL、小写 method，后端会做兼容处理。
- 如果模型返回字段名断行、字符串裸换行、尾逗号或未转义引号等常见坏 JSON，后端会尝试本地修复；仍失败时会触发一次模型 JSON 修复。
- 如果模型返回非法断言、非法提取器或无效字段，后端会过滤或返回 `warnings`。
- 如果最终结构无法通过平台测试用例 Schema 校验，后端返回 502。

## AI 扩写接口测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/ai/test-cases/{test_case_id}/expand?project_id={project_id}&environment_id={environment_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的项目成员 |
| 说明 | 基于一个已存在测试用例，按自然语言要求扩写多个边界值、异常、负向或业务变体用例草稿 |

`environment_id` 可选。不传时后端使用源测试用例的默认环境；如果源用例没有默认环境，则使用源用例的第一个关联环境。

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| requirement | string | 是 | 自然语言扩写要求 |
| generate_count | integer | 否 | 生成数量，范围 1 到 10，默认 5 |
| expansion_types | array | 否 | 扩写类型，默认使用接口健壮性方向 |
| include_assertions | boolean | 否 | 是否生成断言，默认 true |

请求示例：

```json
{
  "requirement": "围绕登录接口扩写边界值和异常场景，包括用户名为空、密码为空、密码错误、字段类型错误、超长用户名",
  "generate_count": 5,
  "expansion_types": ["empty_value", "invalid_type", "missing_param", "extra_param", "length_overflow"],
  "include_assertions": true
}
```

响应结构与 AI 生成接口测试用例一致：

```json
{
  "code": 0,
  "message": "AI 测试用例扩写成功",
  "data": {
    "project_id": 1,
    "environment_id": 1,
    "environment_ids": [1],
    "source_summary": "基于登录成功用例扩写异常和边界场景",
    "cases": [],
    "warnings": []
  }
}
```

后端处理规则：

- 源用例必须属于当前 `project_id`。
- 扩写用例默认沿用源用例的 method、path、headers、body_type、extractors。
- 主要变化应体现在 `name`、`description`、`query_params`、`body`、`assertions`。
- 负向或异常用例通常不生成 extractors。
- 扩写提示词同样要求合法 JSON、字段名不能拆行、字符串内部不输出真实控制字符，并要求断言使用 `expected` 字段。
- 返回结果仍然是草稿，不直接保存到 `test_cases`。

扩写类型说明：

| 类型 | 说明 |
| --- | --- |
| empty_value | 字段 key 保留，但 value 为空字符串、null、空数组或空对象 |
| invalid_type | 字段 key 保留，但 value 类型错误 |
| extra_param | 在原请求基础上增加少量无关字段 |
| missing_param | 在原请求基础上删除单个关键字段或少量字段 |
| length_overflow | 字符串字段超过合理长度 |
| invalid_format | 字段格式错误，例如日期、邮箱、手机号、枚举格式非法 |

限制规则：

- 不生成“完全不传参”“删除全部 body”“删除全部 query_params”这类过粗用例。
- 扩写必须基于源用例做单点或少量字段变异。
- method、path、headers、body_type 默认沿用源用例。
- 如果模型生成了疑似删除全部请求参数的结果，后端会在 `warnings` 中提示前端确认。
