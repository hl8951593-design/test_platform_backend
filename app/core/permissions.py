from enum import StrEnum


class ProjectPermission(StrEnum):
    VIEW_PROJECT = "project:view"
    UPDATE_PROJECT = "project:update"
    DELETE_PROJECT = "project:delete"
    MANAGE_MEMBERS = "project:members:manage"
    VIEW_ENVIRONMENT = "environment:view"
    MANAGE_ENVIRONMENT = "environment:manage"
    VIEW_API = "api:view"
    MANAGE_API = "api:manage"
    VIEW_CASE = "case:view"
    MANAGE_CASE = "case:manage"
    VIEW_FLOW = "flow:view"
    MANAGE_FLOW = "flow:manage"
    EXECUTE_TEST = "test:execute"
    VIEW_REPORT = "report:view"


PROJECT_CREATOR_PERMISSIONS = frozenset(permission.value for permission in ProjectPermission)
NORMAL_TESTER_GRANTABLE_PERMISSIONS = PROJECT_CREATOR_PERMISSIONS - {
    ProjectPermission.UPDATE_PROJECT.value,
    ProjectPermission.DELETE_PROJECT.value,
    ProjectPermission.MANAGE_MEMBERS.value,
}
