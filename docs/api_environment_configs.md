# 环境配置接口文档

本文档说明环境配置相关接口的调用方式。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

环境配置属于项目，由当前登录用户创建，可维护环境变量，并可绑定到测试用例。所有接口均需要携带登录后的 `access_token`：

```http
Authorization: Bearer <access_token>
```

## 数据关系

环境配置关联关系：

```text
user
-> project
-> environment config
-> environment variables
-> test case
-> test execution
```

字段关系说明：

| 关系 | 说明 |
| --- | --- |
| environment_config.project_id | 环境配置所属项目 |
| environment_config.created_by_id | 创建环境配置的用户 |
| environment_variable.environment_id | 环境变量所属环境配置 |
| test_case.environment_id | 测试用例绑定的环境配置 |
| test_case_execution.environment_id | 执行记录使用的环境配置 |

## 统一响应格式

成功响应统一返回：

```json
{
  "code": 0,
  "message": "操作结果说明",
  "data": {}
}
```

参数校验、权限和业务错误统一返回 `{code,message,data}`。详细规则见
[统一错误响应契约](api_errors.md)。

## 查询项目环境配置列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:view` 权限的普通测试人员 |
| 说明 | 查询项目下的环境配置列表，返回所属项目、创建用户、变量列表和绑定用例数量 |

### 请求示例

```http
GET /api/v1/environment-configs?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
```

### 成功响应

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": 1,
      "project_id": 1,
      "name": "uat",
      "base_url": "https://uat.example.com",
      "description": "用户验收测试环境",
      "is_default": true,
      "is_deleted": false,
      "created_by_id": 1,
      "created_at": "2026-06-03T10:00:00",
      "updated_at": "2026-06-03T10:00:00",
      "project": {
        "id": 1,
        "name": "测试平台项目"
      },
      "created_by": {
        "id": 1,
        "username": "测试用户",
        "account": "test_user"
      },
      "variables": [
        {
          "id": 1,
          "environment_id": 1,
          "name": "token",
          "value": "example-token",
          "is_secret": true,
          "created_at": "2026-06-03T10:00:00",
          "updated_at": "2026-06-03T10:00:00"
        }
      ],
      "test_case_count": 3
    }
  ]
}
```

## 创建环境配置

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| Content-Type | `application/json` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 为项目创建环境配置；当 `is_default=true` 时，会将同项目下其他环境配置取消默认 |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | string | 是 | 环境名称，长度 1-64，同项目下唯一，例如 `dev`、`test`、`uat`、`prod` |
| base_url | string | 是 | 环境基础地址，长度 1-512 |
| description | string/null | 否 | 环境说明 |
| is_default | boolean | 否 | 是否默认环境，默认 `false` |

### 请求示例

```http
POST /api/v1/environment-configs?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "uat",
  "base_url": "https://uat.example.com",
  "description": "用户验收测试环境",
  "is_default": true
}
```

## 查询环境配置详情

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:view` 权限的普通测试人员 |
| 说明 | 查询单个环境配置详情，包含项目、创建用户、变量列表和绑定用例数量 |

### 请求示例

```http
GET /api/v1/environment-configs/1?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
```

## 更新环境配置

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}?project_id={project_id}` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <access_token>` |
| Content-Type | `application/json` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 更新环境名称、基础地址、说明和默认状态 |

### 请求示例

```http
PUT /api/v1/environment-configs/1?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "uat",
  "base_url": "https://uat-api.example.com",
  "description": "用户验收测试环境",
  "is_default": true
}
```

## 删除环境配置

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}?project_id={project_id}` |
| 方法 | `DELETE` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 当前为软删除；删除后该环境配置不再出现在列表和详情中 |

### 请求示例

```http
DELETE /api/v1/environment-configs/1?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
```

## 查询环境变量

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}/variables?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:view` 权限的普通测试人员 |
| 说明 | 查询环境配置下的变量列表 |

### 请求示例

```http
GET /api/v1/environment-configs/1/variables?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
```

