# 工作台接口契约

状态：已实现
最后核验：2026-07-15

所有接口使用统一响应包：`{"code":0,"message":"success","data":...}`。工作台属于项目读写边界，所有查询至少要求项目访问权限；AI 分析要求 `ai:analyze`，普通回归要求 `test:execute`，测试计划回归要求 `plan:run`。

## 质量总览

```http
GET /api/v1/dashboard/quality-overview?project_id=1&environment_id=4&range=7d
```

`range` 支持 `today`、`7d`、`30d`。执行统计只计算 HTTP、WebSocket、场景、测试计划和 Flow 的根执行，排除场景内用例和计划内场景，避免重复计数。

`activity_feed[]` 现在包含 `id/type/resource_id/run_id/name/action`；`ai_recommendations[]` 包含 `id/type/recommendation/confidence_score/risk_level` 和结构化 `action`。资源名称来自业务表，只有资源被删除或名称缺失时才退回类型加 ID。当前没有校准预测模型，因此 `defect_predictions=[]`。

## 项目资产趋势

```http
GET /api/v1/dashboard/project-asset-trends?project_id=1&environment_id=4&range=30d
```

`range` 仅支持 `7d`、`30d`，默认 `30d`。响应包含：

- `test_cases`：HTTP、WebSocket、系统用例的 `current/previous/delta/delta_rate/breakdown/points`。
- `automation_flows`：已保存且未删除场景，不包含未保存草稿。
- `defects`：主值为未关闭缺陷数，同时返回累计缺陷数。
- `historical_data_complete` 和 `data_complete_from`：声明快照覆盖是否足以计算完整历史。

历史由 `dashboard_asset_daily_snapshots` 和 `dashboard_asset_events` 提供。GET 读取使用实时聚合生成当天内存点，不写入或提交快照；后台 `DashboardAssetSnapshotScheduler` 默认每 300 秒为项目及有效环境持久化当天快照。资产创建、删除和缺陷关闭进入生命周期事实表。迁移前历史无法恢复时，`previous` 使用当前值作为中性基线、`delta=0`，并返回 `historical_data_complete=false`，禁止用当前表 `created_at` 反推已删除资产。只有上一周期结束日和当前周期的每个日点都有快照时才标记完整；调度停机造成日期缺口时同样返回不完整。

环境趋势中 HTTP/WebSocket 同时识别主环境和多环境关联；系统用例和缺陷当前只有项目归属，因此在每个环境视图中作为项目级事实展示。`points` 按日期升序。`previous=0` 时 `delta_rate=0`。

## 活动明细

```http
GET /api/v1/dashboard/activity-feed?project_id=1&environment_id=4&page=1&page_size=20&resource_type=scenario&status=failed&date_from=2026-07-01&date_to=2026-07-15
```

`page_size` 最大 100。`resource_type` 支持 `http_test_case/websocket_test_case/system_test_case/scenario/flow/test_plan/defect/execution`；`execution` 表示全部执行来源，系统用例当前没有独立执行事实，因此筛选结果为空。日期参数为包含首尾日的 `YYYY-MM-DD`。

响应 `items[]` 使用公共明细形状：

```json
{
  "id": "activity-http-1657",
  "event_type": "execution.failed",
  "occurred_at": "2026-07-15 08:13:15",
  "resource_type": "http_test_case",
  "resource_id": 8,
  "resource_name": "获取企业画像",
  "run_id": 1657,
  "status": "failed",
  "title": "获取企业画像 执行失败",
  "detail": "断言校验失败",
  "action": {
    "code": "view_failure_analysis",
    "label": "查看失败分析",
    "resource_type": "execution",
    "resource_id": 1657,
    "params": {"execution_type": "http"}
  }
}
```

## 异步 AI 分析

```http
POST /api/v1/dashboard/ai-analysis-jobs
GET  /api/v1/dashboard/ai-analysis-jobs/{job_id}
```

创建接口返回 `202`。请求字段：`project_id/environment_id/range/analysis_type/focus/user_prompt`；`analysis_type` 支持 `quality_diagnosis/generate_recommendations/risk_analysis/defect_prediction`。任务状态为 `queued/running/completed/failed`。

任务只把当前项目、环境、时间范围和可选资源焦点匹配到的活动事实作为证据交给现有 AI Provider。模型只能生成摘要和建议文本，`resource_id/run_id/evidence/action` 全部由后端从真实证据重建，模型输出不能创建或替换资源身份。Provider 未配置、不可用或返回非法 JSON 时任务进入 `failed` 并返回稳定 `error_code`。`defect_prediction` 不调用 Provider，也不生成概率，只说明尚无校准模型。

## 统一回归入口

```http
POST /api/v1/dashboard/regression-runs
GET  /api/v1/dashboard/regression-runs/{run_id}
```

创建接口返回 `202`。`scope_type` 支持 `smart/test_plan/scenario/flow/test_cases`，`strategy` 支持 `failed_first/risk_first/full`。创建时固化请求与目标快照，父任务再串行调用现有 HTTP、WebSocket、场景、Flow 或计划执行服务；子执行仍使用原有权限、环境校验、快照、断言、诊断和状态机。

- `failed_first` 优先选择当前环境最近失败的 HTTP/WebSocket 保存用例，无失败时回退到可执行保存用例。
- `risk_first` 优先选择失败用例及 P0/P1 系统用例关联的真实 HTTP 用例。
- `full` 选择请求开关允许的当前环境保存用例。
- 系统用例不是独立执行器，只能展开为 `system_case_api_relations` 中的 HTTP 用例。
- 同一用户、相同请求指纹已有 `queued/running` 父任务时返回 `409`。

父任务响应包含 `run_id/run_type/status/target_count/passed_count/failed_count/child_executions/execution_resource`。创建响应状态为 `queued`，查询接口可返回终态 `passed/failed/cancelled/timeout`。

## 洞察详情

```http
GET /api/v1/dashboard/insights/{insight_type}?project_id=1&environment_id=4&range=7d&page=1&page_size=20
```

`insight_type` 支持 `risk-analysis/automation-efficiency/health-profile/defect-prediction`。风险明细只来自失败执行和缺陷；自动化效率与健康画像复用质量总览的事实口径。缺陷预测在未部署校准模型时固定返回 `available=false`、空 `metrics/items`，不以固定系数模拟概率。

## 表与调度

迁移 `0042_dashboard_workbench_contracts` 新增：

| 表 | 作用 |
| --- | --- |
| `dashboard_asset_daily_snapshots` | 项目/环境每日资产与缺陷计数快照 |
| `dashboard_asset_events` | 资产创建、删除、缺陷关闭/重开生命周期事实 |
| `dashboard_ai_analysis_jobs` | 工作台异步 AI 分析状态、证据和建议 |
| `dashboard_regression_runs` | 统一回归父任务、请求/目标快照和子执行索引 |

项目物理删除会先清理上述表。调度器只维护读模型，不改变执行状态；AI 与回归使用共享有界执行队列，队列满时在写入任务前返回 `503`。
