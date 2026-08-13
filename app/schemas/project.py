from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")


class ProjectMemberSummaryRead(BaseModel):
    id: int
    name: str
    role: str


class ProjectStatsRead(BaseModel):
    api_case_count: int = 0
    http_test_case_count: int = 0
    websocket_test_case_count: int = 0
    system_test_case_count: int = 0
    test_case_count: int = 0
    scenario_count: int = 0
    plan_count: int = 0
    flow_count: int = 0
    run_count: int = 0
    passed_execution_count: int = 0
    failed_execution_count: int = 0
    pass_rate: int = 0
    api_execution_coverage_rate: int = 0
    api_success_coverage_rate: int = 0
    # Compatibility aliases. New clients should use the explicit API coverage names above.
    coverage_rate: int = 0
    automation_rate: int = 0
    open_defect_count: int = 0
    total_defect_count: int = 0
    # Compatibility alias for total_defect_count.
    defect_count: int = 0
    last_run_at: datetime | None = None
    last_execution_status: str | None = None
    risk_score: int = 0
    risk_level: Literal["low", "medium", "high"] = "low"
    ai_recommendations: list[str] = Field(default_factory=list)
    team_activity: list[str] = Field(default_factory=list)
    recommendations: list["ProjectRecommendationRead"] = Field(default_factory=list)
    activities: list["ProjectActivityRead"] = Field(default_factory=list)


class ProjectRecommendationRead(BaseModel):
    id: str
    type: Literal["coverage", "failure", "defect", "automation"]
    title: str
    description: str
    severity: Literal["low", "medium", "high"]
    action_type: str | None = None
    action_target_id: int | None = None


class ProjectActivityRead(BaseModel):
    id: str
    type: Literal[
        "project_updated",
        "case_created",
        "case_executed",
        "scenario_executed",
        "plan_executed",
        "flow_executed",
        "defect_created",
    ]
    title: str
    description: str | None = None
    operator_id: int | None = None
    operator_name: str | None = None
    resource_type: str | None = None
    resource_id: int | None = None
    resource_name: str | None = None
    occurred_at: datetime


class ProjectTestingCountsRead(BaseModel):
    http_test_cases: int = 0
    websocket_test_cases: int = 0
    system_test_cases: int = 0
    api_test_cases: int = 0
    scenarios: int = 0
    plans: int = 0
    flows: int = 0
    total_executions: int = 0
    passed_executions: int = 0
    failed_executions: int = 0
    open_defects: int = 0
    total_defects: int = 0


class ProjectTestingQualityRead(BaseModel):
    pass_rate: int = 0
    api_execution_coverage_rate: int = 0
    api_success_coverage_rate: int = 0
    risk_score: int = 0
    risk_level: Literal["low", "medium", "high"] = "low"


class ProjectLatestExecutionRead(BaseModel):
    id: int
    resource_type: Literal["http_case", "websocket_case", "scenario", "plan", "flow"]
    resource_id: int | None = None
    resource_name: str
    status: str
    executed_at: datetime


class ProjectTestingOverviewRead(BaseModel):
    project_id: int
    generated_at: datetime
    counts: ProjectTestingCountsRead
    quality: ProjectTestingQualityRead
    latest_execution: ProjectLatestExecutionRead | None = None
    recommendations: list[ProjectRecommendationRead] = Field(default_factory=list)
    activities: list[ProjectActivityRead] = Field(default_factory=list)


class ProjectRead(BaseModel):
    id: int
    name: str
    description: str | None
    created_by_id: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    owner_name: str | None = None
    status: str = "active"
    is_active: bool = True
    members: list[ProjectMemberSummaryRead] = Field(default_factory=list)
    stats: ProjectStatsRead = Field(default_factory=ProjectStatsRead)

    model_config = {"from_attributes": True}


class ProjectSummaryRead(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class UserSummaryRead(BaseModel):
    id: int
    username: str
    account: str

    model_config = {"from_attributes": True}


class ProjectMemberGrantRequest(BaseModel):
    user_id: int = Field(description="被加入项目的用户 ID")
    permission_codes: set[str] = Field(default_factory=set, description="授予的项目内功能权限编码")


class ProjectMemberUpdateRequest(BaseModel):
    permission_codes: set[str] = Field(default_factory=set, description="Complete replacement permission set")


class ProjectMemberRead(BaseModel):
    id: int
    project_id: int
    user_id: int
    added_by_id: int
    is_active: bool
    permission_codes: set[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectMemberDetailRead(BaseModel):
    # Member-management routes are keyed by user_id, so id is the stable user identity.
    id: int
    membership_id: int | None = None
    project_id: int
    user_id: int
    username: str
    display_name: str
    avatar_url: str | None = None
    role: Literal["owner", "tester", "viewer"]
    permission_codes: list[str] = Field(default_factory=list)
    is_active: bool
    added_by_id: int
    added_by_name: str
    created_at: datetime
    updated_at: datetime


class ProjectEnvironmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="环境名称，例如 prod、uat、test")
    base_url: str = Field(min_length=1, max_length=512, description="环境基础地址")
    description: str | None = Field(default=None, description="环境描述")
    is_default: bool = Field(default=False, description="是否默认环境")


class ProjectEnvironmentUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="环境名称，例如 prod、uat、test")
    base_url: str = Field(min_length=1, max_length=512, description="环境基础地址")
    description: str | None = Field(default=None, description="环境描述")
    is_default: bool = Field(default=False, description="是否默认环境")


class ProjectEnvironmentRead(BaseModel):
    id: int
    project_id: int
    name: str
    base_url: str
    description: str | None
    is_default: bool
    is_active: bool = True
    is_deleted: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectEnvironmentDetailRead(ProjectEnvironmentRead):
    project: ProjectSummaryRead
    created_by: UserSummaryRead
    variables: list["ProjectEnvironmentVariableRead"] = Field(default_factory=list)
    test_case_count: int = 0


class EnvironmentTestCaseRead(BaseModel):
    id: int
    project_id: int
    environment_id: int | None
    name: str
    method: str
    path: str
    created_by_id: int
    last_execution_status: str | None
    last_executed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestCaseEnvironmentBindRequest(BaseModel):
    environment_id: int | None = Field(default=None, description="环境配置 ID，传 null 表示解绑")


class ProjectEnvironmentVariableUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="变量名")
    value: str = Field(description="变量值")
    is_secret: bool = Field(default=False, description="是否敏感")


class ProjectEnvironmentVariableRead(BaseModel):
    id: int
    environment_id: int
    name: str
    value: str
    is_secret: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
