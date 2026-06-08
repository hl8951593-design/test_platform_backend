# 测试用例多环境保存开发记录

## 模块职责

本次变更支持前端在创建、编辑接口测试用例时选择多个环境保存。后端负责校验环境归属、保存默认执行环境、维护多环境关联关系，并在列表接口返回 `environment_ids` 供前端展示。

## 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/test_cases.py` | 测试用例列表、新增、编辑、执行入口 |
| Schema | `app/schemas/test_case.py` | `environment_id` 与 `environment_ids` 请求和响应结构 |
| Service | `app/services/test_case_service.py` | 环境列表去重、默认环境选择、环境归属校验 |
| Repository | `app/repositories/test_case_repository.py` | 测试用例保存和环境关联表替换 |
| Model | `app/models/test_case.py` | `TestCaseEnvironment` 关联模型 |
| Migration | `migrations/versions/0008_create_test_case_environments.py` | 新增测试用例环境关联表并回填旧数据 |
| API Doc | `docs/api_test_case_multi_environment.md` | 多环境保存接口文档 |

## 数据模型

新增表：

```text
test_case_environments
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| id | 主键 |
| project_id | 所属项目 |
| test_case_id | 测试用例 ID |
| environment_id | 环境 ID |
| created_at | 创建时间 |

约束与索引：

- `test_case_id + environment_id` 唯一，避免同一个用例重复绑定同一环境。
- `project_id + environment_id + test_case_id` 组合索引，用于按项目和环境筛选用例。
- 外键关联 `projects`、`test_cases`、`project_environments`。

旧字段保留：

```text
test_cases.environment_id
```

保留原因：

- 兼容旧前端和旧数据。
- 作为默认执行环境。
- 执行接口未显式指定环境时仍能确定运行环境。

## 业务流程

创建或编辑测试用例：

```text
接收 environment_id 和 environment_ids
-> 合并并去重环境 ID
-> 校验所有环境属于当前 project_id
-> 确定默认 environment_id
-> 保存 test_cases 主记录
-> 替换 test_case_environments 关联记录
-> 返回 TestCaseRead，包含 environment_ids
```

查询测试用例列表：

```text
按 project_id 查询 test_cases
-> selectinload 预加载 environment_links
-> TestCaseRead 返回 environment_ids
```

## 权限规则

权限沿用测试用例模块规则：

- 查询列表需要 `case:view`。
- 新增和编辑需要 `case:manage`。
- 管理员和项目创建者拥有项目内完整权限。
- 普通项目成员只能操作已授权项目内的数据。
- 环境校验必须限定在当前 `project_id` 下，不能跨项目绑定环境。

## 迁移处理

本次报错原因：

```text
pymysql.err.ProgrammingError: (1146, "Table 'test_platform_backend.test_case_environments' doesn't exist")
```

原因是代码已经使用 `TestCase.environment_links` 读取多环境关联，但当前数据库没有执行 `0008` 迁移。

处理方式：

```powershell
.\.venv\Scripts\python.exe -m alembic stamp 0007_environment_indexes
.\.venv\Scripts\python.exe -m alembic upgrade head
```

本次同时将迁移 revision ID 缩短到 32 字符以内，避免 MySQL 中 `alembic_version.version_num` 默认长度不足导致 stamp 或 upgrade 失败。

## 已实现

- 创建测试用例支持 `environment_ids`。
- 编辑测试用例支持替换多个环境。
- 列表接口返回 `environment_ids`。
- 旧数据通过迁移从 `test_cases.environment_id` 回填到 `test_case_environments`。
- 旧的 `environment_id` 字段继续作为默认执行环境，不影响现有执行逻辑。

## 风险点

- 历史数据库如果没有 Alembic 版本记录，不能直接 `upgrade head`，需要先 `stamp 0007_environment_indexes`。
- 前端传入的 `environment_ids` 必须属于当前项目，否则后端会拒绝保存。
- 删除环境时后续需要补充用例关联清理策略，避免出现失效环境关联。
