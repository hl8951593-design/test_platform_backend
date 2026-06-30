---
name: project-permission-admin
description: Use when the user asks to explain, inspect, troubleshoot, or plan TestAuto projects, members, roles, permissions, project access, administrator rights, project creator rights, ordinary tester permissions, or authorization failures.
triggers:
  - permission
  - permissions
  - role
  - member
  - project access
  - admin
  - 403
  - 权限
  - 角色
  - 成员
  - 项目成员
  - 管理员
  - 普通测试人员
  - 授权
routing_requires_tool:
  - current project permission
  - current project member
  - project access
  - 当前项目权限
  - 当前项目成员
  - 项目访问
---

# Project Permission Admin

## Workflow

1. For conceptual permission explanations, answer directly using the platform role model.
2. For current project facts, use `project.read_context` when available, but do not invent member lists or granted permission codes that no tool returned.
3. If the user asks to add/remove members, grant/revoke permissions, set admin, or delete projects, only claim completion when a dedicated backend tool succeeds.
4. For 403 or authorization failures, separate authentication, project membership, permission code, resource ownership, and deleted-resource causes.

## Permission Model

- Admin has global access.
- Project creator owns and manages their own project.
- Ordinary testers need project membership and explicit project permission codes.
- Data access follows project scope; cross-project reuse or copying must be explicit and authorized.

## Final Reply

- State the likely permission layer involved and what evidence is missing.
- Provide a safe checklist for the user or administrator without exposing secrets or granting access implicitly.
