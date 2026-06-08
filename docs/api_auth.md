# 认证接口文档

本文档说明认证相关接口的调用方式。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

线上或测试环境请将域名替换为对应环境的 `base_url`。

## 统一响应格式

成功响应统一返回：

```json
{
  "code": 0,
  "message": "操作结果说明",
  "data": {}
}
```

当参数校验失败时，FastAPI 会返回 `422`；业务错误会返回对应 HTTP 状态码和 `detail`。

## 用户注册

### 基本信息

| 项目 | 内容 |
| --- | --- |
| 接口 | `/auth/register` |
| 方法 | `POST` |
| Content-Type | `application/json` |
| 说明 | 创建新用户，密码会加密后保存 |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| username | string | 是 | 用户名，长度 1-64 |
| avatar | string/null | 否 | 头像地址，最长 512 |
| account | string | 是 | 登录账号，长度 3-64，唯一 |
| password | string | 是 | 登录密码，长度 6-128 |
| phone | string | 是 | 手机号，长度 5-32，唯一 |
| email | string | 是 | 邮箱，需符合邮箱格式，唯一 |

### 请求示例

```http
POST /api/v1/auth/register HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{
  "username": "测试用户",
  "avatar": "https://example.com/avatar.png",
  "account": "test_user",
  "password": "123456",
  "phone": "13800138000",
  "email": "test@example.com"
}
```

### 成功响应

```json
{
  "code": 0,
  "message": "注册成功",
  "data": {
    "id": 1,
    "username": "测试用户",
    "avatar": "https://example.com/avatar.png",
    "account": "test_user",
    "phone": "13800138000",
    "email": "test@example.com",
    "is_active": true,
    "created_at": "2026-06-02T10:00:00"
  }
}
```

### 常见错误

| 状态码 | 场景 | 返回说明 |
| --- | --- | --- |
| 400 | 账号、手机号或邮箱已存在 | `账号、手机号或邮箱已存在` |
| 422 | 请求参数格式不合法 | FastAPI 参数校验错误详情 |

## 用户登录

### 基本信息

| 项目 | 内容 |
| --- | --- |
| 接口 | `/auth/login` |
| 方法 | `POST` |
| Content-Type | `application/json` |
| 说明 | 使用账号和密码登录，成功后返回 access token、refresh token 和用户信息 |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| account | string | 是 | 登录账号，长度 3-64 |
| password | string | 是 | 登录密码，长度 6-128 |

### 请求示例

```http
POST /api/v1/auth/login HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{
  "account": "test_user",
  "password": "123456"
}
```

### 成功响应

```json
{
  "code": 0,
  "message": "登录成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "user": {
      "id": 1,
      "username": "测试用户",
      "avatar": "https://example.com/avatar.png",
      "account": "test_user",
      "phone": "13800138000",
      "email": "test@example.com",
      "is_active": true,
      "created_at": "2026-06-02T10:00:00"
    }
  }
}
```

### 后续请求携带 token

登录成功后，前端或接口调用方应使用 `access_token` 访问需要登录的接口：

```http
Authorization: Bearer <access_token>
```

示例：

```http
GET /api/v1/some-protected-api HTTP/1.1
Host: 127.0.0.1:8000
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 常见错误

| 状态码 | 场景 | 返回说明 |
| --- | --- | --- |
| 401 | 账号不存在或密码错误 | `账号或密码错误` |
| 403 | 用户已被禁用 | `用户已被禁用` |
| 422 | 请求参数格式不合法 | FastAPI 参数校验错误详情 |

### Token 有效期

| Token | 默认有效期 | 用途 |
| --- | --- | --- |
| access_token | 30 分钟 | 访问需要认证的接口 |
| refresh_token | 7 天 | 后续刷新 access token 使用 |

默认有效期来自环境变量：

```text
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

## 刷新访问令牌

### 基本信息

| 项目 | 内容 |
| --- | --- |
| 接口 | `/auth/refresh` |
| 方法 | `POST` |
| Content-Type | `application/json` |
| 说明 | 使用 refresh token 换取新的 access token 和 refresh token |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| refresh_token | string | 是 | 登录接口返回的 refresh token |

### 请求示例

```http
POST /api/v1/auth/refresh HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### 成功响应

```json
{
  "code": 0,
  "message": "令牌刷新成功",
  "data": {
    "access_token": "new-access-token",
    "refresh_token": "new-refresh-token",
    "token_type": "bearer",
    "user": {
      "id": 1,
      "username": "测试用户",
      "avatar": "https://example.com/avatar.png",
      "account": "test_user",
      "phone": "13800138000",
      "email": "test@example.com",
      "is_active": true,
      "is_admin": false,
      "created_at": "2026-06-02T10:00:00"
    }
  }
}
```

### 常见错误

| 状态码 | 场景 | 返回说明 |
| --- | --- | --- |
| 401 | refresh token 无效、过期，或传入 access token | `刷新令牌无效` |
| 403 | 用户已被禁用 | `用户已被禁用` |
| 422 | 请求参数格式不合法 | FastAPI 参数校验错误详情 |
