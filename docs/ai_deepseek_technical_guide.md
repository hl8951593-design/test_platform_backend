# DeepSeek AI 能力技术开发指南

本文档用于记录 DeepSeek 官方技术文档中与本项目后续 AI 功能开发相关的能力、约束和落地建议。它不是接口调用文档，而是后续开发“AI 生成测试用例、失败分析、断言推荐、报告摘要、代码补全”等功能时的技术设计参考。

官方参考文档：

- DeepSeek 对话补全：https://api-docs.deepseek.com/zh-cn/api/create-chat-completion
- DeepSeek FIM 补全：https://api-docs.deepseek.com/zh-cn/api/create-completion
- DeepSeek JSON Output：https://api-docs.deepseek.com/zh-cn/guides/json_mode
- DeepSeek 多轮对话：https://api-docs.deepseek.com/zh-cn/guides/multi_round_chat
- DeepSeek 对话前缀续写：https://api-docs.deepseek.com/zh-cn/guides/chat_prefix_completion

## 1. 当前接入状态

当前项目已经完成 DeepSeek 基础数据源接入：

| 能力 | 当前状态 | 代码位置 |
| --- | --- | --- |
| Chat Completions | 已接入 | `app/services/ai_service.py` |
| JSON Output | 已接入基础参数 | `response_format=json` |
| AI 生成测试用例 | 已接入 | `app/services/ai_test_case_service.py` |
| AI 扩写测试用例 | 已接入 | `app/services/ai_test_case_service.py` |
| Thinking 参数 | 已接入基础参数 | `thinking` |
| Reasoning Effort | 已接入基础参数 | `reasoning_effort` |
| 多轮对话 | 接口层已支持 messages 透传，业务侧待封装 | `AIChatRequest.messages` |
| 对话前缀续写 | 待扩展 | 需要支持 beta base_url 和 message.prefix |
| FIM 补全 | 待扩展 | 需要新增 `/completions` 封装 |
| 流式输出 | 待扩展 | 需要 SSE 或 WebSocket 支持 |

当前接口：

```text
GET  /api/v1/ai/provider
POST /api/v1/ai/chat
POST /api/v1/ai/test-cases/generate
POST /api/v1/ai/test-cases/{test_case_id}/expand
```

## 2. DeepSeek 基础调用模型

DeepSeek Chat Completions 采用 OpenAI 兼容格式，项目中统一通过 `httpx` 调用。

推荐后续所有业务 AI 功能都通过 `AIService` 间接调用，不要在业务 Service 中直接拼接 DeepSeek HTTP 请求。

推荐调用链：

```text
业务 Service
-> AIService
-> DeepSeek HTTP API
-> 统一响应结构
-> 业务解析和落库
```

这样做的好处：

- API Key、base_url、模型、超时统一管理。
- 上游错误统一转换。
- 后续切换模型供应商时不影响业务模块。
- 便于统一加调用日志、token 统计、脱敏和限流。

## 3. 多轮对话设计

DeepSeek 的 `/chat/completions` 是无状态接口，服务端不会保存上下文。每次请求都必须由调用方把历史消息完整传入 `messages`。

后续如果开发“AI 助手会话”功能，不能只保存最后一条用户输入，需要保存完整消息历史。

推荐数据模型：

```text
ai_conversations
-> id
-> project_id
-> user_id
-> title
-> scene
-> created_at
-> updated_at

ai_conversation_messages
-> id
-> conversation_id
-> role
-> content
-> token_count
-> created_at
```

推荐调用流程：

```text
用户输入
-> 查询历史 messages
-> 追加本次 user message
-> 调用 AIService.chat
-> 追加 assistant message
-> 返回本轮结果
```

上下文控制规则：

- 每轮请求前必须控制历史消息长度，避免超上下文。
- 优先保留 system prompt、最近若干轮对话、关键业务上下文。
- 对历史执行记录、接口文档这类长文本，建议先摘要再放入 prompt。
- 不要把 access_token、password、cookie、secret header 原样写入 messages。

## 4. JSON Output 使用规范

JSON Output 用于让模型返回可被程序解析的结构化结果。本项目后续“生成测试用例草稿、推荐断言、生成提取器、失败原因结构化分析”都应该优先使用 JSON Output。

