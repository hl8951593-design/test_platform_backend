# 测试用例接口文档

本文档说明接口测试用例相关接口。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

## 数据关系

测试用例关联关系：

```text
project
-> environment
-> environment variables
-> test case
-> assertions
-> execution records
-> executed user
```

当前已实现：

- 测试用例列表
- 新增测试用例
- 更新测试用例
- 删除测试用例
- 异步执行已保存测试用例
- 执行未保存测试用例
- 异步批量执行测试用例
- 执行记录保存
- 环境变量维护

## Agent 执行工具补充契约

Agent 可通过 `testcase.execute_saved` 执行单个已保存 HTTP 用例，通过 `testcase.batch_execute` 批量执行已保存 HTTP 用例。两者都会复用正常执行服务并创建 `test_case_executions` 业务记录，记录来源字段为 `trigger_source=agent`、`agent_run_id`、`agent_tool_call_id`、`trigger_tool_name`；人工前端执行仍为 `trigger_source=manual` 且 Agent 关联字段为空。

Agent 可通过 `testcase.create_saved` 新增已保存 HTTP 用例，通过 `testcase.update_saved` 完整更新已保存 HTTP 用例，也可通过 `testcase.update_assertions` / `testcase.batch_update_assertions` 只保存断言。四类写工具都复用现有用例服务，要求 `case:manage` 权限，`side_effect_class=business_update`，`replay_policy=require_revalidation`，必须先进入人工审批；审批前不会写入 `test_cases`。创建工具输入为 `{"project_id":1,"case": TestCaseCreateRequest}`，完整更新工具输入为 `{"project_id":1,"test_case_id":7,"case": TestCaseUpdateRequest}`；单个断言更新输入为 `{"project_id":1,"test_case_id":7,"assertions":[AssertionConfig]}`，批量断言更新输入为 `{"project_id":1,"items":[{"test_case_id":7,"assertions":[AssertionConfig]}]}`。断言更新工具只替换 `assertions` 字段，保留 method、path、headers、query_params、body、extractors 和 retry_policy。审批通过并 resume 执行成功后，ToolCall 输出包含 `operation`、`project_id`、`test_case_id` 和 `test_case` 详情。

`testcase.query_project_cases` 返回项目下候选用例时，除 `http_test_cases` 明细外，还返回 `http_test_case_ids`，按当前 `project_id/environment_id` 过滤结果升序列出；同时返回 `http_batch_execute_input`，这是可直接传给 `testcase.batch_execute` 的推荐输入。Agent 或前端调试界面应使用该对象或 ID 数组选择批量执行目标，不要根据最小/最大 ID 推断连续区间。

`testcase.batch_execute` 在创建任何执行记录前会先校验 `test_case_ids` 全部存在且属于当前项目。只要存在无效 ID，接口返回 `422`，detail 形如：

```json
{
  "code": "agent_testcase_batch_invalid_ids",
  "message": "Batch execution contains case IDs that do not exist in this project.",
  "invalid_test_case_ids": [999],
  "valid_case_ids": [1, 2],
  "retry_batch_execute_input": {
    "project_id": 1,
    "environment_id": 1,
    "test_case_ids": [1, 2]
  },
  "repair_instruction": "Use retry_batch_execute_input exactly if the user still wants to run the valid cases. Do not infer case IDs from numeric ranges."
}
```

该失败不会留下部分 `queued` 执行记录，也不会触发后续真实请求。`retry_batch_execute_input` 只是下一次工具调用的建议输入，后端不会在失败响应里自动执行它。

## 查询测试用例列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases?project_id={project_id}&keyword={keyword}&environment_id={id}&page=1&page_size=20` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:view` 权限的普通测试人员 |
| 说明 | 分页返回项目下测试用例数据、创建人、最近执行时间、最近执行状态 |

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `keyword` | 空 | 按名称或描述模糊匹配 |
| `environment_id` | 空 | 匹配默认环境或多环境关联中的任一环境 |
| `page` | `1` | 页码，从 1 开始 |
| `page_size` | `20` | 每页数量，最大 200 |

响应 `data` 结构为：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

## 新增测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的普通测试人员 |
| 说明 | 前端传参，保存测试用例到数据库 |

请求示例：

