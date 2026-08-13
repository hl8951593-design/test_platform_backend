# 项目管理接口

状态：当前实现  
最后核验：2026-07-18

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/projects` | 查询当前用户可见项目及项目卡片统计 |
| `GET` | `/api/v1/projects/{project_id}` | 查询单个项目的权威详情与实时统计 |
| `GET` | `/api/v1/projects/{project_id}/testing-overview` | 查询语义明确的测试总览、最近执行、建议和活动 |
| `POST` | `/api/v1/projects` | 创建项目 |
| `PUT` | `/api/v1/projects/{project_id}` | 更新项目名称和说明 |
| `DELETE` | `/api/v1/projects/{project_id}` | 删除项目及其项目级资产 |
| `POST` | `/api/v1/projects/{project_id}/members` | 添加成员或更新成员权限 |
| `GET` | `/api/v1/projects/{project_id}/members` | 查询创建者和有效项目成员 |
| `PUT` | `/api/v1/projects/{project_id}/members/{user_id}` | 完整替换普通成员权限 |
| `DELETE` | `/api/v1/projects/{project_id}/members/{user_id}` | 停用并移除普通成员 |

## 项目列表

```http
GET /api/v1/projects?refresh=true
```

`refresh` 默认为 `false`。常规读取允许复用短时项目列表缓存；项目管理页主动刷新时传入
`refresh=true`，服务端仅为本次请求绕过缓存并重新计算当前用户可见项目的统计快照，不清除其他
用户的缓存条目。

响应 `data` 为 `ProjectRead[]`。每个项目包含：

```json
{
  "id": 1,
  "name": "测试项目",
  "description": "项目说明",
  "created_by_id": 1,
  "owner_name": "admin",
  "status": "active",
  "is_active": true,
  "is_deleted": false,
  "created_at": "2026-07-15T08:00:00",
  "updated_at": "2026-07-15T08:00:00",
  "members": [
    { "id": 1, "name": "admin", "role": "负责人" }
  ],
  "stats": {
    "api_case_count": 15,
    "http_test_case_count": 14,
    "websocket_test_case_count": 1,
    "system_test_case_count": 8,
    "test_case_count": 15,
    "scenario_count": 4,
    "plan_count": 2,
    "flow_count": 1,
    "run_count": 1888,
    "passed_execution_count": 1472,
    "failed_execution_count": 356,
    "pass_rate": 78,
    "api_execution_coverage_rate": 100,
    "api_success_coverage_rate": 93,
    "coverage_rate": 100,
    "automation_rate": 93,
    "open_defect_count": 2,
    "total_defect_count": 3,
    "defect_count": 3,
    "last_run_at": "2026-07-15T08:13:15",
    "last_execution_status": "失败",
    "risk_score": 46,
    "risk_level": "medium",
    "ai_recommendations": [],
    "team_activity": [],
    "recommendations": [],
    "activities": []
  }
}
```

## 项目详情与统计刷新

```http
GET /api/v1/projects/{project_id}
```

该接口不读取项目列表响应缓存。前端进入项目详情和点击“刷新统计”时使用此接口，响应结构为单个
`ProjectRead`。项目不存在或当前用户不可见时返回统一权限/资源错误响应。

`coverage_rate`、`automation_rate` 和 `defect_count` 为旧客户端兼容字段，分别等同于
`api_execution_coverage_rate`、`api_success_coverage_rate` 和 `total_defect_count`。新客户端必须使用
语义明确的新字段；风险评分仅使用 `open_defect_count`，关闭缺陷不再持续抬高项目风险。

## 测试总览

```http
GET /api/v1/projects/{project_id}/testing-overview
```

响应 `data` 为 `ProjectTestingOverview`：

- `counts`：HTTP、WebSocket、系统用例、场景、计划、流程、根执行成功/失败数和缺陷数。
- `quality.pass_rate`：通过的根执行数除以全部根执行数。
- `quality.api_execution_coverage_rate`：至少存在一条终态执行记录的已保存 HTTP/WebSocket 用例占比。
- `quality.api_success_coverage_rate`：至少成功执行过一次的已保存 HTTP/WebSocket 用例占比。
- `latest_execution`：最近一条根执行及其真实资源 ID、名称和类型；无执行时为 `null`。
- `recommendations`：规则生成的结构化质量建议，不冒充大模型分析结果。
- `activities`：来自真实项目、用例、执行和缺陷记录的结构化活动，按时间倒序返回。

项目卡片统计只计独立业务执行：直接 HTTP/WebSocket 执行、非计划内场景执行、计划执行和流程执行。
场景/计划内部产生的子执行不会再次计入 `total_executions`。

## 成员权限

```http
POST /api/v1/projects/{project_id}/members
Content-Type: application/json

{
  "user_id": 12,
  "permission_codes": ["testcase:read", "scenario:read"]
}
```

创建者由 `projects.created_by_id` 隐式拥有全部权限，不创建 `project_members` 行。成员列表为了给前端
提供统一身份，令 `id == user_id`，并额外返回可空的 `membership_id`；创建者的 `membership_id` 为
`null` 且 `role=owner`。普通成员角色由权限集投影为 `tester` 或 `viewer`。

`DELETE` 采用停用成员而非物理删除，以保留授权审计；再次调用 `POST` 会复用原成员记录并重新激活，
不会触发 `(project_id, user_id)` 唯一约束冲突。创建者不可被修改权限或移除，普通成员也不能被授予
`project:update`、`project:delete` 或 `project:members:manage`。

## 项目删除

`DELETE /api/v1/projects/{project_id}` 仅允许项目创建者或平台管理员调用。删除采用项目级物理清理：先在
同一数据库事务中清除环境、成员、用例、场景、计划、执行、Flow、缺陷、通知、Dashboard、Desktop/UI
绑定、报告导出凭证和报告删除标记，再删除项目；对象存储中的媒体对象在数据库提交后尽力清理，存储故障
不会回滚已经成功的数据库删除。前端项目列表和详情均需二次确认，成功后重新加载顶栏项目上下文。

## 缓存一致性

项目列表缓存最长 10 秒。项目、系统/API 用例、场景、计划、流程、缺陷发生写入时会主动失效；场景、
计划、流程、HTTP 和 WebSocket 异步执行在入队后及完成回调中再次失效，保证运行状态和质量统计及时
收敛。`GET /testing-overview` 和 `GET /projects/{project_id}` 始终实时计算，不读取项目列表缓存。