DeepSeek JSON 模式注意事项：

- 请求中设置 `response_format={"type":"json_object"}`。
- system 或 user prompt 中必须明确出现 `json` 字样。
- prompt 中必须给出期望 JSON 结构样例。
- `max_tokens` 要足够大，避免 JSON 被截断。
- 需要处理 content 为空或 JSON 解析失败的情况。

推荐后端解析流程：

```text
调用 AIService.chat(response_format=json)
-> 检查 content 非空
-> json.loads(content)
-> Pydantic Schema 校验
-> 失败时返回可读错误，不直接落库
```

测试用例生成推荐 JSON 结构：

```json
{
  "name": "登录成功",
  "description": "验证有效账号密码可以登录",
  "method": "POST",
  "path": "/finance/api/login",
  "headers": {
    "Content-Type": "application/json"
  },
  "query_params": {},
  "body_type": "json",
  "body": {
    "username": "admin",
    "password": "admin"
  },
  "assertions": [
    {
      "type": "status_code",
      "expected": 200
    }
  ],
  "extractors": []
}
```

失败分析推荐 JSON 结构：

```json
{
  "summary": "请求被上游拒绝",
  "root_cause": "目标服务返回 403",
  "evidence": [
    "status_code=403",
    "response_body 包含 error code"
  ],
  "suggestions": [
    "检查目标服务 WAF 或 Cloudflare 规则",
    "补充必要请求头"
  ],
  "confidence": "medium"
}
```

## 5. 对话前缀续写

对话前缀续写适合“强制模型从指定格式开始输出”的场景。它沿用 Chat Completions，但最后一条 message 必须是 `assistant`，并带有 `prefix=true`。

DeepSeek 要求：

- 使用 beta base_url：`https://api.deepseek.com/beta`
- `messages` 最后一条必须是 assistant。
- 最后一条 assistant message 需要设置 `prefix=true`。

适用场景：

- 强制输出代码块，例如让模型直接续写 Python、JSON、YAML。
- 强制输出某种固定前缀后的内容。
- 减少模型解释性文本。

本项目后续可用于：

- 根据接口描述生成 Python 调试脚本。
- 根据接口字段生成 JSON Schema。
- 根据失败日志生成 Markdown 报告片段。

建议新增 Service 方法：

```text
AIService.chat_prefix_completion(...)
```

建议请求结构：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "根据接口信息生成 pytest 测试代码"
    },
    {
      "role": "assistant",
      "content": "```python\n",
      "prefix": true
    }
  ],
  "stop": ["```"]
}
```

实现注意：

- 该能力是 beta，不建议作为核心链路唯一依赖。
- 需要增加 `DEEPSEEK_BETA_BASE_URL=https://api.deepseek.com/beta`。
- 当前 `AIChatMessage` 还没有 `prefix` 字段，扩展时需要新增。

## 6. FIM 补全

FIM 是 Fill-In-the-Middle 补全，适合给定前缀和后缀，让模型补中间内容。

DeepSeek 要求：

- 接口路径：`POST /completions`
- beta base_url：`https://api.deepseek.com/beta`
- 模型：`deepseek-v4-pro`
- 必填：`prompt`
- 可选：`suffix`

适用场景：

- 在已有代码前后文中补全中间逻辑。
- 自动补全测试步骤。
- 根据已有 JSON 前后片段补全缺失字段。
- 给自动化脚本补齐中间断言逻辑。

建议新增 Service 方法：

```text
AIService.fim_completion(prompt, suffix, max_tokens, stop)
```

建议请求结构：

```json
{
  "model": "deepseek-v4-pro",
  "prompt": "def test_login_success():\n    response = client.post(",
  "suffix": "\n    assert response.status_code == 200",
  "max_tokens": 256,
  "temperature": 0.2,
  "stop": ["\n\n"]
}
```

实现注意：

- FIM 返回结构是 text completion，不是 chat message。
- 响应内容在 `choices[0].text`。
- `finish_reason` 可能是 `stop`、`length`、`content_filter`、`insufficient_system_resource`。
- 如果需要流式返回，需要处理 SSE。

## 7. 参数使用建议

