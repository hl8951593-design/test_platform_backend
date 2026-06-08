# 开发过程技术文档

本文档用于随着开发进程持续记录平台各功能模块、业务逻辑、数据权限、用户权限以及模块之间的关系。它不是一次性架构设计文档，而是后续开发时需要同步维护的业务技术账本。

## 1. 文档维护规则

每完成一个功能模块或对现有模块做重要调整时，需要同步更新本文档。

必须记录的内容包括：

- 功能模块的职责边界
- 涉及的数据表、核心字段和数据关系
- 主要业务流程
- 用户权限和数据权限规则
- 对外接口和对应接口文档
- 与其他模块的依赖关系
- 已实现能力、待实现能力和风险点

接口的详细调用方式应写入对应接口文档；本文档只记录模块关系、业务规则和权限规则。

## 2. 当前模块总览

| 模块 | 当前状态 | 主要职责 | 对应文档 |
| --- | --- | --- | --- |
| 用户与认证 | 已开始实现 | 用户注册、用户登录、JWT 签发、当前用户识别 | [认证接口文档](api_auth.md) |
| 项目管理 | 已开始实现 | 管理测试项目和项目成员 | [项目权限接口文档](api_project_permissions.md) |
| 环境管理 | 已开始实现 | 管理项目下不同环境的 base_url | [项目权限接口文档](api_project_permissions.md) |
| 接口管理 | 待实现 | 维护被测接口定义、请求参数、断言模板 | 待补充 |
| 测试用例 | 已开始实现 | 保存接口测试用例、断言配置、执行记录、批量执行 | [测试用例接口文档](api_test_cases.md) |
| 测试流程 | 待实现 | 编排多个用例或接口步骤并触发执行 | 待补充 |
| 执行记录 | 待实现 | 保存每次执行的步骤结果、请求响应、耗时和错误 | 待补充 |
| 测试报告 | 待实现 | 基于执行记录生成报告摘要和明细 | 待补充 |

## 3. 用户与认证模块

### 3.1 模块职责

用户与认证模块负责平台基础身份能力：

- 用户注册
- 用户登录
- 密码哈希存储
- JWT access token 和 refresh token 签发
- 根据 access token 识别当前登录用户
- 通过用户状态控制是否允许登录

当前认证方式为前后端分离 JWT 认证。前端登录成功后保存 `access_token`，后续请求通过 `Authorization: Bearer <access_token>` 访问需要认证的接口。

### 3.2 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/auth.py` | 注册、登录接口入口 |
| 依赖注入 | `app/api/v1/deps.py` | 数据库会话、当前用户解析 |
| Service | `app/services/user_service.py` | 注册和登录业务逻辑 |
| Repository | `app/repositories/user_repository.py` | 用户查询和创建 |
| Model | `app/models/user.py` | 用户表模型 |
| Schema | `app/schemas/auth.py` | 注册、登录请求结构 |
| Schema | `app/schemas/user.py` | 用户信息、token 返回结构 |
| Security | `app/core/security.py` | 密码哈希、JWT 创建和解析 |

### 3.3 数据模型

当前用户表为 `users`。

| 字段 | 说明 | 权限/业务含义 |
| --- | --- | --- |
| id | 用户主键 | JWT `sub` 使用该字段识别用户 |
| username | 用户名 | 展示名称，不作为登录凭证 |
| avatar | 头像地址 | 用户资料字段，可为空 |
| account | 登录账号 | 唯一，登录时使用 |
| password_hash | 密码哈希 | 只存哈希，不存明文密码 |
| phone | 手机号 | 唯一，当前注册必填 |
| email | 邮箱 | 唯一，当前注册必填 |
| is_active | 是否启用 | 为 `false` 时禁止登录 |
| created_at | 创建时间 | 审计和展示 |
| updated_at | 更新时间 | 审计和展示 |

### 3.4 业务流程

注册流程：

```text
接收注册参数
-> 校验 account、phone、email 是否已存在
-> 对 password 做哈希
-> 创建 users 记录
-> 返回用户基础信息
```

登录流程：

```text
接收 account 和 password
-> 根据 account 查询用户
-> 校验密码哈希
-> 校验 is_active
-> 签发 access_token 和 refresh_token
-> 返回 token 和用户基础信息
```

