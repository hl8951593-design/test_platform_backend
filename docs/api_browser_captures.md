# 浏览器采集与插件接口

Chrome 插件通过浏览器采集接口保存一次操作过程中捕获的 HTTP 与 WebSocket 草稿。插件本地负责实时抓包、初步脱敏和临时审阅，后端负责批次持久化、二次脱敏、结构化 AI 分析、正式资产导入和审计记录。

基础路径：

```text
http://127.0.0.1:8000/api/v1
```

成功响应沿用统一结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

## 数据流程

1. 插件开始采集时调用 `POST /browser-captures?project_id={id}` 创建批次。
2. 插件实时在本地保存和审阅草稿，不逐请求写入后端。
3. 停止采集时调用 `POST /browser-captures/{capture_id}/entries/batch?project_id={id}` 幂等同步草稿。
4. 草稿可调用 `POST /ai/browser-captures/{capture_id}/entries/{entry_id}/analyze?project_id={id}` 进行结构化分析。
5. 未同步本地草稿可调用 `POST /ai/browser-captures/analyze?project_id={id}&environment_id={id}` 进行临时分析。
6. 审阅完成后调用 `POST /browser-captures/{capture_id}/import?project_id={id}` 导入正式 HTTP/WebSocket 用例，可选择生成场景。

## 接口总览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/browser-captures?project_id={id}` | 查询项目采集批次 |
| `POST` | `/browser-captures?project_id={id}` | 创建采集批次 |
| `PUT` | `/browser-captures/{capture_id}?project_id={id}` | 更新批次状态 |
| `DELETE` | `/browser-captures/{capture_id}?project_id={id}` | 删除采集批次 |
| `GET` | `/browser-captures/{capture_id}/entries?project_id={id}` | 查询批次草稿，支持筛选 |
| `POST` | `/browser-captures/{capture_id}/entries/batch?project_id={id}` | 按 `client_entry_id` 幂等同步草稿 |
| `PUT` | `/browser-captures/{capture_id}/entries/{entry_id}?project_id={id}` | 更新草稿状态与审阅结果 |
| `POST` | `/browser-captures/{capture_id}/import?project_id={id}` | 导入正式资产 |
| `POST` | `/ai/browser-captures/analyze?project_id={id}&environment_id={id}` | 分析未同步本地草稿 |
| `POST` | `/ai/browser-captures/{capture_id}/entries/{entry_id}/analyze?project_id={id}` | 分析已同步草稿 |
| `POST` | `/ai/browser-captures/{capture_id}/entries/{entry_id}/generate-cases?project_id={id}` | 根据结构化草稿生成用例建议 |
| `POST` | `/ai/browser-captures/{capture_id}/generate-cases?project_id={id}` | 为选中草稿批量生成用例建议 |
| `POST` | `/ai/browser-captures/{capture_id}/analyze-relations?project_id={id}` | 分析响应字段与后续请求字段依赖 |
| `POST` | `/ai/browser-captures/{capture_id}/batch-analyze?project_id={id}` | 批量分析多选草稿的上下文传递依赖 |
| `POST` | `/ai/browser-captures/{capture_id}/generate-scenario?project_id={id}` | 生成有序场景草稿与跨步骤响应引用建议 |

## 权限

| 权限 | 说明 |
| --- | --- |
| `capture:view` | 查看项目采集批次和草稿 |
| `capture:manage` | 创建、修改、删除采集批次和草稿 |
| `capture:import` | 将采集草稿导入正式资产 |
| `ai:analyze` | 使用采集分析、场景生成和失败诊断能力 |
| `case:manage` | 导入正式 HTTP/WebSocket 用例时仍需校验 |
| `test:execute` | 临时执行 HTTP/WebSocket 用例时仍需校验 |

管理员和项目创建者自动拥有项目内所有权限。普通成员可被授予以上插件权限。

## 创建采集批次

