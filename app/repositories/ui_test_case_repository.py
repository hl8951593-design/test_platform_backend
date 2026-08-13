from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.ui_test_case import UiTestCase, UiTestCaseVersion


class UiTestCaseRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _detail_options():
        return (
            joinedload(UiTestCase.default_environment),
            joinedload(UiTestCase.current_version),
        )

    def list_by_project(
        self,
        *,
        project_id: int,
        keyword: str | None,
        status: str | None,
        environment_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[UiTestCase], int]:
        filters = [
            UiTestCase.project_id == project_id,
            UiTestCase.is_deleted.is_(False),
        ]
        if keyword:
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    UiTestCase.name.ilike(pattern),
                    UiTestCase.description.ilike(pattern),
                    UiTestCase.public_id.ilike(pattern),
                )
            )
        if status:
            filters.append(UiTestCase.status == status)
        if environment_id is not None:
            filters.append(UiTestCase.default_environment_id == environment_id)

        total = int(
            self.db.scalar(
                select(func.count()).select_from(UiTestCase).where(*filters)
            )
            or 0
        )
        statement = (
            select(UiTestCase)
            .options(*self._detail_options())
            .where(*filters)
            .order_by(UiTestCase.updated_at.desc(), UiTestCase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(statement).unique().all()), total

    def get_by_public_id(
        self,
        case_public_id: str,
        *,
        project_id: int | None = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> UiTestCase | None:
        filters = [UiTestCase.public_id == case_public_id]
        if project_id is not None:
            filters.append(UiTestCase.project_id == project_id)
        if not include_deleted:
            filters.append(UiTestCase.is_deleted.is_(False))
        statement = (
            select(UiTestCase)
            .options(*self._detail_options())
            .where(*filters)
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def add_case(self, ui_test_case: UiTestCase) -> UiTestCase:
        self.db.add(ui_test_case)
        self.db.flush()
        return ui_test_case

    def add_version(self, version: UiTestCaseVersion) -> UiTestCaseVersion:
        self.db.add(version)
        self.db.flush()
        return version

    def get_version(
        self,
        *,
        ui_test_case_id: int,
        version_number: int,
    ) -> UiTestCaseVersion | None:
        statement = select(UiTestCaseVersion).where(
            UiTestCaseVersion.ui_test_case_id == ui_test_case_id,
            UiTestCaseVersion.version_number == version_number,
        )
        return self.db.scalar(statement)

    def list_versions(self, ui_test_case_id: int) -> list[UiTestCaseVersion]:
        statement = (
            select(UiTestCaseVersion)
            .where(UiTestCaseVersion.ui_test_case_id == ui_test_case_id)
            .order_by(UiTestCaseVersion.version_number.desc())
        )
        return list(self.db.scalars(statement).all())