当前用户识别流程：

```text
读取 Authorization Bearer token
-> 解析 JWT
-> 从 sub 中获取 user_id
-> 查询 users 表
-> 返回当前用户对象
```

### 3.5 用户权限规则

当前已实现的用户权限规则：

| 规则 | 当前状态 | 说明 |
| --- | --- | --- |
| 未登录用户不能访问需要登录的接口 | 部分实现 | 已提供 `get_current_user` 依赖，后续受保护接口需要显式使用 |
| 禁用用户不能登录 | 已实现 | `is_active=false` 时登录返回 403 |
| 密码不可明文存储 | 已实现 | 使用 bcrypt 哈希 |
| 用户不能伪造身份 | 已实现基础能力 | 通过 JWT `sub` 识别用户 |

后端权限架构按以下四类设计：

| 权限类型 | 功能权限 | 数据权限 | 授权能力 |
| --- | --- | --- | --- |
| 管理员权限 | 拥有所有功能权限 | 拥有所有数据权限 | 可以增加所有角色权限 |
| 项目创建者 | 拥有自己创建项目的所有功能权限 | 拥有自己创建项目的所有数据权限 | 只能增加普通测试人员权限 |
| 普通测试人员 | 被项目创建者拉入项目后获得项目创建者赋予的权限 | 只能访问被授权项目内的数据 | 无角色授权能力，除非后续明确扩展 |
| 通用权限 | 同一用户可在不同项目中拥有不同身份 | 数据权限按所在项目身份计算 | 项目创建者也可以是其他项目的普通测试人员 |

权限关系说明：

- 管理员是全局最高权限，不受项目归属限制。
- 项目创建者只对自己创建的项目拥有完整控制权。
- 普通测试人员必须被项目创建者加入项目后，才拥有该项目下的权限。
- 普通测试人员的具体权限不是天然固定值，而是由项目创建者赋予。
- 通用权限表示用户身份具有项目上下文，同一个用户在 A 项目可以是创建者，在 B 项目可以是普通测试人员。

### 3.6 数据权限规则

当前已实现项目级数据权限底座。

后续必须采用项目维度的数据权限，并叠加管理员全局权限：

| 数据类型 | 建议权限边界 |
| --- | --- |
| 项目 | 管理员可访问所有项目；项目创建者可访问自己创建的项目；普通测试人员只能访问被加入的项目 |
| 环境 | 跟随项目权限 |
| 接口定义 | 跟随项目权限 |
| 测试用例 | 跟随项目权限 |
| 测试流程 | 跟随项目权限 |
| 执行记录 | 跟随项目权限，记录执行人 |
| 测试报告 | 跟随项目权限，必要时支持公开分享 |

已新增 `projects`、`project_members`、`project_member_permissions` 表记录项目归属、项目成员和普通测试人员的项目内权限。所有项目下属资源查询时，应校验当前用户在该项目中的身份和被授予的权限。

## 4. 项目管理模块

### 4.1 模块职责

项目管理模块用于组织测试资源。项目下应包含环境、接口定义、测试用例、测试流程、执行记录和报告。

当前已实现项目创建、项目列表、项目详情访问控制、项目更新、项目软删除、项目普通测试人员授权，以及项目环境管理。

项目归项目创建者所有。项目创建者可以修改、编辑、删除自己创建的项目；管理员可以管理所有项目。

### 4.2 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/projects.py` | 项目创建、查询、成员授权、权限编码查询 |
| API Router | `app/api/v1/routers/users.py` | 管理员权限设置 |
| 依赖注入 | `app/api/v1/deps.py` | 当前用户、管理员校验、项目权限依赖 |
| Model | `app/models/project.py` | 项目、项目成员、项目成员权限 |
| Repository | `app/repositories/project_repository.py` | 项目和成员权限数据访问 |
| Service | `app/services/project_service.py` | 项目业务逻辑 |
| Service | `app/services/permission_service.py` | 权限判断核心逻辑 |
| Schema | `app/schemas/project.py` | 项目和成员权限请求/响应结构 |
| Script | `scripts/sync_permission_schema.py` | 同步权限数据库结构 |
| Script | `scripts/set_admin.py` | 初始化或取消用户管理员权限 |

### 4.3 数据关系

