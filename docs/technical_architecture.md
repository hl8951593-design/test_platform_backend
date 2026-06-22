# 自动化测试平台后端技术架构文档

文档入口、权威范围和维护要求见 [文档索引与维护规范](README.md)。

开发过程中的模块关系、业务逻辑、数据权限和用户权限记录见 [开发过程技术文档](development_technical_notes.md)。

项目权限底座接口见 [项目权限接口文档](api_project_permissions.md)。

测试用例接口见 [测试用例接口文档](api_test_cases.md)。

WebSocket 测试用例接口见 [WebSocket 测试用例接口技术文档](api_websocket_test_cases.md)。

场景组合与实时事件接口见 [场景组合接口文档](api_scenarios.md)。

缺陷跟踪接口见 [缺陷跟踪接口文档](api_defects.md)。

MinIO 图片附件接口和部署配置见 [媒体存储接口文档](api_media.md)。

场景从触发到 dataset record、步骤、变量和事件持久化的完整关系见
[场景组合执行流程图谱](scenario_execution_graph.md)。

场景版本只保存 `nodes[]`：每个节点绑定一个 HTTP/WebSocket 主用例，并以
`before_actions[]`、`after_actions[]` 显式表达动作位置。执行器按节点顺序展开为
`before_actions -> test_case -> after_actions`；前置或主用例失败不会跳过本节点后置动作，
后置动作逐项尝试，失败仍如实计入运行终态。旧 `steps/execution_phase` 只允许通过
`0020_scenario_nodes` 一次性迁移，运行时没有兼容分支。

## 1. 项目定位

本项目是一个基于 FastAPI 的自动化测试平台后端，主要面向接口自动化测试场景。

平台核心目标不是简单封装 pytest 或 Allure，而是自研一套接口测试用例管理、测试流程编排、执行引擎和测试报告体系。用户可以在前端维护接口、组合测试流程、选择环境并触发执行，后端负责执行请求、处理变量、执行断言、记录结果并生成报告数据。

## 2. 总体技术选型

| 模块 | 技术选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI | 提供 REST API，支持 OpenAPI 文档和类型校验 |
| ASGI 服务 | Uvicorn | 本地开发和服务启动 |
| 数据库 | MySQL | 保存用户、项目、接口、用例、流程、缺陷、执行记录和报告 |
| ORM | SQLAlchemy 2.x | 负责数据库模型和查询 |
| 数据库迁移 | Alembic | 管理表结构版本演进 |
| 数据校验 | Pydantic v2 | 定义请求和响应数据结构 |
| 认证 | JWT | 支持前后端分离认证 |
| 密码加密 | passlib[bcrypt] | 用户密码哈希存储 |
| 缓存/临时状态 | Redis | 保存 token 状态、任务状态、临时变量和限流数据 |
| 对象存储 | MinIO（S3 兼容） | 私有保存缺陷截图等二进制媒体，MySQL 只保存对象键和元数据 |
| HTTP 执行引擎 | httpx | 执行接口测试步骤 |
| 异步任务 | FastAPI BackgroundTasks（当前）/ 独立 Worker（演进目标） | 当前场景手工执行在响应后继续运行；生产可靠性阶段迁移到独立 Worker |
| 实时事件 | SSE + MySQL 持久化事件表 | 支持鉴权请求头、Last-Event-ID 重放、心跳和终态关闭 |
| 测试报告 | 自研 | 基于执行记录生成平台内置报告 |
| 配置管理 | pydantic-settings + .env | 管理环境配置 |
| 日志 | Python logging 或 loguru | 记录系统日志和执行日志 |

## 3. 架构分层

建议项目逐步演进为如下结构：

```text
app/
├── main.py
├── core/
│   ├── config.py
│   ├── security.py
│   └── redis.py
├── db/
│   ├── session.py
│   └── base.py
├── api/
│   └── v1/
│       ├── routers/
│       └── deps.py
├── models/
│   ├── user.py
│   ├── project.py
│   ├── environment.py
│   ├── api_case.py
│   ├── test_flow.py
│   └── test_report.py
├── schemas/
├── services/
├── repositories/
├── runner/
│   ├── flow_runner.py
│   ├── step_executor.py
│   ├── request_builder.py
│   ├── assertion_engine.py
│   ├── extractor.py
│   └── report_recorder.py
├── tasks/
│   └── test_tasks.py
└── utils/
```

### 3.1 API 层

API 层负责对外提供 HTTP 接口，包括用户认证、项目管理、环境管理、接口管理、用例管理、流程管理、缺陷跟踪、执行管理和报告查询。