```http
POST /api/v1/test-cases?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "查询用户信息",
  "description": "验证用户接口返回成功",
  "environment_id": 1,
  "method": "GET",
  "path": "/api/user/{{user_id}}",
  "headers": {
    "Authorization": "Bearer {{token}}"
  },
  "query_params": {},
  "body_type": "none",
  "body": null,
  "assertions": [
    {
      "type": "status_code",
      "expected": 200,
      "retry_on_failure": false
    },
    {
      "type": "json_equals",
      "path": "code",
      "expected": 0
    }
  ],
  "extractors": [],
  "retry_policy": {
    "enabled": true,
    "max_attempts": 3,
    "base_delay_ms": 500,
    "max_delay_ms": 10000,
    "jitter": "full",
    "respect_retry_after": true,
    "retry_network_errors": true,
    "retry_timeouts": true,
    "status_codes": [408, 429, 500, 502, 503, 504],
    "retry_unsafe_methods": false
  }
}
```

## 步骤级重试

重试封装在单次 HTTP 用例执行内部。场景、可视化 Flow 和批量执行只接收该步骤最终的
`passed`、`failed` 或 `error`，不参与 attempt 路由。

`retry_policy` 默认 `enabled=false`，旧用例保持单次执行。字段含义：

| 字段 | 说明 |
| --- | --- |
| `max_attempts` | 总尝试次数，包含首次请求，范围 1 到 10 |
| `base_delay_ms` / `max_delay_ms` | 指数退避基数和等待上限 |
| `jitter` | `full` 使用 Full Jitter，`none` 不使用随机抖动 |
| `respect_retry_after` | 429 等响应是否优先遵循 `Retry-After` 秒数或 HTTP 日期 |
| `retry_network_errors` | 是否重试连接等网络错误 |
| `retry_timeouts` | 是否重试连接、读取或场景 deadline 超时 |
| `status_codes` | 允许重试的 HTTP 状态码 |
| `retry_unsafe_methods` | 是否允许 POST/PATCH 等非幂等方法自动重试 |

默认仅对 GET、HEAD、OPTIONS、PUT、DELETE 自动重试。POST/PATCH 必须显式启用
`retry_unsafe_methods`，并建议同时使用业务幂等键。

响应分类：

- 网络错误和超时：按策略重试。
- `408`、`429`、`500`、`502`、`503`、`504`：默认可重试。
- `429`：启用时尊重 `Retry-After`。
- 其他 `4xx`：不自动重试，仍由断言判断测试结果，支持预期 400/404 等负向测试。
- 断言失败：默认不重试；只有失败断言全部设置 `retry_on_failure=true` 时才按轮询处理。

每次 attempt 使用隔离结果。执行顺序固定为：

```text
发送请求
-> 响应分类
-> 断言
-> 仅在断言全部通过后提取变量
```

失败 attempt 不会写入变量上下文，避免旧 token、ID 等污染下一次请求。

## 请求体格式

后端通过 `body_type` 字段支持不同请求格式。

| body_type | 说明 | body 示例 |
| --- | --- | --- |
| none | 无请求体，常用于 GET、HEAD、OPTIONS | `null` |
| json | JSON 对象或数组，后端会序列化为 JSON | `{"name": "demo"}` |
| form_urlencoded | `application/x-www-form-urlencoded` 表单 | `{"username": "demo", "password": "123456"}` |
| multipart | `multipart/form-data` 表单 | `{"file": {"filename": "a.txt", "content": "hello", "content_type": "text/plain"}}` |
| raw_text | 原始文本 | `"hello world"` |
| raw_json | 原始 JSON 字符串或对象 | `"{\"name\":\"demo\"}"` |

JSON 请求示例：

```json
{
  "method": "POST",
  "path": "/api/v1/users",
  "body_type": "json",
  "body": {
    "name": "demo"
  }
}
```

form-urlencoded 请求示例：

```json
{
  "method": "POST",
  "path": "/login",
  "body_type": "form_urlencoded",
  "body": {
    "username": "demo",
    "password": "123456"
  }
}
```

multipart 请求示例：

```json
{
  "method": "POST",
  "path": "/upload",
  "body_type": "multipart",
  "body": {
    "file": {
      "filename": "demo.txt",
      "content": "hello",
      "content_type": "text/plain"
    },
    "remark": "测试上传"
  }
}
```