```text
users
-> projects.created_by_id
-> project_members.user_id
-> project_members.added_by_id
projects
-> project_members.project_id
-> project_environments.project_id
project_members
-> project_member_permissions.member_id
projects
   -> environments
   -> api_definitions
   -> test_cases
   -> test_flows
   -> execution_records
   -> test_reports
```

### 4.4 已实现规则

| 问题 | 规则 |
| --- | --- |
| 项目是否必须有创建者 | 是，创建人默认为项目创建者 |
| 项目成员角色有哪些 | 管理员、项目创建者、普通测试人员 |
| 项目创建者能授权哪些角色 | 只能把用户加入自己创建的项目，并赋予普通测试人员权限 |
| 管理员能授权哪些角色 | 可以增加所有角色权限 |
| 删除项目是否物理删除 | 建议软删除 |
| 项目资源是否允许跨项目复用 | 初期不允许，后续可做复制功能 |

## 4.5 环境管理规则

同一个项目下允许存在多个环境，例如：

| 环境 | 用途 |
| --- | --- |
| prod | 生产环境 |
| uat | 用户验收测试环境 |
| test | 测试环境 |

当前已实现的数据表为 `project_environments`。

| 字段 | 说明 |
| --- | --- |
| project_id | 所属项目 |
| name | 环境名称，例如 prod、uat、test |
| base_url | 环境基础地址 |
| description | 环境描述 |
| is_default | 是否默认环境 |
| is_deleted | 是否软删除 |
| created_by_id | 环境创建人 |

环境权限规则：

- 管理员可以查看和管理所有项目环境。
- 项目创建者可以查看和管理自己创建项目下的所有环境。
- 普通测试人员需要 `environment:view` 才能查看项目环境。
- 普通测试人员需要 `environment:manage` 才能创建、修改、删除项目环境。
- 同一个项目只能有一个默认环境；设置新的默认环境时，旧默认环境会自动取消默认状态。

## 4.6 测试用例模块

测试用例模块用于保存、调试和执行项目下的接口测试用例。

当前已实现能力：

- 查询项目测试用例列表
- 新增测试用例
- 更新测试用例
- 执行已保存测试用例
- 执行未保存测试用例
- 按用户选择顺序批量执行测试用例
- 支持不同请求体格式
- 记录执行结果
- 读取环境变量并在请求中替换 `{{变量名}}`