| 参数 | 建议 |
| --- | --- |
| model | 默认使用 `DEEPSEEK_MODEL`，复杂推理可由业务传入更强模型 |
| temperature | 生成测试用例、断言推荐建议 0.2 到 0.4 |
| max_tokens | JSON 输出时必须留足，避免结构被截断 |
| response_format | 需要落库或程序解析时必须使用 `json` |
| thinking | 普通生成可关闭，复杂分析可开启 |
| reasoning_effort | 复杂失败定位、覆盖率分析可使用 `high` 或 `max` |
| stop | 代码块、前缀续写、FIM 场景建议使用 |
| stream | 后续长文本生成或前端实时输出时再接入 |

## 8. 本项目 AI 功能分层建议

建议后续按三层拆分：

```text
AIProvider 层
-> 只负责 DeepSeek 请求、错误转换、响应解析

AICapability 层
-> 封装测试用例生成、失败分析、断言推荐等能力

业务 API 层
-> 负责权限校验、读取项目数据、调用能力层、落库或返回结果
```

推荐目录规划：

```text
app/services/ai_service.py
app/services/ai_capabilities/
  test_case_generation.py
  failure_analysis.py
  assertion_recommendation.py
  report_summary.py
app/schemas/ai.py
app/schemas/ai_capabilities.py
```

不要把 prompt 模板散落在 Router 中。Prompt 应该放在能力 Service 或独立模板模块中，方便测试和迭代。

## 9. Prompt 模板规范

所有业务 prompt 建议包含：

- 角色定义：说明模型在本平台中的角色。
- 输入说明：列出后端传入的数据字段。
- 输出要求：如果要程序解析，必须要求 JSON。
- 输出示例：给出完整 JSON 样例。
- 约束：禁止编造未提供的接口字段，禁止输出密钥。

测试用例生成 system prompt 示例：

```text
你是自动化测试平台的接口测试用例设计助手。
请根据用户提供的接口信息生成可保存到平台的测试用例。
必须只输出合法 JSON，不要输出 Markdown。
不要编造未提供的接口路径、请求方法和认证信息。
```

失败分析 system prompt 示例：

```text
你是自动化测试平台的执行失败分析助手。
请根据请求快照、响应快照、断言结果和错误信息分析失败原因。
必须输出合法 JSON，字段包含 summary、root_cause、evidence、suggestions、confidence。
```

## 10. 安全与合规要求

AI 调用前必须做脱敏：

| 数据类型 | 处理方式 |
| --- | --- |
| Authorization | 保留认证类型，隐藏 token |
| Cookie | 默认不传给 AI |
| password | 替换为 `******` |
| access_token / refresh_token | 替换为 `******` |
| 手机号 / 邮箱 | 后续可按配置决定是否脱敏 |
| 环境变量中的 secret | 必须脱敏 |

落库建议：

- 保存 prompt 摘要，不默认保存完整敏感上下文。
- 保存模型、usage、finish_reason、调用状态。
- 保存调用用户和项目 ID，便于审计。
- AI 输出落库前必须经过 Schema 校验。

## 11. 后续开发清单

优先级建议：

1. 增加 AI 调用日志表，记录 provider、model、usage、status、duration。
2. 增加脱敏工具，统一处理请求头、环境变量、请求体。
3. 增加 JSON Output 的解析和 Pydantic 校验工具。
4. 开发“根据接口信息生成测试用例草稿”能力。
5. 开发“根据执行记录分析失败原因”能力。
6. 接入对话前缀续写，用于代码或固定格式文本生成。
7. 接入 FIM 补全，用于脚本和结构片段补全。
8. 根据前端需要评估流式输出，选择 SSE 或 WebSocket。

## 12. 当前实现边界

当前已完成的是“AI 数据源基础接入”，不是完整 AI 业务功能。

当前不负责：

- AI 会话历史保存。
- AI 调用日志保存。
- 自动生成测试用例并落库。
- AI 输出自动修复。
- 流式返回。
- FIM 和前缀续写实际接口封装。

后续开发时应优先复用当前 `AIService.chat`，等业务场景明确后再扩展 beta 能力。

## 13. AI 生成测试用例接口设计

