from typing import Literal

from pydantic import BaseModel, Field


SystemCasePriority = Literal["P0", "P1", "P2", "P3"]
SystemCaseStatus = Literal["draft", "enabled", "disabled", "incomplete"]
SystemCaseRelationStatus = Literal["linked", "unlinked", "partial"]
SystemCaseRelationType = Literal["direct", "recommended", "manual"]
SystemApiMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
SystemApiExecutionStatus = Literal["passed", "failed", "not_run"]


class SystemTestCaseCreateRequest(BaseModel):
    projectId: str | None = None
    title: str = Field(min_length=1, max_length=256)
    businessModule: str = Field(min_length=1, max_length=128)
    testObjective: str = Field(min_length=1)
    preconditions: str | None = None
    testScenario: str | None = None
    systemBehavior: str | None = None
    expectedResult: str | None = None
    dataRequirements: str | None = None
    riskPoints: str | None = None
    priority: SystemCasePriority = "P1"
    status: SystemCaseStatus = "draft"
    tags: list[str] = Field(default_factory=list)
    aiGenerated: bool = False
    aiConfidence: float | None = None
    owner: str | None = None
    createdBy: str | None = None


class SystemTestCaseUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    businessModule: str | None = Field(default=None, min_length=1, max_length=128)
    testObjective: str | None = Field(default=None, min_length=1)
    preconditions: str | None = None
    testScenario: str | None = None
    systemBehavior: str | None = None
    expectedResult: str | None = None
    dataRequirements: str | None = None
    riskPoints: str | None = None
    priority: SystemCasePriority | None = None
    status: SystemCaseStatus | None = None
    tags: list[str] | None = None
    owner: str | None = None


class SystemTestCaseBatchDeleteRequest(BaseModel):
    ids: list[str] = Field(min_length=1)


class SystemCaseApiRelationInput(BaseModel):
    apiCaseId: str
    relationType: SystemCaseRelationType
    confidence: float | None = None
    sortOrder: int = 0


class SystemCaseApiRelationsReplaceRequest(BaseModel):
    relations: list[SystemCaseApiRelationInput] = Field(default_factory=list)
