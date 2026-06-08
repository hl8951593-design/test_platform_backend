# 接口测试用例多环境保存接口文档

本文档补充说明测试用例创建、编辑时选择多个环境进行保存的接口约定。基础路径：

```text
http://127.0.0.1:8000/api/v1
```

## 数据关系

测试用例与环境由原来的单环境字段扩展为“默认执行环境 + 多环境关联”：

```text
projects
-> project_environments
-> test_cases.environment_id
-> test_case_environments
```

字段含义：

| 字段 | 说明 |
| --- | --- |
| environment_id | 默认执行环境，兼容旧前端和单环境执行逻辑 |
| environment_ids | 用例关联的环境列表，用于前端展示和多环境保存 |
| test_case_environments | 用例与环境的多对多关联表 |

兼容规则：

- 前端只传 `environment_id` 时，后端会自动生成一个关联环境。
- 前端同时传 `environment_id` 和 `environment_ids` 时，`environment_id` 作为默认执行环境，并确保出现在 `environment_ids` 中。
- 前端只传 `environment_ids` 时，后端默认取第一个环境作为 `environment_id`。
- `environment_ids` 会去重，并校验所有环境都属于当前 `project_id`。

## 新增测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的项目成员 |
| 说明 | 创建测试用例并保存多个可用环境 |

请求示例：

```json
{
  "name": "查询统计接口",
  "description": "同一个测试用例可在 test、uat 环境运行",
  "environment_id": 1,
  "environment_ids": [1, 2],
  "method": "GET",
  "path": "/finance/api/statistics",
  "headers": {
    "Authorization": "Bearer {{access_token}}"
  },
  "query_params": {
    "start_date": "2026-05-31",
    "end_date": "2026-06-04"
  },
  "body_type": "none",
  "body": null,
  "assertions": [],
  "extractors": []
}
```

响应示例：

```json
{
  "code": 0,
  "message": "测试用例创建成功",
  "data": {
    "id": 2,
    "project_id": 1,
    "environment_id": 1,
    "environment_ids": [1, 2],
    "name": "查询统计接口",
    "method": "GET",
    "path": "/finance/api/statistics",
    "last_execution_status": null,
    "created_at": "2026-06-04 09:10:00",
    "updated_at": "2026-06-04 09:10:00"
  }
}
```

## 编辑测试用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases/{test_case_id}?project_id={project_id}` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的项目成员 |
| 说明 | 更新测试用例基础信息，并替换该用例的环境关联列表 |

请求示例：

```json
{
  "name": "查询统计接口",
  "description": "调整为 test、uat、pre 三个环境",
  "environment_id": 1,
  "environment_ids": [1, 2, 3],
  "method": "GET",
  "path": "/finance/api/statistics",
  "headers": {
    "Authorization": "Bearer {{access_token}}"
  },
  "query_params": {
    "start_date": "2026-05-31",
    "end_date": "2026-06-04"
  },
  "body_type": "none",
  "body": null,
  "assertions": [],
  "extractors": []
}
```

更新规则：

- 后端会先删除当前用例旧的环境关联，再写入新的 `environment_ids`。
- `environment_id` 仍然保存在 `test_cases` 表中，作为默认执行环境。
- 执行保存后的单条用例时，如果接口没有额外传 `environment_id`，使用默认执行环境。
- 批量执行时，如果请求体传了 `environment_id`，以批量执行请求中的环境为准。

## 查询测试用例列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/test-cases?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:view` 权限的项目成员 |
| 说明 | 返回测试用例列表，并携带 `environment_ids` 供前端展示 |

响应字段：

| 字段 | 说明 |
| --- | --- |
| environment_id | 默认环境 ID |
| environment_ids | 当前用例已关联的所有环境 ID |

## 数据库迁移

本功能新增迁移：

```text
migrations/versions/0008_create_test_case_environments.py
```

执行命令：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

如果历史数据库已经有业务表但没有 Alembic 版本记录，需要先标记旧结构版本，再执行最新迁移：

```powershell
.\.venv\Scripts\python.exe -m alembic stamp 0007_environment_indexes
.\.venv\Scripts\python.exe -m alembic upgrade head
```

缺少 `test_case_environments` 表时，测试用例列表会在加载 `environment_ids` 时出现数据库 500 错误。执行上述迁移后即可恢复。
