# 统一错误响应契约

所有普通 HTTP API 错误统一返回：

```json
{
  "code": 400,
  "message": "错误摘要",
  "data": {}
}
```

`code` 与 HTTP 状态码一致。`message` 用于页面提示，`data` 保留结构化错误上下文。

## 错误类型

| HTTP 状态码 | 场景 | `data` |
| --- | --- | --- |
| `400` | 业务参数、资源关系或执行前校验错误 | 原始业务错误；可能包含字段定位信息 |
| `401` | Token 缺失、无效或过期 | 原始认证错误 |
| `403` | 项目或功能权限不足 | 原始权限错误 |
| `404` | 路由或资源不存在 | 原始资源错误 |
| `409` | 名称、版本、幂等键或资源状态冲突 | 冲突上下文，例如 `current_version` |
| `422` | Pydantic 请求结构校验失败 | FastAPI 校验错误数组 |
| `503` | 数据库连接断开或外部依赖短暂不可用 | `{error, request_id}`，例如 `database_connection_lost` |
| `500` | 未处理的服务内部错误 | `{error, request_id}` |

业务错误中的结构化字段不会被丢弃。例如场景请求覆盖校验仍会返回
`dataset_id`、`record_id`、`step_id`、`target` 和 `path`，前端可据此定位控件。

## 参数校验

```json
{
  "code": 422,
  "message": "request validation failed",
  "data": [
    {
      "type": "int_parsing",
      "loc": ["query", "page"],
      "msg": "Input should be a valid integer",
      "input": "invalid"
    }
  ]
}
```

前端应优先使用 `loc` 定位字段，使用 `msg` 显示具体错误。

## 内部错误

未处理异常不会把堆栈、数据库信息或密钥返回客户端：

```json
{
  "code": 500,
  "message": "internal server error",
  "data": {
    "error": "internal_server_error",
    "request_id": "request-uuid"
  }
}
```

服务端会记录完整异常及 `request_id`。如果请求携带 `X-Request-ID`，响应会沿用该值；
否则服务端生成 UUID。500 响应头同时返回 `X-Request-ID`，用于日志定位。

## 短暂不可用

当 SQLAlchemy 报告 MySQL 断连、连接被重置、连接超时或连接池连接失效时，后端返回：

```json
{
  "code": 503,
  "message": "database temporarily unavailable",
  "data": {
    "error": "database_connection_lost",
    "request_id": "request-uuid"
  }
}
```

响应头包含 `X-Request-ID` 和 `Retry-After: 1`。服务端会 dispose 当前连接池，下一次请求重新建连；响应不会包含 SQL、连接串或堆栈。

## OpenAPI

公共 `ErrorResponse` Schema 已注册到 OpenAPI。所有接口统一声明
`400/401/403/404/409/422/500/503` 错误响应。

SSE 接口在成功建立连接后使用事件协议表达运行错误，不会在事件流中包装 JSON 错误响应。