API 层只做参数接收、权限校验和响应封装，不直接写复杂业务逻辑。

### 3.2 Service 层

Service 层负责业务编排，例如创建测试流程、触发执行任务、生成报告摘要、校验用户权限等。

Service 层可以调用 Repository、Runner、Redis 和任务队列。

### 3.3 Repository 层

Repository 层负责数据库访问，封装常见 CRUD 和复杂查询，避免 SQLAlchemy 查询逻辑散落在 API 或 Service 中。

### 3.4 Runner 执行层

Runner 是平台的核心能力，负责将平台中的接口测试流程转化为真实 HTTP 请求，并记录每一步执行结果。

建议拆分为：

| 模块 | 职责 |
| --- | --- |
| FlowRunner | 执行完整测试流程 |
| StepExecutor | 执行单个接口步骤 |
| RequestBuilder | 根据环境、变量和步骤配置构造请求 |
| AssertionEngine | 执行断言规则 |
| Extractor | 从响应中提取变量 |
| ReportRecorder | 写入执行记录和报告数据 |
| ErrorHandler | 处理异常、失败策略、跳过策略 |

## 4. 核心业务模块

### 4.1 用户与认证

认证采用 JWT，推荐 access token + refresh token 模式。

认证接口的具体调用方式见 [认证接口文档](api_auth.md)。

```text
用户登录
-> 校验账号密码
-> 签发 access_token 和 refresh_token
-> refresh_token 或 token 状态写入 Redis
-> 前端携带 access_token 请求接口
```

建议策略：

| Token | 有效期 | 用途 |
| --- | --- | --- |
| access_token | 30 分钟左右 | 请求接口 |
| refresh_token | 7 天左右 | 刷新 access_token |

Redis 可用于：

- 保存 refresh token
- 保存 token 黑名单
- 实现退出登录
- 实现强制下线
- 保存用户登录版本号

### 4.2 项目管理

项目是测试资源的组织单位。

项目下可以包含：

- 环境配置
- 接口定义
- 测试用例
- 测试流程
- 执行记录
- 测试报告
- 成员与权限

### 4.3 环境管理

环境用于区分 dev、test、stage、prod 等不同运行目标。

环境配置建议包含：

- base_url
- 全局 headers
- 全局变量
- 数据库连接信息，可选
- 前置认证配置，可选

执行测试流程时，Runner 根据用户选择的环境组装最终请求。

### 4.4 接口用例管理

接口用例用于保存单个接口请求定义。

建议包含：

- 请求方法
- 请求路径
- headers
- query 参数
- body
- timeout
- 前置变量
- 后置提取规则
- 断言规则

### 4.5 测试流程编排

测试流程由多个接口步骤组成。

每个步骤可以配置：

- 执行顺序
- 引用接口用例
- 本步骤覆盖参数
- 是否继续执行
- 失败处理策略
- 变量提取
- 断言规则

典型流程：

```text
登录
-> 提取 token
-> 创建数据
-> 查询数据
-> 修改数据
-> 删除数据
-> 校验删除结果
```

### 4.6 测试执行

接口流程执行不依赖 pytest，直接使用 httpx 作为 HTTP 执行引擎。

当前场景手工执行链路：

```text
前端点击执行
-> FastAPI 校验权限、场景版本、环境和数据集
-> MySQL 写入 test_scenario_executions
-> 每个已选择数据集的每条 enabled record 写入 test_scenario_runs 和 run_queued
-> API 返回 HTTP 202、execution_id、run_id 和订阅地址
-> FastAPI BackgroundTasks 使用独立 Session 执行已有 run
-> 步骤执行继续复用原变量渲染、用例执行、断言和提取逻辑
-> 每个状态边界先写 test_scenario_run_events，再由 SSE 读取
-> 前端通过 Last-Event-ID 重连，必要时用 run detail 恢复快照
```

执行入口不直接等待长场景。API 先创建持久化 `queued` 运行并返回 HTTP 202，再由
应用内后台任务继续执行。当前实现保证任务 ID、运行快照和事件在响应前落库，但尚未提供
进程重启后的自动领取和恢复，因此不能把 `BackgroundTasks` 视为可靠任务队列。

生产环境可将“读取 queued execution 并执行 run”的边界迁移到 Celery、RQ 或专用 Worker，
无需改变现有 API、运行状态和 SSE 事件协议。迁移时必须增加原子 claim、租约、Worker 心跳、
重复投递幂等和孤儿任务恢复。

### 4.7 场景实时事件模型

```text
test_scenario_executions
  1 -> N test_scenario_runs
         1 -> N test_scenario_run_events
```

