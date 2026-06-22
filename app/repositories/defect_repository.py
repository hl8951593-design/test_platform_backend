from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.defect import Defect
from app.models.media import MediaObject
from app.models.user import User


class DefectRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_project(
        self,
        *,
        project_id: int,
        keyword: str | None,
        status: str | None,
        urgency: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Defect], int]:
        conditions = [Defect.project_id == project_id]
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    Defect.title.ilike(pattern),
                    Defect.assignee.ilike(pattern),
                    Defect.content_html.ilike(pattern),
                    User.username.ilike(pattern),
                    User.account.ilike(pattern),
                )
            )
        if status:
            conditions.append(Defect.status == status)
        if urgency:
            conditions.append(Defect.urgency == urgency)

        base = select(Defect).outerjoin(User, Defect.reporter_id == User.id).where(*conditions)
        total = self.db.scalar(
            select(func.count(Defect.id)).select_from(Defect).outerjoin(
                User, Defect.reporter_id == User.id
            ).where(*conditions)
        ) or 0
        statement = (
            base.options(selectinload(Defect.reporter), selectinload(Defect.attachments))
            .order_by(Defect.updated_at.desc(), Defect.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(statement).all()), int(total)

    def get_by_id(self, *, project_id: int, defect_id: int) -> Defect | None:
        statement = (
            select(Defect)
            .options(selectinload(Defect.reporter), selectinload(Defect.attachments))
            .where(Defect.project_id == project_id, Defect.id == defect_id)
        )
        return self.db.scalar(statement)

    def create(
        self,
        *,
        project_id: int,
        title: str,
        assignee: str | None,
        bug_type: str,
        urgency: str,
        status: str,
        content_html: str,
        reporter_id: int,
    ) -> Defect:
        defect = Defect(
            project_id=project_id,
            title=title,
            assignee=assignee,
            bug_type=bug_type,
            urgency=urgency,
            status=status,
            content_html=content_html,
            reporter_id=reporter_id,
        )
        self.db.add(defect)
        self.db.commit()
        created_defect = self.get_by_id(project_id=project_id, defect_id=defect.id)
        return created_defect or defect

    def update(
        self,
        *,
        defect: Defect,
        title: str,
        assignee: str | None,
        bug_type: str,
        urgency: str,
        status: str,
        content_html: str,
    ) -> Defect:
        defect.title = title
        defect.assignee = assignee
        defect.bug_type = bug_type
        defect.urgency = urgency
        defect.status = status
        defect.content_html = content_html
        self.db.commit()
        updated_defect = self.get_by_id(project_id=defect.project_id, defect_id=defect.id)
        return updated_defect or defect

    def update_status(self, *, defect: Defect, status: str) -> Defect:
        defect.status = status
        self.db.commit()
        updated_defect = self.get_by_id(project_id=defect.project_id, defect_id=defect.id)
        return updated_defect or defect

    def delete(self, defect: Defect) -> None:
        self.db.delete(defect)
        self.db.commit()

    def replace_attachments(self, *, defect: Defect, attachments: list[MediaObject]) -> Defect:
        defect.attachments = attachments
        self.db.commit()
        updated = self.get_by_id(project_id=defect.project_id, defect_id=defect.id)
        return updated or defect