```http
POST /api/v1/browser-captures?project_id=1
Content-Type: application/json

{
  "project_id": 1,
  "environment_id": 4,
  "name": "订单创建流程采集",
  "source_url": "https://test.example.com/orders"
}
```

`project_id` 以 query 为准，请求体中的同名字段仅用于插件侧兼容。

## 批量上传采集记录

```http
POST /api/v1/browser-captures/1/entries/batch?project_id=1
Content-Type: application/json

{
  "entries": [
    {
      "client_entry_id": "uuid",
      "protocol": "http",
      "method": "POST",
      "url": "https://test.example.com/api/orders?page=1",
      "request_headers": {
        "Authorization": "Bearer {{access_token}}"
      },
      "request_body_type": "json",
      "request_body": {
        "product_id": 1001
      },
      "response_status": 200,
      "response_headers": {
        "content-type": "application/json"
      },
      "response_body": {
        "code": 0,
        "data": {
          "order_id": "{{redacted_dynamic_value}}"
        }
      },
      "duration_ms": 128,
      "fingerprint": "sha256-value",
      "captured_at": "2026-06-11T10:00:00+08:00"
    }
  ]
}
```

后端兼容插件原生字段，会规范化为平台字段：

| 插件字段 | 后端草稿字段 |
| --- | --- |
| `url` | `source_url`，并解析出 `path` 和 `request_data.query_params` |
| `request_headers` | `request_data.headers` |
| `request_body_type` | `request_data.body_type` |
| `request_body` | `request_data.body` |
| `response_status` | `response_data.status_code` |
| `response_headers` | `response_data.headers` |
| `response_body` | `response_data.body` |
| `duration_ms` | `draft_data.duration_ms` |

如果插件已经提交平台结构化字段 `name`、`path`、`request_data`、`response_data`、`draft_data`，后端会优先使用显式字段。

## 查询采集记录

```http
GET /api/v1/browser-captures/1/entries?project_id=1&status=captured&protocol=http&method=POST&domain=test.example.com&keyword=orders
```

筛选参数：

| 参数 | 说明 |
| --- | --- |
| `status` / `status_filter` | 草稿状态；插件推荐使用 `status`，后端兼容旧的 `status_filter` |
| `protocol` | `http` 或 `websocket` |
| `method` | HTTP 方法，后端会转大写匹配 |
| `domain` | 按 `source_url` 模糊匹配域名 |
| `keyword` | 按名称、路径、来源 URL 模糊匹配 |

草稿状态：

```text
captured
analyzing
review_required
approved
imported
ignored
failed
```

## 更新草稿

```http
PUT /api/v1/browser-captures/1/entries/11?project_id=1
Content-Type: application/json

{
  "name": "订单创建接口",
  "method": "POST",
  "path": "/api/orders",
  "request_data": {
    "headers": {},
    "query_params": {},
    "body_type": "json",
    "body": {}
  },
  "response_data": {
    "status_code": 200,
    "body": {}
  },
  "draft_data": {
    "assertions": [
      {"type": "status_code", "expected": 200}
    ],
    "extractors": [
      {"name": "order_id", "path": "data.order_id"}
    ]
  },
  "status": "approved"
}
```

## 分析单条采集接口

已同步草稿：

```http
POST /api/v1/ai/browser-captures/1/entries/11/analyze?project_id=1
Content-Type: application/json

{
  "analysis_focus": ["semantics", "data_structure", "test_points", "risks", "automation"],
  "include_examples": true
}
```

未同步本地草稿：

```http
POST /api/v1/ai/browser-captures/analyze?project_id=1&environment_id=4
Content-Type: application/json

{
  "protocol": "http",
  "draft_data": {},
  "analysis_focus": ["semantics", "automation"],
  "include_examples": true
}
```

响应 `data`：

