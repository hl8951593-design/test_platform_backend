from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.async_response import public_execution_status
from app.core.permissions import ProjectPermission
from app.models.project import ProjectEnvironment
from app.models.system_test_case import SystemCaseApiRelation, SystemTestCase
from app.models.test_case import TestCase
from app.models.user import User
from app.schemas.system_test_case import (
    SystemCaseApiRelationsReplaceRequest,
    SystemTestCaseBatchDeleteRequest,
    SystemTestCaseCreateRequest,
    SystemTestCaseUpdateRequest,
)
from app.services.permission_service import PermissionService


class SystemTestCaseService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_cases(
        self,
        *,
        project_id: int,
        current_user: User,
        keyword: str | None,
        status_filter: str | None,
        priority: str | None,
        relation_status: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        project = self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        base_query = self._filtered_cases_query(
            project_id=project_id,
            keyword=keyword,
            status_filter=status_filter,
            priority=priority,
        )
        if relation_status in {"linked", "partial"}:
            base_query = base_query.where(SystemTestCase.relations.any())
        elif relation_status == "unlinked":
            base_query = base_query.where(~SystemTestCase.relations.any())

        total = self.db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
        statement = (
            base_query.options(
                selectinload(SystemTestCase.relations),
                selectinload(SystemTestCase.created_by),
            )
            .order_by(SystemTestCase.updated_at.desc(), SystemTestCase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            self._serialize_case(item, project_name=project.name)
            for item in self.db.scalars(statement).all()
        ]
        return {"items": items, "total": int(total)}

    def get_case(self, *, system_case_id: int, current_user: User) -> dict[str, Any]:
        system_case = self._get_case_by_id(system_case_id=system_case_id)
        project = self.permission_service.require_project_permission(
            current_user,
            system_case.project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        return self._serialize_case(system_case, project_name=project.name)

    def create_case(
        self,
        *,
        project_id: int,
        payload: SystemTestCaseCreateRequest,
        current_user: User,
    ) -> dict[str, Any]:
        project = self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        system_case = SystemTestCase(
            project_id=project_id,
            case_code=self._next_case_code(project_id),
            title=payload.title,
            business_module=payload.businessModule,
            test_objective=payload.testObjective,
            preconditions=payload.preconditions,
            test_scenario=payload.testScenario,
            system_behavior=payload.systemBehavior,
            expected_result=payload.expectedResult,
            data_requirements=payload.dataRequirements,
            risk_points=payload.riskPoints,
            priority=payload.priority,
            status=payload.status,
            tags=list(payload.tags),
            ai_generated=payload.aiGenerated,
            ai_confidence=payload.aiConfidence,
            owner=payload.owner,
            created_by_id=current_user.id,
        )
        self.db.add(system_case)
        self.db.commit()
        self.db.refresh(system_case)
        return self._serialize_case(system_case, project_name=project.name)

    def update_case(
        self,
        *,
        system_case_id: int,
        payload: SystemTestCaseUpdateRequest,
        current_user: User,
    ) -> dict[str, Any]:
        system_case = self._get_case_by_id(system_case_id=system_case_id)
        project = self.permission_service.require_project_permission(
            current_user,
            system_case.project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        updates = payload.model_dump(exclude_unset=True)
        field_map = {
            "businessModule": "business_module",
            "testObjective": "test_objective",
            "testScenario": "test_scenario",
            "systemBehavior": "system_behavior",
            "expectedResult": "expected_result",
            "dataRequirements": "data_requirements",
            "riskPoints": "risk_points",
        }
        for field, value in updates.items():
            setattr(system_case, field_map.get(field, field), value)
        self.db.commit()
        self.db.refresh(system_case)
        return self._serialize_case(system_case, project_name=project.name)

    def delete_case(self, *, system_case_id: int, current_user: User) -> None:
        system_case = self._get_case_by_id(system_case_id=system_case_id)
        self.permission_service.require_project_permission(
            current_user,
            system_case.project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        self.db.delete(system_case)
        self.db.commit()

    def batch_delete(
        self,
        *,
        project_id: int,
        payload: SystemTestCaseBatchDeleteRequest,
        current_user: User,
    ) -> dict[str, int]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        ids = [int(item) for item in payload.ids]
        cases = self.db.scalars(
            select(SystemTestCase).where(
                SystemTestCase.project_id == project_id,
                SystemTestCase.id.in_(ids),
            )
        ).all()
        for system_case in cases:
            self.db.delete(system_case)
        self.db.commit()
        return {"deletedCount": len(cases)}

    def duplicate_case(self, *, system_case_id: int, current_user: User) -> dict[str, Any]:
        source = self._get_case_by_id(system_case_id=system_case_id)
        project = self.permission_service.require_project_permission(
            current_user,
            source.project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        copied = SystemTestCase(
            project_id=source.project_id,
            case_code=self._next_case_code(source.project_id),
            title=f"{source.title} Copy",
            business_module=source.business_module,
            test_objective=source.test_objective,
            preconditions=source.preconditions,
            test_scenario=source.test_scenario,
            system_behavior=source.system_behavior,
            expected_result=source.expected_result,
            data_requirements=source.data_requirements,
            risk_points=source.risk_points,
            priority=source.priority,
            status="draft",
            tags=list(source.tags or []),
            ai_generated=source.ai_generated,
            ai_confidence=source.ai_confidence,
            owner=source.owner,
            created_by_id=current_user.id,
        )
        self.db.add(copied)
        self.db.commit()
        self.db.refresh(copied)
        return self._serialize_case(copied, project_name=project.name)

    def list_api_candidates(
        self,
        *,
        project_id: int,
        current_user: User,
        keyword: str | None,
        method: str | None,
        environment: str | None,
        execution_status: str | None,
        tag: str | None,
    ) -> list[dict[str, Any]]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        statement = (
            select(TestCase, ProjectEnvironment.name)
            .outerjoin(ProjectEnvironment, TestCase.environment_id == ProjectEnvironment.id)
            .where(TestCase.project_id == project_id)
            .order_by(TestCase.updated_at.desc(), TestCase.id.desc())
        )
        if keyword:
            pattern = f"%{keyword.strip()}%"
            statement = statement.where(or_(TestCase.name.ilike(pattern), TestCase.path.ilike(pattern)))
        if method:
            statement = statement.where(TestCase.method == method)
        if environment:
            statement = statement.where(ProjectEnvironment.name == environment)

        candidates = []
        for api_case, environment_name in self.db.execute(statement).all():
            item = self._serialize_api_candidate(api_case, environment_name=environment_name)
            if execution_status and item["executionStatus"] != execution_status:
                continue
            if tag and tag not in item["tags"]:
                continue
            candidates.append(item)
        return candidates

    def list_relations(self, *, system_case_id: int, current_user: User) -> list[dict[str, Any]]:
        system_case = self._get_case_by_id(system_case_id=system_case_id)
        self.permission_service.require_project_permission(
            current_user,
            system_case.project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        return [
            self._serialize_relation(relation)
            for relation in sorted(system_case.relations, key=lambda item: (item.sort_order, item.id))
        ]

    def replace_relations(
        self,
        *,
        system_case_id: int,
        payload: SystemCaseApiRelationsReplaceRequest,
        current_user: User,
    ) -> dict[str, Any]:
        system_case = self._get_case_by_id(system_case_id=system_case_id)
        project = self.permission_service.require_project_permission(
            current_user,
            system_case.project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        api_case_ids = [int(item.apiCaseId) for item in payload.relations]
        if api_case_ids:
            found_ids = set(
                self.db.scalars(
                    select(TestCase.id).where(
                        TestCase.project_id == system_case.project_id,
                        TestCase.id.in_(api_case_ids),
                    )
                ).all()
            )
            missing_ids = sorted(set(api_case_ids) - found_ids)
            if missing_ids:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="关联 API 用例不存在或不属于当前项目",
                )
        self.db.execute(
            delete(SystemCaseApiRelation).where(SystemCaseApiRelation.system_case_id == system_case.id)
        )
        self.db.flush()
        for item in payload.relations:
            self.db.add(
                SystemCaseApiRelation(
                    project_id=system_case.project_id,
                    system_case_id=system_case.id,
                    api_case_id=int(item.apiCaseId),
                    relation_type=item.relationType,
                    confidence=item.confidence,
                    sort_order=item.sortOrder,
                )
            )
        self.db.commit()
        refreshed = self._get_case_by_id(system_case_id=system_case.id)
        return {
            "relations": [
                self._serialize_relation(relation)
                for relation in sorted(refreshed.relations, key=lambda row: (row.sort_order, row.id))
            ],
            "systemCase": self._serialize_case(refreshed, project_name=project.name),
        }

    def statistics(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        total = self.db.scalar(
            select(func.count(SystemTestCase.id)).where(SystemTestCase.project_id == project_id)
        ) or 0
        linked = self.db.scalar(
            select(func.count(distinct(SystemCaseApiRelation.system_case_id))).where(
                SystemCaseApiRelation.project_id == project_id
            )
        ) or 0
        ai_generated = self.db.scalar(
            select(func.count(SystemTestCase.id)).where(
                SystemTestCase.project_id == project_id,
                SystemTestCase.ai_generated.is_(True),
            )
        ) or 0
        coverage = int(round((linked / total) * 100)) if total else 0
        return {
            "total": int(total),
            "linkedApiCaseCount": int(linked),
            "unlinkedSystemCaseCount": int(total - linked),
            "aiGeneratedCount": int(ai_generated),
            "apiRelationCoverageRate": coverage,
        }

    def _filtered_cases_query(
        self,
        *,
        project_id: int,
        keyword: str | None,
        status_filter: str | None,
        priority: str | None,
    ):
        statement = select(SystemTestCase).where(SystemTestCase.project_id == project_id)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            statement = statement.where(
                or_(
                    SystemTestCase.title.ilike(pattern),
                    SystemTestCase.business_module.ilike(pattern),
                    SystemTestCase.test_objective.ilike(pattern),
                )
            )
        if status_filter:
            statement = statement.where(SystemTestCase.status == status_filter)
        if priority:
            statement = statement.where(SystemTestCase.priority == priority)
        return statement

    def _get_case_by_id(self, *, system_case_id: int) -> SystemTestCase:
        system_case = self.db.scalar(
            select(SystemTestCase)
            .options(
                selectinload(SystemTestCase.relations),
                selectinload(SystemTestCase.created_by),
            )
            .where(SystemTestCase.id == system_case_id)
        )
        if system_case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="系统测试用例不存在")
        return system_case

    def _next_case_code(self, project_id: int) -> str:
        count = self.db.scalar(
            select(func.count(SystemTestCase.id)).where(SystemTestCase.project_id == project_id)
        ) or 0
        return f"STC-{int(count) + 1:06d}"

    def _serialize_case(self, system_case: SystemTestCase, *, project_name: str) -> dict[str, Any]:
        linked_api_case_ids = [str(relation.api_case_id) for relation in sorted(system_case.relations, key=lambda item: item.sort_order)]
        relation_status = "linked" if linked_api_case_ids else "unlinked"
        return {
            "id": str(system_case.id),
            "caseCode": system_case.case_code,
            "projectId": str(system_case.project_id),
            "projectName": project_name,
            "title": system_case.title,
            "businessModule": system_case.business_module,
            "testObjective": system_case.test_objective,
            "preconditions": system_case.preconditions,
            "testScenario": system_case.test_scenario,
            "systemBehavior": system_case.system_behavior,
            "expectedResult": system_case.expected_result,
            "dataRequirements": system_case.data_requirements,
            "riskPoints": system_case.risk_points,
            "priority": system_case.priority,
            "status": system_case.status,
            "tags": list(system_case.tags or []),
            "relationStatus": relation_status,
            "linkedApiCaseIds": linked_api_case_ids,
            "linkedApiCaseCount": len(linked_api_case_ids),
            "aiGenerated": bool(system_case.ai_generated),
            "aiConfidence": system_case.ai_confidence,
            "owner": system_case.owner,
            "createdBy": system_case.created_by.username if system_case.created_by else str(system_case.created_by_id),
            "createdAt": self._datetime_to_string(system_case.created_at),
            "updatedAt": self._datetime_to_string(system_case.updated_at),
        }

    def _serialize_api_candidate(self, api_case: TestCase, *, environment_name: str | None) -> dict[str, Any]:
        assertions = api_case.assertions if isinstance(api_case.assertions, list) else []
        return {
            "id": str(api_case.id),
            "projectId": str(api_case.project_id),
            "name": api_case.name,
            "method": api_case.method,
            "path": api_case.path,
            "environment": environment_name or "",
            "executionStatus": self._candidate_execution_status(api_case.last_execution_status),
            "assertionCount": len(assertions),
            "tags": [],
            "updatedAt": self._datetime_to_string(api_case.updated_at),
        }

    @staticmethod
    def _serialize_relation(relation: SystemCaseApiRelation) -> dict[str, Any]:
        return {
            "id": str(relation.id),
            "systemCaseId": str(relation.system_case_id),
            "apiCaseId": str(relation.api_case_id),
            "relationType": relation.relation_type,
            "confidence": relation.confidence,
            "sortOrder": relation.sort_order,
        }

    @staticmethod
    def _candidate_execution_status(value: str | None) -> str:
        public_status = public_execution_status(value)
        if public_status == "passed":
            return "passed"
        if public_status in {"failed", "error"}:
            return "failed"
        return "not_run"

    @staticmethod
    def _datetime_to_string(value: datetime | None) -> str:
        if value is None:
            return ""
        return value.isoformat()
