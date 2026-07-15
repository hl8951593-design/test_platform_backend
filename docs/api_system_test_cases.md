# 系统测试用例接口文档

本文档说明前端“系统测试用例”模块第一阶段后端接口。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

## 边界与权限

所有系统测试用例、API 候选和关联关系都按 `projectId` 隔离。列表、详情、候选、关系查询和统计要求项目访问者具备 `case:view`；新增、更新、删除、复制、批量删除和保存关联关系要求 `case:manage`。

系统用例持久化在 `system_test_cases`，API 关系持久化在 `system_case_api_relations`。保存关系时，后端会校验系统用例和 API 用例都属于同一项目；跨项目 API 用例返回 `404`，不会创建部分关系。

## SystemTestCase

响应字段使用前端契约的 camelCase：

```json
{
  "id": "1",
  "caseCode": "STC-000001",
  "projectId": "10",
  "projectName": "示例项目",
  "title": "用户登录成功",
  "businessModule": "登录",
  "testObjective": "验证账号密码登录",
  "priority": "P0",
  "status": "enabled",
  "tags": ["smoke"],
  "relationStatus": "linked",
  "linkedApiCaseIds": ["100"],
  "linkedApiCaseCount": 1,
  "aiGenerated": false,
  "aiConfidence": null,
  "owner": null,
  "createdBy": "admin",
  "createdAt": "2026-07-11T09:00:00",
  "updatedAt": "2026-07-11T09:00:00"
}
```

`relationStatus` 当前按已关联 API 数量派生：无关系为 `unlinked`，有关系为 `linked`。`partial` 作为前端兼容筛选值保留。

## 列表与详情

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/projects/{projectId}/system-test-cases` | `GET` | 查询项目系统用例列表 |
| `/system-test-cases/{id}` | `GET` | 查询系统用例详情 |

列表查询参数：`keyword`、`status`、`priority`、`relationStatus`、`page`、`pageSize`。响应为：

```json
{
  "items": [],
  "total": 0
}
```

## 创建、更新、删除与复制

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/projects/{projectId}/system-test-cases` | `POST` | 新增系统用例 |
| `/system-test-cases/{id}` | `PUT` | 更新系统用例 |
| `/system-test-cases/{id}` | `DELETE` | 删除系统用例 |
| `/projects/{projectId}/system-test-cases/batch-delete` | `POST` | 批量删除系统用例 |
| `/system-test-cases/{id}/duplicate` | `POST` | 复制系统用例 |

创建请求由前端提交业务字段，`id`、`caseCode`、`projectName`、`linkedApiCaseIds`、`linkedApiCaseCount`、`relationStatus`、`createdAt` 和 `updatedAt` 由后端生成。复制会创建新的系统用例、生成新的 `caseCode`，状态重置为 `draft`，不复制 API 关联关系。

批量删除请求：

```json
{
  "ids": ["1", "2"]
}
```

响应：

```json
{
  "deletedCount": 2
}
```

## API 候选与关联关系

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/projects/{projectId}/system-test-cases/api-candidates` | `GET` | 查询可关联 HTTP API 用例 |
| `/system-test-cases/{id}/relations` | `GET` | 查询系统用例已关联 API |
| `/system-test-cases/{id}/relations` | `PUT` | 替换保存系统用例 API 关系 |

候选来源为现有 `test_cases` 表，只返回当前项目数据。查询参数：`keyword`、`method`、`environment`、`executionStatus`、`tag`。当前 HTTP 用例尚无标签字段，首版保留 `tag` 参数但候选 `tags` 返回空数组。

保存关系请求：

```json
{
  "relations": [
    {
      "apiCaseId": "100",
      "relationType": "manual",
      "confidence": 0.8,
      "sortOrder": 1
    }
  ]
}
```

响应包含 `relations` 和更新后的 `systemCase`。

## 统计

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/projects/{projectId}/system-test-cases/statistics` | `GET` | 查询项目系统用例统计 |

响应：

```json
{
  "total": 120,
  "linkedApiCaseCount": 88,
  "unlinkedSystemCaseCount": 32,
  "aiGeneratedCount": 46,
  "apiRelationCoverageRate": 73
}
```

统计基于项目全量系统用例，不受列表分页影响。

## 后续阶段

AI 生成、批量创建、导入模板、导入解析/校验/确认和导出文件流尚未纳入第一阶段。后续实现时应继续遵守项目隔离和异步/非阻塞约束：AI、文件解析和大批量导出不得在普通请求生命周期内长时间阻塞。