```json
{
  "summary": {
    "name": "查询订单列表",
    "purpose": "按查询条件分页返回订单",
    "business_domain": "订单",
    "operation_type": "query",
    "confidence": 0.92
  },
  "request": {
    "description": "分页与筛选参数",
    "fields": []
  },
  "response": {
    "description": "订单分页结果",
    "fields": []
  },
  "test_points": [],
  "risks": [],
  "automation": {
    "assertions": [],
    "extractors": [],
    "dependencies": [],
    "data_setup": [],
    "cleanup": []
  },
  "warnings": [],
  "model": "deepseek-chat",
  "analyzed_at": "2026-07-09T10:00:00+00:00"
}
```

后端在调用 AI 前会执行二次脱敏并限制样本长度。调用 AI 时会同时传入 `expected_output_contract` 和 `output_limits`，要求模型严格返回统一对象结构：`summary`、`request`、`response`、`test_points`、`risks`、`automation`、`warnings`，并限制测试点与风险数量，避免泛化输出过长导致 JSON 截断。AI 返回值会经过结构化 Schema 校验：缺省数组返回 `[]`，`confidence` 会被归一到 0 到 1，测试点和风险会按优先级排序；即使模型返回超量测试点或风险，后端也只保留前 6 条。已同步草稿的分析结果、模型版本和分析时间会保存到草稿记录。

`summary.purpose` 是前端概览区使用的简短展示文本，不承载原始 JSON 或完整分析内容。如果模型返回不合法 JSON、截断 JSON，或把结构化大块内容错误放入 `purpose`，后端会使用请求方法与路径生成兜底用途描述，并在 `warnings` 中返回归一化提示。

分析接口不是只把原始抓包 JSON 直接交给模型。后端会先从采集数据中构建高信号上下文：

- `request_context`：包含 method、URL、host、path、path segments、query 参数、请求头名称、请求体字段。
- `response_schema`：包含 HTTP 状态码、响应头、业务 code、响应 body 字段结构；即使数组为空，也会保留数组字段本身。
- `automation_hints`：包含鉴权依赖、query key、状态码断言、可提取的 ID 类字段。

上下文构建会兼容插件常见字段别名，例如 `source_url` / `sourceUrl`、`query_params` / `queryParams` / `query` / `params`、`request_headers` / `requestHeaders` / `headers`、`request_body` / `requestBody` / `body` / `bodyText`、`response_status` / `responseStatus` / `status_code` / `statusCode` / `status`、`response_headers` / `responseHeaders`、`response_body` / `responseBody` / `responseBodyText` / `bodyText`。如果响应 body 是 JSON 字符串，后端会先解析为结构化对象再生成 `response.fields`。

如果插件只采集到 HTML / 文本响应头，没有同步完整响应体，后端仍会根据 `Content-Type` 在 `response.fields` 中补充 `headers.Content-Type` 和 `body` 占位字段，便于前端明确展示“响应是 HTML 页面/文本内容”，而不是空响应结构。对于搜索类请求（例如 `/s?wd=...`、`/search?q=...`），后端会基于 query 参数生成更明确的 `summary.purpose`、测试点、风险和自动化断言兜底。

如果模型返回的 `request.fields`、`response.fields`、`automation.assertions`、`automation.dependencies` 等为空，后端会使用上述上下文进行确定性补全，并在 `warnings` 中标明补全来源。敏感请求头和响应字段示例会继续脱敏，例如 `Authorization`、`lingxi-auth`、`access_token`、`password` 等不会把真实值传给模型或返回给前端。

## 批量分析上下文依赖

用于插件多选草稿后的批量分析，重点识别接口之间的上下文传递依赖，例如：

- 登录接口响应 `access_token` 被后续请求 `Authorization` 请求头消费。
- 创建接口响应 `order_id` 被后续详情查询的 `query.order_id` 消费。
- 创建接口响应 `id` 被后续接口的请求体字段或路径片段消费。

```http
POST /api/v1/ai/browser-captures/1/batch-analyze?project_id=1
Content-Type: application/json

{
  "entry_ids": [11, 12, 13],
  "include_nodes": true,
  "include_suggestions": true
}
```

