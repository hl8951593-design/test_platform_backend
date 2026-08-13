# 数据库连接与场景数据库动作

数据库能力用于自动化测试场景中的测试数据准备、数据库查询、业务断言、结果取值和清理。
当前支持 MySQL、PostgreSQL 和 MongoDB。连接按项目与执行环境隔离，基础路径为 `/api/v1`，
成功响应统一使用 `{code, message, data}`。

## 数据库连接接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/projects/{project_id}/environments/{environment_id}/database-connections` | `database:view` | 查询当前环境连接 |
| POST | 同上 | `database:manage` | 创建连接 |
| PUT | `.../database-connections/{connection_id}` | `database:manage` | 更新连接；`password` 为空时保留原密码 |
| DELETE | `.../database-connections/{connection_id}` | `database:manage` | 软删除连接并释放连接键 |
| POST | `.../database-connections/{connection_id}/test` | `database:manage` | 执行轻量连接测试 |

创建示例：

```json
{
  "name": "UAT PostgreSQL",
  "connection_key": "orders_db",
  "provider": "postgresql",
  "host": "db.example.com",
  "port": 5432,
  "database_name": "orders",
  "username": "test_runner",
  "password": "secret",
  "options": {"tls": true, "ssl_mode": "require"},
  "is_enabled": true,
  "allow_writes": false,
  "connect_timeout_ms": 5000,
  "statement_timeout_ms": 10000,
  "max_rows": 100
}
```

`provider` 允许 `mysql`、`postgresql`、`mongodb`。密码经平台密钥加密保存，任何读取响应只返回
`password_configured`，不返回密码或连接 URI。允许的 provider 选项为：

- 通用：`tls`。
- MySQL：`charset`、`ssl_ca`。
- PostgreSQL：`ssl_mode`、`ssl_root_cert`。
- MongoDB：`auth_source`、`replica_set`、`use_srv`。

默认阻止回环、私网、链路本地、保留地址等受保护网络目标。部署方必须通过
`DATABASE_EXECUTION_ALLOWED_HOSTS` 精确加入允许访问的内网数据库，或显式设置
`DATABASE_EXECUTION_ALLOW_PRIVATE_NETWORKS=true`。运行前会再次解析和校验目标，降低 DNS
重绑定风险。

## 场景数据库动作

数据库动作只能位于场景节点的 `before_actions[]` 或 `after_actions[]`，不能替代 HTTP/WebSocket
主用例。动作类型：

- `database_query`：只读查询；需要 `database:execute`。
- `database_execute`：测试数据写入或清理；同时需要 `database:execute`、`database:write`，且连接
  必须显式设置 `allow_writes=true`。

关系型数据库查询示例：

```json
{
  "id": "DB-QUERY-1",
  "kind": "database_query",
  "name": "查询订单状态",
  "config": {
    "connection_key": "orders_db",
    "sql": "SELECT id, status FROM orders WHERE id = :order_id",
    "parameters": {"order_id": "{{orderId}}"},
    "assertions": [
      {"type": "row_count", "operator": "eq", "expected": 1},
      {"type": "value", "path": "rows.0.status", "operator": "eq", "expected": "PAID"}
    ],
    "extractors": [
      {"name": "databaseOrderId", "path": "rows.0.id", "required": true, "masked": false}
    ],
    "retry_policy": {"max_attempts": 3, "interval_ms": 500},
    "timeout_ms": 10000,
    "max_rows": 100
  }
}
```

SQL 文本禁止直接插入 `{{variable}}`，变量必须放在 `parameters` 中并使用命名绑定。每次动作只允许
一条语句：查询只允许 `SELECT`，写动作只允许 `INSERT`、`UPDATE`、`DELETE`。不提供 DDL、存储
过程或多语句执行。查询结果包含 `columns`、`rows`、`row_count`、`scalar` 和 `truncated`；写结果
包含 `affected_rows`。

MongoDB 查询示例：

```json
{
  "connection_key": "document_db",
  "collection": "orders",
  "operation": "find_one",
  "filter": {"orderId": "{{orderId}}"},
  "projection": {"_id": 0, "orderId": 1, "status": 1},
  "assertions": [{"type": "exists", "operator": "eq"}],
  "extractors": [{"name": "databaseStatus", "path": "rows.0.status"}]
}
```

查询操作支持 `find`、`find_one`、`count_documents`、`aggregate`；写操作支持 `insert_one`、
`insert_many`、`update_one`、`update_many`、`delete_one`、`delete_many`。禁止 `$where`、`$function`、
`$accumulator`、`$out` 和 `$merge`。写操作不自动重试，避免重复副作用。

断言类型为 `row_count`、`value`、`exists`、`not_exists`、`affected_rows`；操作符为 `eq`、`ne`、
`gt`、`gte`、`lt`、`lte`、`contains`、`not_contains`。取值路径使用点路径和数字数组索引，例如
`rows.0.id`。提取值保持 JSON 原始类型，可通过场景变量链路传给后续 HTTP、WebSocket、脚本或
数据库动作；`masked=true` 时持久化快照和接口响应只显示 `***`。

保存场景时会同时固化非敏感 `connection_snapshot` 和稳定 `connection_key`，但正式运行仍按本次
执行环境解析连接，连接密码不会进入场景版本。

## 未保存动作调试

| 项目 | 内容 |
| --- | --- |
| Canonical | `POST /scenarios/actions/database/execute-unsaved?project_id={project_id}` |
| 兼容路径 | `POST /scenario-actions/database/execute-unsaved?project_id={project_id}` |
| 请求 | `environment_id`、`kind`、`config`、`input_values` |
| 结果 | `status`、`duration_ms`、`output`、`assertion_results`、`extracted_variables`、`attempt_history`、`error_message` |

执行和审计落在目标数据库之外的平台事务中。每次调试或正式场景执行会写入
`database_action_executions`，保存 provider、操作类型、语句指纹、脱敏请求/结果、断言、尝试历史、
状态和耗时。迁移 revision 为 `0045_database_test_actions`。