## 新增或更新环境变量

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}/variables?project_id={project_id}` |
| 方法 | `POST` |
| 认证 | `Authorization: Bearer <access_token>` |
| Content-Type | `application/json` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 按变量名 upsert；同一环境配置下变量名唯一 |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | string | 是 | 变量名，长度 1-64，例如 `token`、`user_id` |
| value | string | 是 | 变量值 |
| is_secret | boolean | 否 | 是否敏感变量，默认 `false` |

### 请求示例

```http
POST /api/v1/environment-configs/1/variables?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "token",
  "value": "example-token",
  "is_secret": true
}
```

## 删除环境变量

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}/variables/{variable_id}?project_id={project_id}` |
| 方法 | `DELETE` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `environment:manage` 权限的普通测试人员 |
| 说明 | 删除指定环境变量 |

### 请求示例

```http
DELETE /api/v1/environment-configs/1/variables/2?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
```

## 查询绑定环境配置的用例

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/{environment_id}/test-cases?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | 管理员、项目创建者，或拥有 `case:view` 权限的普通测试人员 |
| 说明 | 查询当前绑定到该环境配置的测试用例 |

### 请求示例

```http
GET /api/v1/environment-configs/1/test-cases?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
```

### 成功响应

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": 3,
      "project_id": 1,
      "environment_id": 1,
      "name": "查询用户信息",
      "method": "GET",
      "path": "/api/user/{{user_id}}",
      "created_by_id": 1,
      "last_execution_status": "passed",
      "last_executed_at": "2026-06-03T11:00:00",
      "created_at": "2026-06-03T10:00:00",
      "updated_at": "2026-06-03T10:30:00"
    }
  ]
}
```

## 绑定或解绑用例环境配置

| 项目 | 内容 |
| --- | --- |
| 接口 | `/environment-configs/test-cases/{test_case_id}/environment?project_id={project_id}` |
| 方法 | `PUT` |
| 认证 | `Authorization: Bearer <access_token>` |
| Content-Type | `application/json` |
| 权限 | 管理员、项目创建者，或拥有 `case:manage` 权限的普通测试人员 |
| 说明 | 修改测试用例绑定的环境配置；传 `null` 表示解绑 |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| environment_id | integer/null | 是 | 环境配置 ID；传 `null` 表示解绑 |

绑定示例：

```http
PUT /api/v1/environment-configs/test-cases/3/environment?project_id=1 HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "environment_id": 1
}
```

解绑示例：

```json
{
  "environment_id": null
}
```

## 环境变量引用

测试用例请求配置中可以通过 `{{变量名}}` 引用环境变量，例如：

```text
{{token}}
{{user_id}}
```

执行测试用例时，后端会根据测试用例绑定的 `environment_id`，读取对应环境配置和环境变量，并渲染到请求路径、请求头、Query 参数和请求体中。

示例：

```json
{
  "path": "/api/user/{{user_id}}",
  "headers": {
    "Authorization": "Bearer {{token}}"
  }
}
```

## 常见错误

| 状态码 | 场景 | 返回说明 |
| --- | --- | --- |
| 400 | 创建或更新同项目下重名环境配置 | 数据库唯一约束错误 |
| 401 | 未登录或 token 无效 | `认证凭证无效` |
| 403 | 当前用户无项目或功能权限 | `无功能操作权限` |
| 404 | 项目、环境配置、环境变量或测试用例不存在 | 对应资源不存在 |
| 422 | 请求参数格式不合法 | FastAPI 参数校验错误详情 |

## 权限汇总

| 功能 | 所需权限 |
| --- | --- |
| 查询环境配置列表和详情 | `environment:view` |
| 创建、更新、删除环境配置 | `environment:manage` |
| 查询环境变量 | `environment:view` |
| 新增、更新、删除环境变量 | `environment:manage` |
| 查询绑定环境配置的测试用例 | `case:view` |
| 绑定或解绑用例环境配置 | `case:manage` |

管理员和项目创建者默认拥有项目内全部权限。