- execution 表示一次用户点击或一次幂等执行请求。
- run 表示一个数据集 record 的一次运行，是详情快照和最终结果的权威来源。
- event 表示 run 内不可变的有序状态变化，`run_id + sequence` 唯一。
- 事件必须先提交数据库，再允许 SSE 客户端读取。
- SSE 采用至少一次读取语义，客户端以 `run_id + sequence` 去重。
- 心跳也持久化并占用 sequence，保证所有带 ID 的消息都可以重放。
- 完整请求和响应正文不进入 SSE，只保存在执行详情及关联用例执行记录中。

运行状态机：

```text
queued -> running -> passed | failed | timeout | cancelled
```

步骤状态机：

```text
pending -> running -> passed | failed | timeout | skipped | cancelled
```

执行期间 `test_scenario_runs` 维护 `current_step_id`、`current_step_index`、
`last_event_sequence` 和渐进式 `step_results`，用于页面刷新或事件流中断后的快照恢复。

### 4.8 数据驱动请求解析

场景数据集使用 `records` 表示独立测试输入。未指定数据集时选择所有启用数据集；显式指定
数据集时保留原有选择语义。每个选中数据集只展开其 `enabled=true` 的 record，每条 record
创建一个独立 run。没有 `records` 的历史数据集在读取时归一化为一条兼容 record。

每个步骤按以下顺序构建最终请求：

```text
读取不可变场景版本和步骤请求快照
-> 深拷贝当前步骤请求
-> 应用当前 record 对该步骤的 request_overrides
-> 解析数据集变量、环境变量和上游步骤绑定
-> 按协议 Schema 校验最终请求
-> 执行并保存已解析请求快照
```

覆盖项优先于保存的请求快照，但模板解析发生在覆盖之后，因此覆盖值可以继续使用
`{{variable}}`。HTTP 步骤支持 `path`、`headers`、`query_params` 和嵌套 JSON `body`；
WebSocket 步骤支持 `path` 和 `headers`。覆盖只作用于当前 run 的请求副本，不修改场景版本。

核心资源列表统一使用 `{items,total,page,page_size}` 分页结构。HTTP 和 WebSocket 用例支持
关键字与环境筛选；可视化 Flow 支持关键字与状态筛选。列表查询在 Repository 层完成 count、
filter、offset 和 limit，Service 负责权限和响应组装。

### 4.9 统一错误边界

应用级异常处理器统一覆盖业务 HTTP 异常、请求校验、框架 404 和未处理异常：

```text
Router / Dependency / Service 抛出异常
-> StarletteHTTPException 保留状态码和结构化 detail
-> RequestValidationError 返回 422 字段定位数组
-> 未处理异常记录服务端堆栈和 request_id
-> 客户端统一接收 {code,message,data}
```

500 响应不泄露内部异常，使用 `X-Request-ID` 关联服务日志。公共 `ErrorResponse` Schema 和
常见状态码已注册到 OpenAPI。详细契约见 [统一错误响应文档](api_errors.md)。

### 4.10 步骤内部重试

HTTP 和 WebSocket 的自动重试位于协议执行器内部，而不是场景步骤结果路由层。单个步骤可
经历多个 attempt，但场景外层只接收最终成功或最终失败。

```text
发送请求或建立会话
-> 分类网络错误、超时、HTTP 状态
-> 必要时指数退避 + Full Jitter
-> 执行断言
-> 轮询断言必要时重试
-> 断言全部通过后提取变量
-> 返回步骤最终结果
```

HTTP 默认重试网络错误、超时、408、429、500、502、503、504；普通 4xx 不自动重试，
429 优先尊重 `Retry-After`。POST/PATCH 等非幂等方法默认禁止自动重试。WebSocket 每次
attempt 都重新建立连接并重放消息序列。所有 attempt 写入执行记录，失败 attempt 不修改变量。

### 4.11 统一执行记录查询

执行中心采用只读聚合层，不建立新的执行总表，也不改变四类执行器的持久化职责：

```text
GET /execution-records
-> ExecutionRecordService 校验 report:view
-> ExecutionRecordRepository
-> UNION ALL(
     test_case_executions,
     websocket_test_case_executions,
     test_scenario_runs,
     visual_flow_executions
   )
-> 公共筛选、计数、排序和分页
```

公共摘要统一执行类型、资源、项目、环境、触发人、状态、耗时、时间和错误信息。详情按
`execution_type + execution_id` 回查原始表，HTTP/WebSocket 保留请求或会话、响应、断言和
attempt 历史；场景保留 dataset record、变量、步骤结果和持久化事件；Flow 保留上下文和节点
执行明细。该边界使报告和趋势统计复用统一读取模型，同时避免复制历史数据或影响现有执行链路。