响应 `data`：

```json
{
  "capture_id": 1,
  "entry_ids": [11, 12, 13],
  "summary": {
    "entry_count": 3,
    "dependency_count": 2,
    "suggestion_count": 2
  },
  "nodes": [
    {
      "entry_id": 11,
      "name": "POST /api/orders",
      "protocol": "http",
      "method": "POST",
      "path": "/api/orders",
      "produces": [
        {
          "path": "body.data.order_id",
          "variable": "order_id",
          "target": "response",
          "type": "string",
          "sensitive": false,
          "value_preview": "ORD-001"
        }
      ],
      "consumes": [],
      "depends_on": [],
      "provides_to": [
        {
          "entry_id": 12,
          "variable": "order_id",
          "request_path": "query_params.order_id",
          "response_path": "body.data.order_id"
        }
      ]
    }
  ],
  "dependencies": [
    {
      "producer_entry_id": 11,
      "producer_name": "POST /api/orders",
      "producer_path": "/api/orders",
      "consumer_entry_id": 12,
      "consumer_name": "GET /api/orders/detail",
      "consumer_path": "/api/orders/detail",
      "response_path": "body.data.order_id",
      "request_path": "query_params.order_id",
      "request_target": "query",
      "variable": "order_id",
      "replacement": "{{order_id}}",
      "confidence": 0.96,
      "match_type": "exact_value",
      "reason": "响应字段值与后续请求字段值完全一致",
      "value_preview": "ORD-001"
    }
  ],
  "suggested_bindings": [
    {
      "consumer_entry_id": 12,
      "consumer_name": "GET /api/orders/detail",
      "request_target": "query",
      "request_path": "query_params.order_id",
      "replacement": "{{order_id}}",
      "source": {
        "producer_entry_id": 11,
        "producer_name": "POST /api/orders",
        "response_path": "body.data.order_id"
      },
      "confidence": 0.96
    }
  ],
  "warnings": []
}
```

匹配规则：

- `exact_value`：前序响应字段值与后序请求字段值完全一致，置信度最高。
- `contained_value`：前序响应字段值出现在后序请求字段值中，例如 token 出现在 `Bearer <token>` 中。
- `semantic_name`：前序响应 ID 类字段名与后序请求字段名一致，作为疑似依赖返回。

返回值不会暴露敏感字段真实值。敏感依赖仍会生成绑定关系，但 `value_preview` 会返回 `***`。

## 导入正式资产

```http
POST /api/v1/browser-captures/1/import?project_id=1
Content-Type: application/json

{
  "entry_ids": [11, 12, 13],
  "environment_id": 4,
  "create_environment_variables": true,
  "create_scenario": true,
  "scenario_draft_id": 8
}
```

响应会逐条返回成功、失败和重复项：

```json
{
  "code": 0,
  "message": "采集草稿导入完成",
  "data": {
    "capture_id": 1,
    "environment_id": 4,
    "scenario_draft_id": 8,
    "create_environment_variables": true,
    "environment_variables_created": 0,
    "success_count": 2,
    "failure_count": 1,
    "duplicate_count": 0,
    "results": [
      {
        "entry_id": 11,
        "ok": true,
        "status": "success",
        "asset_type": "http",
        "asset_id": 101,
        "name": "POST /api/orders"
      }
    ],
    "scenario": {
      "ok": true,
      "scenario_id": 20,
      "name": "浏览器采集场景 #1"
    }
  }
}
```

导入时：

- HTTP 草稿会创建正式 HTTP 用例。
- WebSocket 草稿会创建正式 WebSocket 用例。
- 已导入成功的草稿再次导入会返回 `status=duplicate`。
- `create_scenario=true` 时，后端会基于本次成功导入的正式资产创建一个基础场景；场景创建失败不会回滚已导入的正式用例。
