from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")


class ProjectRead(BaseModel):
    id: int
    name: str
    description: str | None
    created_by_id: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

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


class ProjectMemberRead(BaseModel):
    id: int
    project_id: int
    user_id: int
    added_by_id: int
    is_active: bool
    permission_codes: set[str]
    created_at: datetime

    model_config = {"from_attributes": True}


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