raw 文本请求示例：

```json
{
  "method": "POST",
  "path": "/webhook",
  "body_type": "raw_text",
  "body": "plain text body"
}
```

## 更新测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases/{test_case_id}?project_id={project_id}` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的普通测试人员 |

## 删除测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases/{test_case_id}?project_id={project_id}` |
| 方法 | `DELETE` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的普通测试人员 |
| 成功响应 | `200`，返回“测试用例删除成功” |

删除采用以下数据规则：

- 历史执行记录继续保留，其中 `test_case_id` 置空。
- 已保存的场景版本继续使用完整用例快照执行，不依赖已删除的源用例。
- 如果任一可视化流程版本仍引用该用例，返回 `409 Conflict`，响应 `detail.flows` 给出流程名称；应先移除引用再删除。

## 执行已保存测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases/{test_case_id}/execute?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `test:execute` 权限的普通测试人员 |
| 成功响应 | HTTP `200`，返回最终状态为 `passed`、`failed` 或 `error` 的执行记录 |
| 说明 | 后端内部先创建执行记录并提交共享执行工作池，接口等待执行完成后按原结构返回结果；队列状态不暴露给前端 |

执行记录包含来源字段：人工通过该接口执行时 `trigger_source=manual`，`agent_run_id`、`agent_tool_call_id`、`trigger_tool_name` 为空；Agent 通过 `testcase.execute_saved` 或 `testcase.batch_execute` 工具触发执行时，业务执行记录会写入 `trigger_source=agent` 和对应 Agent 追踪字段，便于执行中心区分人工与 AI 来源。

可选参数：

| 参数 | 说明 |
| --- | --- |
| environment_id | 覆盖用例绑定环境 |

## 执行未保存测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases/execute-unsaved?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `test:execute` 权限的普通测试人员 |
| 说明 | 用于前端编辑或新增完用例但尚未保存时直接调试；当前仍为同步调试入口，后续迁移到任务载荷持久化 |

请求体结构和新增测试用例中的请求配置一致，但不包含 `name`、`description`。

## 批量执行测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases/batch-execute?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `test:execute` 权限的普通测试人员 |
| 成功响应 | HTTP `200`，返回多条最终状态为 `passed`、`failed` 或 `error` 的执行记录 |
| 说明 | 根据用户选择的测试用例 ID 创建多条执行记录并提交共享执行工作池，接口等待本批次完成后按原结构返回结果 |

批量执行返回的每条执行记录同样携带 `trigger_source`；人工批量执行为 `manual`，Agent 批量执行为 `agent` 并携带 `agent_run_id`、`agent_tool_call_id`、`trigger_tool_name=testcase.batch_execute`。

请求示例：

```json
{
  "test_case_ids": [3, 1, 2],
  "environment_id": 1
}
```

## 环境变量

测试用例可通过 `{{变量名}}` 引用环境变量，例如：

```text
{{token}}
{{user_id}}
```

维护环境变量接口：

```text
GET    /projects/{project_id}/environments/{environment_id}/variables
POST   /projects/{project_id}/environments/{environment_id}/variables
DELETE /projects/{project_id}/environments/{environment_id}/variables/{variable_id}
```

新增或更新环境变量示例：

```json
{
  "name": "token",
  "value": "example-token",
  "is_secret": true
}
```

## 断言类型

当前支持三类断言：

| type | 说明 |
| --- | --- |
| status_code | 校验响应状态码 |
| body_contains | 校验响应文本包含指定内容 |
| json_equals | 校验响应 JSON 指定路径等于预期值 |

`json_equals` 的 `path` 使用点分路径，例如：

```text
data.id
data.user.name
items.0.id
```

## 执行结果

执行接口会写入 `test_case_executions` 表，并返回：

| 字段 | 说明 |
| --- | --- |
| status | `passed`、`failed`、`error` |
| request_snapshot | 实际请求快照 |
| response_snapshot | 响应快照 |
| assertion_results | 断言结果 |
| attempt_history | 每次 attempt 的状态、重试原因、等待时间、状态码和断言摘要 |
| error_message | 错误信息 |
| duration_ms | 执行耗时 |

数据库字段由迁移 `0017_add_step_retry_policies.py` 引入。部署前必须执行
`alembic upgrade head`。
