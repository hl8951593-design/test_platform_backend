# 工作台质量总览接口契约

状态：已实现
最后核验：2026-07-09

工作台首页使用聚合快照接口，避免前端分别请求用例、缺陷、执行记录和报告后自行拼接指标。

## 查询质量总览

```http
GET /api/v1/dashboard/quality-overview?project_id=1&environment_id=4&range=today&version=V3.2.1
Authorization: Bearer <access_token>
```

查询参数：

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `project_id` | 是 | - | 当前项目 |
| `environment_id` | 否 | 空 | 指定环境；为空时返回项目整体 |
| `range` | 否 | `today` | 支持 `today`、`7d`、`30d` |
| `version` | 否 | 空 | 当前版本或测试周期 |

权限：需要当前用户可访问项目。

响应 `data`：

```json
{
  "generated_at": "2026-07-08 23:30:00",
  "scope": {
    "project_id": 1,
    "environment_id": 4,
    "range": "today",
    "version": "V3.2.1"
  },
  "hero": {
    "health_score": 91.2,
    "insight_title": "质量状态稳定",
    "insight_summary": "当前范围内执行 20 次，通过 19 次，失败 1 次。",
    "risk_count": 2,
    "updated_text": "刚刚更新"
  },
  "kpis": [
    {
      "key": "execution_total",
      "label": "执行次数",
      "value": 20,
      "trend": "up",
      "breakdown": [
        { "label": "通过", "value": 19 },
        { "label": "失败", "value": 1 }
      ]
    }
  ],
  "risk_matrix": [
    { "module": "企业核心链路", "api": 25, "data": 20, "environment": 15, "level": "medium" }
  ],
  "automation_efficiency": [
    { "label": "接口自动化", "percent": 100, "saved_hours": 12 }
  ],
  "health_profile": {
    "score": 91.2,
    "dimensions": [
      { "label": "通过率", "value": 95 }
    ]
  },
  "defect_predictions": [
    { "module": "企业核心链路", "probability": 32, "impact": "medium", "reason": "失败执行和未关闭缺陷集中在当前范围内" }
  ],
  "ai_recommendations": [
    { "priority": "P0", "title": "优先处理失败链路", "summary": "当前范围内有失败执行。", "action": "查看失败分析" }
  ],
  "activity_feed": [
    {
      "occurred_at": "2026-07-08 23:30:00",
      "type": "scenario",
      "name": "企业信息全链路回归",
      "status": "failed",
      "title": "企业信息全链路回归 执行失败",
      "detail": "场景执行状态：失败"
    }
  ]
}
```

## 数据来源

- `kpis`、`activity_feed`：HTTP/WebSocket 用例执行、场景运行、测试计划运行。
- `activity_feed[].name` 使用对应 HTTP/WebSocket 用例、自动化测试流程或测试计划名称；`title` 必须优先展示名称，不能用 `HTTP 用例 {id}` 或 `场景 {id}` 作为普通用户文案。资源名称缺失时才允许回退到类型加 ID。
- `risk_matrix`、`defect_predictions`：失败执行与未关闭缺陷。
- `automation_efficiency`：HTTP/WebSocket 用例、场景和计划资产数量。
- `health_profile` 和 `hero`：通过率、失败数、缺陷数和自动化覆盖派生。

该接口是页面读模型，不新增业务事实表。

## 性能边界

- `quality-overview` 不应全量读取 HTTP/WebSocket 执行、场景运行或测试计划运行后再在 Python 中统计。
- 执行次数、通过数和失败数必须优先使用数据库聚合查询，活动流只允许读取各来源最近少量记录。
- 引用时间使用各来源最大执行时间和缺陷更新时间计算，不能为了寻找最新时间物化全部执行历史。
- `test_plan_runs` 依赖 `0034_test_plan_run_dashboard_indexes` 补齐计划运行聚合索引，`defects` 依赖 `0035_defect_dashboard_indexes` 补齐最新时间和最近缺陷索引。
- 当前接口响应体很小，若前端 Network 中耗时明显偏高，应优先检查数据库聚合 SQL、索引和是否误回退到全量执行记录读取。
