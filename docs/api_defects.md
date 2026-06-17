# 缺陷跟踪接口文档

本文档说明项目缺陷跟踪相关接口。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

缺陷模块用于按项目记录 Bug，并维护从创建到关闭或重新激活的生命周期。成功响应统一为
`{code, message, data}`。

## 数据关系

```text
projects
-> defects.project_id
users
-> defects.reporter_id
```

当前已实现：

- 查询项目缺陷列表；
- 创建缺陷；
- 查询缺陷详情；
- 更新缺陷；
- 删除缺陷；
- 推进缺陷状态；
- 富文本 HTML 服务端清洗；
- 项目删除时清理项目下缺陷。

## 权限

| 操作 | 权限 |
| --- | --- |
| 查询列表、详情 | `defect:view` |
| 创建缺陷 | `defect:create` |
| 更新缺陷 | `defect:update` |
| 删除缺陷 | `defect:delete` |
| 推进状态 | `defect:transition` |

管理员和项目创建者默认拥有项目下全部缺陷权限。普通测试人员必须被加入项目并授予对应权限后才能操作。

## 状态枚举

| 值 | 展示文案 |
| --- | --- |
| `new` | 新创建 |
| `active` | 已激活 |
| `confirmed` | 已确认 |
| `fixed` | 已修复 |
| `verified` | 已验证 |
| `closed` | 已关闭 |
| `reopened` | 重新激活 |

后端校验状态流转合法性。非法流转返回 HTTP `409`，响应 `data` 中包含
`current_status` 和 `target_status`。

当前允许的状态流转：

```text
new -> active | confirmed | closed
active -> confirmed | fixed | closed
confirmed -> fixed | closed
fixed -> verified | reopened
verified -> closed | reopened
closed -> reopened
reopened -> active | confirmed | fixed | closed
```

重复提交当前状态视为幂等成功。

## 查询缺陷列表

| 项目 | 内容 |
| --- | --- |
| 接口 | `/defects?project_id={project_id}&keyword={keyword}&status={status}&urgency={urgency}&page=1&page_size=20` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | `defect:view` |
| 说明 | 分页返回项目下缺陷数据 |

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `project_id` | 必填 | 当前项目 ID |
| `keyword` | 空 | 按标题、指派人、报告人账号/姓名或富文本内容搜索 |
| `status` | 空 | 缺陷状态 |
| `urgency` | 空 | 紧急程度 |
| `page` | `1` | 页码，从 1 开始 |
| `page_size` | `20` | 每页数量，最大 200 |

响应 `data` 结构为：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

## 创建缺陷

| 项目 | 内容 |
| --- | --- |
| 接口 | `/defects?project_id={project_id}` |
| 方法 | `POST` |
| 权限 | `defect:create` |

请求示例：

```json
{
  "title": "支付成功后订单状态未同步",
  "assignee": "qa_owner",
  "bug_type": "functional",
  "urgency": "critical",
  "status": "new",
  "content_html": "<p>复现步骤...</p>"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `title` | 是 | Bug 标题，最长 256 |
| `assignee` | 否 | 指派人账号、姓名或用户 ID，当前按字符串保存并以 `assignee_name` 返回 |
| `bug_type` | 是 | `functional`、`ui`、`performance`、`security`、`compatibility`、`data`、`other` |
| `urgency` | 是 | `low`、`medium`、`high`、`critical` |
| `status` | 否 | 当前状态，默认 `new` |
| `content_html` | 是 | 富文本内容 HTML |

创建人自动记录为 `reporter_id`，响应中通过 `reporter_name` 返回用户名或账号。

## 查询、更新和删除缺陷

| 方法 | 接口 | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/defects/{defect_id}?project_id={project_id}` | `defect:view` | 查询详情 |
| `PUT` | `/defects/{defect_id}?project_id={project_id}` | `defect:update` | 更新缺陷字段 |
| `DELETE` | `/defects/{defect_id}?project_id={project_id}` | `defect:delete` | 删除缺陷 |

更新请求体与创建请求体一致。如果 `status` 发生变化，也会执行状态流转校验。

## 推进缺陷状态

| 项目 | 内容 |
| --- | --- |
| 接口 | `/defects/{defect_id}/status?project_id={project_id}` |
| 方法 | `PUT` |
| 权限 | `defect:transition` |

请求示例：

```json
{
  "status": "fixed"
}
```

响应返回更新后的缺陷对象。若当前状态不能流转到目标状态，返回 HTTP `409`。

## 响应对象

```json
{
  "id": 18,
  "project_id": 1,
  "title": "支付成功后订单状态未同步",
  "assignee_name": "李雷",
  "bug_type": "functional",
  "urgency": "critical",
  "status": "confirmed",
  "content_html": "<p>复现步骤...</p>",
  "reporter_name": "韩梅梅",
  "created_at": "2026-06-17 08:00:00",
  "updated_at": "2026-06-17 09:00:00"
}
```

## 富文本安全

后端会清洗 `content_html`：

- 删除 `script`、`style`、`iframe`、`object`、`embed` 等不安全标签；
- 删除所有 `on*` 事件属性；
- 删除 `javascript:`、`vbscript:` 等不安全 URL；
- 仅允许 `http`、`https`、相对路径和受限图片 `data:` URL；
- 不保留内联 `style`。

如果后续改为独立附件存储，粘贴图片应转换为附件 URL 后再写回标准 `content_html`。

## 兼容性和迁移

- 新增数据库表 `defects`。
- Alembic 迁移文件为 `0018_create_defect_tables.py`，revision 为 `0018_defects`。
- 部署前必须执行 `alembic upgrade head`。
