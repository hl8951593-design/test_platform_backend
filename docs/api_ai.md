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

## 错误处理

| 场景 | 后端状态码 | 说明 |
| --- | --- | --- |
| 未配置 `DEEPSEEK_API_KEY` | 500 | 本地服务配置缺失 |
| DeepSeek 返回 4xx/5xx | 502 | 上游 AI 服务返回异常 |
| 网络错误或超时 | 503 | 无法连接 DeepSeek |

## 后续扩展方向

- 根据接口信息生成测试用例。
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
- 如果模型返回代码块、根数组、`test_cases` 别名、完整 URL、小写 method，后端会做兼容处理。
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