被删除资源通过外连接返回历史记录，资源名称允许为 `null`。统一执行记录是报告域能力，使用
`report:view`，不要求调用方同时具备四类资源查看权限。

### 4.12 媒体对象存储

缺陷图片采用 MySQL 元数据与 MinIO 对象分离的存储边界：

```text
前端 multipart 上传图片
-> FastAPI 校验项目权限、大小、MIME 和文件签名
-> MinIO 私有桶 testplatform 保存对象
-> media_objects 保存项目、所有者、对象键和文件元数据
-> 创建/更新缺陷时用 media_ids 绑定 defect_id
-> 查询缺陷时按需生成短期 S3 V4 预签名 URL
```

数据库不保存 MinIO 凭据，也不保存会过期的预签名 URL。对象键使用随机 UUID，原始文件名
仅作为展示元数据。当前仅接受 PNG、JPEG、GIF 和 WebP；SVG 因可嵌入脚本不进入首版白名单。
删除单个媒体、缺陷或项目时同步删除对象。MinIO 和 MySQL 不具备跨系统原子事务，因此删除
中存储不可用时接口返回 `503` 并保留数据库记录，便于重试；后续可增加 outbox 和孤儿对象巡检。

## 5. 自研测试报告设计

测试报告基于执行过程中的结构化数据生成，不依赖 Allure。

当前首版不建立独立报告表，而是使用测试计划运行和 Flow 执行的不可变快照生成只读报告：

```text
GET /reports
-> TestReportService 校验 report:view
-> TestReportRepository 聚合 test_plan_runs + visual_flow_executions
-> 返回报告历史摘要

GET /reports/{source_type}/{source_id}
-> plan: target_results + test_scenario_runs + step_results
-> flow: context_snapshot + visual_flow_node_executions
-> 生成统一 summary、来源专属 metrics 和 items
```

### 5.1 报告核心指标

报告应包含：

- 执行人
- 执行项目
- 执行环境
- 开始时间
- 结束时间
- 总耗时
- 总用例数
- 成功用例数
- 失败用例数
- 跳过用例数
- 总步骤数
- 成功步骤数
- 失败步骤数
- 断言总数
- 成功断言数
- 失败断言数
- 失败原因摘要

计划报告区分目标级计数和 dataset record 场景运行级计数。Flow 报告按节点统计通过、失败、
跳过和通过率。运行尚未完成时，结束时间和耗时允许为空。

### 5.2 步骤执行明细

每个步骤建议记录：

- 请求 method
- 请求 URL
- 请求 headers
- 请求 query
- 请求 body
- 响应 status_code
- 响应 headers
- 响应 body
- 请求耗时
- 断言结果
- 提取变量结果
- 错误信息

### 5.3 HTML 导出

HTML 导出与结构化报告使用同一读取模型，不再次查询或复制执行数据。导出内容包括摘要、
指标卡片和可展开的完整明细，使用 `Content-Disposition: attachment` 下载。所有运行名称、
节点标识和 JSON 明细在写入 HTML 前必须转义，防止执行数据形成脚本注入。

当前不持久化导出文件；每次下载即时生成。PDF 和长期归档仍属于后续阶段。

### 5.4 历史趋势

趋势接口在数据库内合并测试计划运行和 Flow 执行，按开始日期分组，统计执行次数、通过、
失败、其他状态、通过率和平均耗时。默认窗口 30 天，最大 366 天，可按来源类型和环境过滤。
趋势粒度是一次报告来源运行，不是计划目标、dataset record 或 Flow 节点。

### 5.5 数据存储注意事项

请求和响应数据可能很大，也可能包含敏感信息。

建议：

- 对超大响应体进行截断
- 对 token、password、secret 等字段脱敏
- 执行日志和报告设置保留周期
- 重要报告允许归档
- 当即时聚合无法满足数据量和归档要求时，再引入报告摘要与明细表

## 6. Redis 使用规划

Redis 在平台中主要用于临时数据和高频状态。

推荐使用场景：

| 场景 | 说明 |
| --- | --- |
| token 状态 | refresh token、黑名单、强制下线 |
| 任务状态 | pending、running、success、failed |
| 执行进度 | 当前步骤、总步骤数、进度百分比 |
| 临时变量 | 短生命周期执行上下文 |
| 接口限流 | 登录接口、执行接口限流 |
| 验证码 | 图形验证码、邮箱验证码、短信验证码 |

不建议把 Redis 作为主数据存储。用户、项目、用例、流程和报告应以 MySQL 为准。