当前第一个 AI 业务能力是“根据用户粘贴的接口资料生成测试用例草稿”。

接口：

```text
POST /api/v1/ai/test-cases/generate?project_id={project_id}&environment_id={environment_id}
```

业务规则：

- 需要当前登录用户拥有 `case:manage` 权限。
- `project_id` 表示生成结果归属项目。
- `environment_id` 表示当前环境，生成结果必须绑定该环境。
- 接口只返回草稿，不直接保存到 `test_cases`。
- 前端确认后，继续调用测试用例保存接口。

生成流程：

```text
接收 interface_text、request_method、generate_count、include_assertions
-> 校验项目权限
-> 校验环境属于当前项目
-> 读取环境 base_url 和变量名
-> 组装强约束 prompt
-> 调用 DeepSeek JSON Output
-> 解析模型 JSON
-> 兼容代码块、根数组、字段别名、完整 URL
-> 强制写入 project_id、environment_id、environment_ids
-> 使用 TestCaseCreateRequest 校验每条用例
-> 返回固定 JSON 给前端
```

提示词约束重点：

- 要求模型只输出 JSON。
- 根对象固定为 `source_summary`、`cases`、`warnings`。
- 用例字段完全对齐 `TestCaseCreateRequest`。
- 禁止编造真实 token、cookie、密码、手机号、邮箱。
- 要求 path 优先返回相对路径，不拼接 base_url。
- 断言类型只允许 `status_code`、`body_contains`、`json_equals`。
- 提取器只允许 `name` 和 `path`。

兼容处理：

- 去除 ```json 代码块。
- 如果根节点是数组，自动包装为 `cases`。
- 支持 `cases`、`test_cases`、`data` 三种字段来源。
- 完整 URL 自动拆分为 `path` 和 `query_params`。
- method 自动转大写，非法 method 回退 GET。
- 非法 body_type 回退 none。
- 非法断言和提取器会被过滤。

返回结构固定：

```json
{
  "project_id": 1,
  "environment_id": 1,
  "environment_ids": [1],
  "source_summary": "接口摘要",
  "cases": [],
  "warnings": []
}
```

## 14. AI 扩写测试用例接口设计

第二个 AI 业务能力是“基于已有测试用例扩写多个变体用例”。

接口：

```text
POST /api/v1/ai/test-cases/{test_case_id}/expand?project_id={project_id}&environment_id={environment_id}
```

业务规则：

- 需要当前登录用户拥有 `case:manage` 权限。
- `test_case_id` 必须属于当前 `project_id`。
- `environment_id` 可选，不传时使用源用例默认环境或第一个关联环境。
- 接口只返回草稿，不直接保存到 `test_cases`。
- 前端确认后，继续调用测试用例保存接口。

扩写流程：

```text
接收 test_case_id 和自然语言 requirement
-> 校验项目权限
-> 查询源测试用例
-> 确定当前环境
-> 读取环境变量名
-> 构造源用例上下文和扩写要求
-> 调用 DeepSeek JSON Output
-> 兼容解析模型输出
-> 强制绑定 project_id、environment_id、environment_ids
-> 使用 TestCaseCreateRequest 校验每条扩写用例
-> 返回固定 JSON 给前端
```

扩写方向：

- `empty_value`：字段 key 保留，但 value 为空字符串、null、空数组或空对象。
- `invalid_type`：字段 key 保留，但 value 类型错误。
- `extra_param`：在原请求基础上增加少量无关字段。
- `missing_param`：在原请求基础上删除单个关键字段或少量字段。
- `length_overflow`：字符串字段超过合理长度。
- `invalid_format`：字段格式错误，例如日期、邮箱、手机号、枚举格式非法。

提示词约束重点：

- 扩写用例默认沿用源用例的 method、path、headers、body_type。
- 主要变化体现在 body、query_params、assertions、name、description。
- 禁止生成“完全不传参”“删除全部 body”“删除全部 query_params”这类过粗用例。
- 扩写应基于源用例做单点或少量字段变异，用来检测接口健壮性。
- 不编造真实敏感值，需要变量时使用 `{{变量名}}`。
- 负向用例通常不应生成 extractors。
- 仍然只允许平台支持的断言和提取器结构。
