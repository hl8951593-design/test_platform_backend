# TestAuto Desktop UI 用例 API

> 状态：已实现（阶段 C）
>
> 最近核验：2026-07-29
>
> Alembic revision：`0047_ui_test_cases`，当前 head 为 `0048_ui_execution_runtime`

本文档描述平台已经可调用的 UI 用例、不可变版本和 DSL 校验接口。浏览器执行仍由 PyQt6 Desktop 的 Playwright Worker 完成；后端不接收任意 Python、JavaScript、Shell 或本机绝对路径。

## 1. 路由与权限

所有接口使用用户 access token，并继续按项目复用现有权限。

| 方法 | 路径 | 权限 | 行为 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/ui-test-cases/validate?project_id={id}` | `case:manage` | 校验并规范化未保存 DSL |
| `GET` | `/api/v1/ui-test-cases?project_id={id}` | `case:view` | 分页、关键字、状态、环境筛选 |
| `POST` | `/api/v1/ui-test-cases?project_id={id}` | `case:manage` | 创建用例和版本 1，返回 `201` |
| `GET` | `/api/v1/ui-test-cases/{case_id}` | `case:view` | 元数据和当前版本详情 |
| `PATCH` | `/api/v1/ui-test-cases/{case_id}` | `case:manage` | 只更新名称、描述、状态、标签和默认环境 |
| `DELETE` | `/api/v1/ui-test-cases/{case_id}` | `case:manage` | 软删除，不删除版本和历史运行快照 |
| `GET` | `/api/v1/ui-test-cases/{case_id}/versions` | `case:view` | 倒序查询版本历史 |
| `POST` | `/api/v1/ui-test-cases/{case_id}/versions` | `case:manage` | 追加不可变版本，返回 `201` |
| `GET` | `/api/v1/ui-test-cases/{case_id}/versions/{version}` | `case:view` | 读取指定版本 |

统一响应保持 `{code,message,data}`。`case_id` 为不可猜测的 `ui_case_...` public ID；数据库 BIGINT 主键不作为 Desktop 用例身份。

## 2. 创建用例

```json
{
  "name": "用户登录与工作台校验",
  "description": "Desktop 可见浏览器冒烟",
  "status": "active",
  "tags": ["smoke", "login"],
  "default_environment_id": 3,
  "change_summary": "initial version",
  "dsl": {
    "schema_version": "ui-case-v1",
    "browser": {
      "engine": "chromium",
      "channel": "chrome",
      "headless": false,
      "profile_ref": "ctx_0123456789abcdef"
    },
    "settings": {
      "step_timeout_ms": 10000,
      "navigation_timeout_ms": 30000,
      "trace": "retain-on-failure",
      "screenshot": "only-on-failure"
    },
    "steps": [
      {
        "id": "step_001",
        "name": "打开登录页",
        "kind": "action",
        "operation": "navigate",
        "input_value": "${env.base_url}/login",
        "timeout_ms": 30000,
        "failure_policy": "停止运行",
        "enabled": true
      }
    ]
  }
}
```

后端保存规范化后的可执行形态。为兼容目标架构文档和当前 `0.3.0-dev` Desktop Worker，步骤输入同时接受：

- 扁平形态：`kind/operation/locator_by/locator_value/input_value`；
- 嵌套形态：`type/action|assertion/locator/url|value|expected`。

嵌套输入会转换为扁平 canonical DSL 后再计算 SHA-256。`status/duration_ms/runtime_patch` 等已知本地运行字段会被剥离，其他未知字段、未知操作和重复步骤 ID 直接返回 `422`。

## 3. DSL 安全约束

- `schema_version` 当前只接受 `ui-case-v1`。
- 浏览器引擎只接受 Chromium；channel 为 `chromium/chrome/msedge`。
- `profile_ref` 只能是本地不透明别名（受管录制使用 `ctx_...`），不能保存文件路径、Cookie、storage state 或加密正文。后端只校验和版本化该别名，不解析、下载或跨设备同步它；被派发的 Desktop 必须在当前 Windows 用户的加密上下文存储中按项目/环境解析，缺失、篡改或绑定不匹配时释放执行 lease 并阻止浏览器启动。
- 动作和断言使用白名单；第一版不允许任意代码执行。
- `upload` 只允许文件别名或变量引用，拒绝本机绝对路径。
- 绝对 `http/https` 导航地址的 host 必须等于所选环境 `base_url` host；本地调试时 `localhost`、IPv4 `127.0.0.0/8` 和 IPv6 `::1` 视为同一回环主机，但不会放宽为其他主机。相对路径、`${env.*}` 和 `testauto://smoke/...` 可用。
- `${secret.name}` 只提取为 `required_secret_refs`，不会解析或保存密钥明文。
- 单用例默认最多 `200` 步、规范化 JSON 最多 `1 MiB`、标签最多 `50` 个；由 `UI_CASE_MAX_*` 配置覆盖。