当前代码位置：

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/test_cases.py` | 测试用例管理和执行接口 |
| Model | `app/models/test_case.py` | 测试用例和执行记录 |
| Repository | `app/repositories/test_case_repository.py` | 测试用例、执行记录、环境变量读取 |
| Service | `app/services/test_case_service.py` | 用例保存、执行、断言、批量执行 |
| Schema | `app/schemas/test_case.py` | 用例请求、断言、执行响应 |

数据表：

| 表 | 说明 |
| --- | --- |
| test_cases | 保存测试用例请求配置、断言、提取规则、创建人和最近执行状态 |
| test_case_executions | 保存每次执行的请求快照、响应快照、断言结果、执行人和耗时 |
| project_environment_variables | 保存项目环境变量，执行时可用于变量替换 |

测试用例请求体格式通过 `test_cases.body_type` 保存，当前支持：

| body_type | 说明 |
| --- | --- |
| none | 无请求体 |
| json | JSON 请求体 |
| form_urlencoded | `application/x-www-form-urlencoded` |
| multipart | `multipart/form-data` |
| raw_text | 原始文本 |
| raw_json | 原始 JSON |

业务关系：

```text
project
-> project_environments
-> project_environment_variables
-> test_cases
-> test_case_executions
```

权限规则：

- 查询测试用例需要 `case:view`。
- 新增和更新测试用例需要 `case:manage`。
- 执行已保存、未保存、批量测试用例需要 `test:execute`。
- 管理员和项目创建者默认拥有项目下全部测试用例权限。
- 普通测试人员只能在被加入项目且被授予对应权限后操作。

执行规则：

- 已保存测试用例执行：用例必须已存在于数据库。
- 未保存测试用例执行：用于前端编辑或新增后临时调试，不保存为用例，但保存执行记录。
- 批量执行：按前端传入的 `test_case_ids` 顺序执行。
- 执行时会关联项目、环境、环境变量、执行用户和断言结果。
- 用例最近执行时间和最近执行状态会回写到 `test_cases`。

## 5. 权限模型规划

### 5.1 权限类型

后端权限架构以用户图中的设计为准，分为管理员权限、项目创建者、普通测试人员、通用权限。

| 权限类型 | 权限定义 |
| --- | --- |
| 管理员权限 | 拥有所有功能权限和所有数据权限，可以增加所有角色权限 |
| 项目创建者 | 拥有自己创建项目的所有功能权限和所有数据权限，只能增加普通测试人员权限 |
| 普通测试人员 | 被项目创建者拉入项目后，拥有项目创建者赋予的权限 |
| 通用权限 | 同一个用户在不同项目中可以拥有不同权限身份 |

### 5.2 已实现数据建模

权限实现拆成全局管理员和项目成员权限两层：

| 数据表 | 作用 |
| --- | --- |
| users | 用户基础信息，`is_admin` 标识是否管理员 |
| projects | 项目信息，必须记录 `created_by` 表示项目创建者 |
| project_members | 项目成员关系，记录用户被加入哪个项目 |
| project_member_permissions | 普通测试人员在项目内被授予的具体功能权限 |

项目权限判断时，必须先判断管理员，再判断项目创建者，最后判断普通测试人员的项目成员权限。

### 5.3 建议权限判断方式

后续接口开发时，建议统一使用权限依赖函数，而不是在每个接口中手写权限判断。

示例设计：

```text
get_current_user()
-> is_admin(user)
-> require_project_access(project_id)
-> require_project_permission(project_id, permission_code)
```

判断顺序：

```text
如果用户是管理员
-> 直接拥有全部功能权限和数据权限
否则如果用户是项目创建者
-> 只能访问和管理自己创建的项目
否则如果用户是普通测试人员
-> 只能访问被加入项目中被授予的功能和数据
否则
-> 无权限
```

### 5.4 权限校验原则

- 管理员拥有所有功能权限和所有数据权限。
- 项目创建者只拥有自己创建项目的完整权限。
- 项目创建者只能给项目添加普通测试人员权限，不能新增管理员权限。
- 普通测试人员只能访问被加入项目的数据。
- 普通测试人员的功能权限来自项目创建者赋权。
- 同一用户在不同项目中权限可以不同。
- 所有项目下属资源接口都必须先校验项目访问权限。
- 修改、删除、执行类接口必须校验具体功能权限。
- 查询单条资源时，需要校验该资源所属项目是否对当前用户可见。
- 列表查询时，只返回当前用户有权访问的数据；管理员可返回全部数据。
- 执行记录必须保存执行人，方便审计。

## 6. 后续开发记录模板

新增功能模块时，按下面模板追加记录：

```markdown
## 模块名称

### 模块职责

### 当前代码位置

### 数据模型

### 业务流程

### 用户权限规则

### 数据权限规则

### 对外接口

### 与其他模块关系

### 已实现

### 待实现

### 风险点
```
## WebSocket 测试用例模块

WebSocket 测试用例与 HTTP 测试用例保持独立边界，不在 `test_cases` 中增加协议区分字段，也不复用 `test_case_executions`。

```text
websocket_test_cases
-> websocket_test_case_environments
-> websocket_test_case_executions
```

代码按 Router、Schema、Model、Repository、Service 独立拆分。执行器负责建立一次 WebSocket 会话、顺序发送消息、按数量接收消息、执行断言和提取变量。项目环境、环境变量以及 `case:view`、`case:manage`、`test:execute` 权限继续复用现有项目能力。详细接口和字段见 [WebSocket 测试用例接口技术文档](api_websocket_test_cases.md)。

测试工具 `scripts/websocket_mock_server.py` 是独立 FastAPI ASGI 应用，提供 echo、会话、连续推送、鉴权拒绝和主动关闭场景。`scripts/test_websocket_test_case_execution.py` 会启动真实 Uvicorn mock 服务完成集成验证。

WebSocket 调试使用独立长连接会话管理器 `app/services/websocket_debug_session_service.py`。它与自动化用例执行生命周期分离，由后台接收线程持续读取目标服务消息，通过 `session_id` 支持发送、增量查询、ping 心跳和主动断开。当前会话存储在单进程内存中，生产多实例部署需要粘性路由或专用连接 Worker。