## 7. MySQL 数据定位

MySQL 用于保存平台核心业务数据。

主要数据类型：

- 用户与角色
- 项目与成员
- 环境配置
- 接口定义
- 测试用例
- 测试流程
- 执行任务
- 执行结果
- 测试报告
- 操作日志

设计建议：

- 所有核心表保留 created_at、updated_at
- 重要业务表保留 created_by、updated_by
- 删除优先使用软删除
- 流程步骤保留排序字段
- 报告表注意索引设计
- 大字段谨慎入库，必要时拆分明细表

## 8. 技术选型优劣

### 8.1 FastAPI

优点：

- 性能好
- 类型提示友好
- 自动生成 OpenAPI 文档
- 与 Pydantic 集成紧密
- 适合前后端分离 API 项目

缺点：

- 分层架构需要自行规划
- 异步和同步代码混用时需要规范
- 大型项目需要提前设计依赖注入和异常处理

### 8.2 MySQL

优点：

- 成熟稳定
- 部署和运维经验丰富
- 适合保存平台业务数据
- 生态完善

缺点：

- 对复杂 JSON 查询不如 PostgreSQL
- 报告明细数据量大时需要分表、归档或冷热分离
- 并发写入较高时需要优化索引和事务范围

### 8.3 JWT

优点：

- 适合前后端分离
- 服务端可以保持较轻状态
- 易于多端接入

缺点：

- token 签发后无法天然失效
- 退出登录、强制下线需要 Redis 配合
- token 泄露后需要依赖过期时间和黑名单控制风险

### 8.4 Redis

优点：

- 性能高
- 适合缓存、任务状态和短生命周期数据
- TTL 能力适合 token、验证码和临时变量

缺点：

- 不能替代 MySQL 保存核心业务数据
- 需要关注内存容量和过期策略
- 生产环境需要考虑持久化和高可用

### 8.5 requests

优点：

- 简单稳定
- 社区成熟
- 适合自研 HTTP 执行器
- 更方便将请求、响应、断言结果结构化入库

缺点：

- 同步阻塞，不适合直接在 API 请求线程中跑长流程
- 并发能力依赖任务队列或线程/进程模型
- 需要自研变量、断言、失败策略和报告能力

### 8.6 自研报告

优点：

- 数据结构完全可控
- 更适合平台页面展示
- 可以深度结合项目、环境、流程和历史趋势
- 不受 Allure 数据格式限制

缺点：

- 需要自行设计报告模型
- 需要自行实现报告统计和可视化
- 需要处理大字段、脱敏和历史归档

## 9. 推荐建设阶段

### 第一阶段：基础平台

- 项目结构搭建
- MySQL 接入
- SQLAlchemy 和 Alembic 接入
- JWT 登录认证
- Redis 接入
- 用户、项目、环境基础 CRUD

### 第二阶段：接口测试核心

- 接口定义管理
- 单接口调试
- 接口用例保存
- 变量替换
- 基础断言
- 执行结果保存

### 第三阶段：流程编排

- 多接口步骤编排
- 上下文变量传递
- 响应提取
- 失败处理策略
- 流程执行记录

### 第四阶段：自研报告（基础能力已实现）

- 执行摘要
- 步骤明细
- 断言明细
- 失败原因
- 历史报告查询
- 报告趋势统计
- HTML 离线导出

### 第五阶段：任务系统

- 场景异步执行与持久化 SSE（已完成基础版本）
- 独立 Worker、任务 claim 和重启恢复
- 定时执行
- 批量执行
- 实时进度协议扩展到可视化 Flow
- 执行取消

### 第六阶段：平台增强

- 角色权限
- 操作日志
- 接口限流
- 数据脱敏
- 报告归档
- WebSocket 实时日志

## 10. 当前结论

当前项目已完成认证、项目权限、环境、HTTP/WebSocket 用例、场景组合、测试计划、
浏览器采集、场景实时执行、统一执行记录、报告查询、HTML 导出和按日趋势等核心能力。
后续主线为执行可靠性、前端联调以及报告归档和 PDF 扩展：

```text
FastAPI API 服务
-> MySQL 业务数据
-> JWT 用户认证
-> httpx 自研接口执行器
-> MySQL 持久化运行快照与 SSE 事件
-> 跨协议统一执行记录读取模型
-> 独立 Worker 和可靠任务领取
-> 自研测试报告与趋势读取模型
```

这套架构更适合建设一个真正的平台型后端，而不是简单调用第三方测试框架。它的前期建设成本略高，但对可视化编排、执行历史、报告分析、权限管理和后续扩展更友好。