校验响应返回 `checksum/step_count/required_secret_refs/warnings/normalized_dsl`。XPath、当前 Desktop Worker 尚未完整实现的能力会产生 warning，但不会伪装成已经具备运行能力。

### 3.1 动作、断言与步骤选项

- 页面/鼠标：`navigate/reload/go_back/go_forward/click/dblclick/hover/drag_to`。
- 输入/元素：`fill/clear/press/select/check/uncheck/focus/blur/scroll_into_view/wait_for`。
- 文件/产物：`upload/download/screenshot`。
- 状态断言：`visible/hidden/enabled/disabled/editable/checked/unchecked/empty/focused/in_viewport`。
- 内容/页面/视觉断言：`text/value/attribute/count/url/title/screenshot`。

`operator` 支持 `equals/contains/matches/not_equals`；属性断言要求 `attribute_name`，截图断言要求 `baseline_ref`。`options` 是强类型白名单对象，用于页面等待、鼠标按钮与修饰键、popup/download 原子等待、弹窗处理、下拉选择方式、拖拽目标、截图范围，以及 `accessible_name/exact/nth/frame_locator` 等定位器选项。Recorder V2 的 `locator_candidates/locator_plan/target_fingerprint/action_episode`、动作结果 URL、回放分层证据、网络依赖与 frame 来源也会以受限结构保存，供 Desktop 后续稳定回放和诊断使用；未知 option 字段仍返回 `422`。

## 4. 不可变版本与并发

```json
{
  "base_version": 4,
  "change_summary": "修复登录按钮定位器",
  "dsl": {
    "schema_version": "ui-case-v1",
    "steps": []
  }
}
```

实际 `steps` 至少一项。保存规则：

1. 先规范化 DSL 并计算 checksum。
2. checksum 与当前版本相同则返回当前版本，不重复创建，即使重试携带的 `base_version` 已旧。
3. 内容不同且 `base_version` 不是当前版本时返回 `409 case_version_conflict` 和当前版本号。
4. 成功时只追加 `version + 1`，历史版本没有更新和删除接口。

跨项目环境引用返回 `404`，避免泄露其他项目资源是否存在。元数据 PATCH 不会隐式创建或修改 DSL 版本。

## 5. 主要业务错误

| HTTP | detail/error | 含义 |
| --- | --- | --- |
| `403` | 现有项目权限错误 | 无 `case:view` 或 `case:manage` |
| `404` | `ui_test_case_not_found` | 用例不存在、已软删除或不可见 |
| `404` | `ui_test_case_environment_not_found` | 环境不属于项目或已删除 |
| `404` | `ui_test_case_version_not_found` | 指定版本不存在 |
| `409` | `case_version_conflict` | 基线版本已过期且内容不同 |
| `413` | `ui_case_step_limit_exceeded` / `ui_case_dsl_too_large` | DSL 超出服务端限制 |
| `422` | `ui_case_navigation_host_forbidden` | 导航 host 不属于环境 |

执行创建契约见 [TestAuto Desktop UI 执行 API](api_ui_executions.md)。
