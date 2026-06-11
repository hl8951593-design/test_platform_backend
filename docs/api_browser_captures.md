# 浏览器采集接口

Chrome 插件使用浏览器采集接口保存一次操作过程中捕获的 HTTP 与 WebSocket 草稿。插件本地负责实时抓包与脱敏，后端负责批次持久化、审阅状态和结构化 AI 分析。

## 数据流程

1. 插件开始采集时调用 `POST /api/v1/browser-captures` 创建批次。
2. 插件实时在本地保存和审阅草稿，不逐请求写入后端。
3. 停止采集时调用 `POST /api/v1/browser-captures/{capture_id}/entries/batch` 幂等同步草稿。
4. 单条草稿可调用 `POST /api/v1/ai/browser-captures/{capture_id}/entries/{entry_id}/generate-cases` 生成 AI 用例建议。
5. 正式用例仍通过现有 HTTP/WebSocket 用例接口创建。

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/browser-captures?project_id={id}` | 查询项目采集批次 |
| `POST` | `/api/v1/browser-captures?project_id={id}` | 创建采集批次 |
| `PUT` | `/api/v1/browser-captures/{capture_id}?project_id={id}` | 更新批次状态 |
| `DELETE` | `/api/v1/browser-captures/{capture_id}?project_id={id}` | 删除采集批次 |
| `GET` | `/api/v1/browser-captures/{capture_id}/entries?project_id={id}` | 查询批次草稿 |
| `POST` | `/api/v1/browser-captures/{capture_id}/entries/batch?project_id={id}` | 按 `client_entry_id` 幂等同步草稿 |
| `PUT` | `/api/v1/browser-captures/{capture_id}/entries/{entry_id}?project_id={id}` | 更新草稿状态与审阅结果 |
| `POST` | `/api/v1/ai/browser-captures/{capture_id}/entries/{entry_id}/generate-cases?project_id={id}` | 根据结构化草稿生成用例 |
| `POST` | `/api/v1/ai/browser-captures/{capture_id}/generate-cases?project_id={id}` | 为选中草稿批量生成用例建议 |
| `POST` | `/api/v1/ai/browser-captures/{capture_id}/analyze-relations?project_id={id}` | 分析响应字段与后续请求字段依赖 |
| `POST` | `/api/v1/ai/browser-captures/{capture_id}/generate-scenario?project_id={id}` | 生成有序场景草稿与跨步骤响应引用建议 |

查看批次和草稿需要 `case:view`，创建、同步、更新与 AI 生成需要 `case:manage`。
