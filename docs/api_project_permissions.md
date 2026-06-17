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

## 查询当前用户可见项目列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/projects` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 说明 | 管理员可查看全部项目；项目创建者可查看自己创建的项目；普通测试人员可查看被加入的项目 |

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
