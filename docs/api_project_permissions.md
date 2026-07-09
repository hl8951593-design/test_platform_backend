# 项目权限接口文档

本文档说明项目权限底座相关接口。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

## 权限模型

后端权限架构分为四类：

| 权限类型 | 说明 |
| --- | --- |
| 管理员权限 | 拥有所有功能权限和所有数据权限，可以设置其他用户为管理员 |
| 项目创建者 | 创建项目后，自动拥有该项目所有功能权限和数据权限 |
| 普通测试人员 | 被项目创建者或管理员加入项目后，拥有被授予的项目内权限 |
| 通用权限 | 同一用户在不同项目中可以拥有不同身份 |

权限判断顺序：

```text
管理员
-> 项目创建者
-> 普通测试人员项目内权限
-> 无权限
```

## 查询项目权限编码

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/permissions` |
| 方法 | `GET` |
| 说明 | 查询普通测试人员可被授予的项目内功能权限编码 |

请求示例：

```http
GET /api/v1/projects/permissions HTTP/1.1
Host: 127.0.0.1:8000
```

当前普通测试人员可被授予的插件相关权限：

| 权限编码 | 说明 |
| --- | --- |
| `capture:view` | 查看浏览器采集批次和草稿 |
| `capture:manage` | 创建、同步、修改、删除浏览器采集批次和草稿 |
| `capture:import` | 将采集草稿导入正式 HTTP/WebSocket 用例 |
| `ai:analyze` | 使用采集分析、场景生成和执行失败诊断等 AI 分析能力 |

## 创建项目

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 当前登录用户创建项目后，自动成为项目创建者 |

请求示例：

```http
POST /api/v1/projects HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "测试平台项目",
  "description": "用于接口自动化测试"
}
```

成功响应会直接返回项目页可展示的项目对象：

```json
{
  "code": 0,
  "message": "项目创建成功",
  "data": {
    "id": 1,
    "name": "测试平台项目",
    "description": "用于接口自动化测试",
    "created_by_id": 1,
    "owner_name": "当前用户",
    "status": "active",
    "is_active": true,
    "is_deleted": false,
    "created_at": "2026-07-08 10:00:00",
    "updated_at": "2026-07-08 10:00:00",
    "members": [
      {
        "id": 1,
        "name": "当前用户",
        "role": "负责人"
      }
    ],
    "stats": {
      "api_case_count": 0,
      "http_test_case_count": 0,
      "websocket_test_case_count": 0,
      "test_case_count": 0,
      "scenario_count": 0,
      "plan_count": 0,
      "run_count": 0,
      "pass_rate": 0,
      "coverage_rate": 0,
      "automation_rate": 0,
      "defect_count": 0,
      "last_run_at": null,
      "last_execution_status": null,
      "risk_score": 0,
      "ai_recommendations": [],
      "team_activity": []
    }
  }
}
```

## 查询当前用户可见项目列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 管理员可查看全部项目；项目创建者可查看自己创建的项目；普通测试人员可查看被加入的项目 |

响应为 `{code,message,data}`，其中 `data` 是项目页项目对象数组。每个项目对象会补齐
`owner_name`、`status`、`is_active`、`members` 和 `stats`，前端不需要再从其他接口拼装项目卡片统计。

性能边界：`GET /projects` 是项目管理页热路径，后端使用批量读模型一次性装配列表项的
owner、members 和 stats。列表接口不得对每个项目逐个调用单项目 stats 构建器，否则项目数和执行记录数增长后会退化为 N+1 慢查询。成员读取依赖
`0036_project_list_query_indexes` 中的 `project_members(project_id,is_active,id)` 索引。该 GET
接口接入后端 10 秒短 TTL 读穿透缓存，缓存 key 包含 DB bind 和用户身份；项目、成员、环境、
HTTP/WebSocket 用例等会影响项目统计的写操作会清理相关缓存。

`stats` 字段口径：

| 字段 | 说明 |
| --- | --- |
| `api_case_count` / `test_case_count` | HTTP + WebSocket 用例总数 |
| `http_test_case_count` | HTTP 测试用例数 |
| `websocket_test_case_count` | WebSocket 测试用例数 |
| `scenario_count` | 未删除测试场景数 |
| `plan_count` | 未删除测试计划数 |
| `run_count` | HTTP、WebSocket、场景和计划执行总数 |
| `pass_rate` | 执行通过率，0-100 整数 |
| `coverage_rate` | 当前后端可计算的场景覆盖参考值，0-100 整数 |
| `automation_rate` | 有用例且已有场景时返回 100，否则 0 |
| `defect_count` | 项目缺陷数 |
| `last_run_at` | 最近一次执行时间，无执行时为 `null` |
| `last_execution_status` | 最近执行状态中文展示值，例如 `通过`、`失败` |
| `risk_score` | 基于通过率、缺陷数和覆盖率的项目风险参考分 |
| `ai_recommendations` | 后端根据当前统计生成的建议列表 |
| `team_activity` | 最近执行动态列表 |

## 查询项目详情

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 管理员、项目创建者、被加入项目的普通测试人员可访问 |

## 更新项目

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 只有管理员或项目创建者可以修改项目 |

请求示例：

```http
PUT /api/v1/projects/1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "测试平台项目",
  "description": "项目说明"
}
```

## 删除项目

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}` |
| 方法 | `DELETE` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 只有管理员或项目创建者可以删除项目；当前为软删除 |

## 添加普通测试人员权限

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}/members` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 管理员或项目创建者将用户加入项目，并授予项目内功能权限 |

请求示例：

```http
POST /api/v1/projects/1/members HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "user_id": 2,
  "permission_codes": [
    "project:view",
    "api:view",
    "case:view",
    "capture:view",
    "capture:manage",
    "capture:import",
    "ai:analyze",
    "defect:view",
    "defect:create",
    "test:execute",
    "report:view"
  ]
}
```

普通测试人员可被授予的权限不包含项目所有权类权限，因此不能被授予：

```text
project:update
project:delete
project:members:manage
```

## 查询项目环境列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}/environments` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:view` 权限的普通测试人员 |
| 说明 | 查询项目下的环境，例如 prod、uat、test |

## 创建项目环境

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}/environments` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 为项目创建一个环境，同一个项目下可存在多个环境 |

请求示例：

```http
POST /api/v1/projects/1/environments HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "uat",
  "base_url": "https://uat.example.com",
  "description": "用户验收测试环境",
  "is_default": false
}
```

## 更新项目环境

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}/environments/{environment_id}` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |

## 删除项目环境

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects/{project_id}/environments/{environment_id}` |
| 方法 | `DELETE` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 当前为软删除 |

## 设置用户管理员权限

| 项目 | 内容 |
| --- | --- |
| 接口 | `/users/{user_id}/admin` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <admin_access_token>` |
| 说明 | 只有管理员可以设置其他用户是否为管理员 |

请求示例：

```http
PUT /api/v1/users/2/admin HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <admin_access_token>
Content-Type: application/json

{
  "is_admin": true
}
```

## 初始化第一个管理员

系统第一次使用时，还没有管理员 token，可通过本地脚本按账号设置第一个管理员：

```powershell
python scripts/set_admin.py test_user
```

取消管理员：

```powershell
python scripts/set_admin.py test_user --unset
```
