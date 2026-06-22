from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media import MediaObject


class MediaRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **values) -> MediaObject:
        media = MediaObject(**values)
        self.db.add(media)
        self.db.commit()
        self.db.refresh(media)
        return media

    def list_by_ids(self, media_ids: list[int]) -> list[MediaObject]:
        if not media_ids:
            return []
        return list(self.db.scalars(select(MediaObject).where(MediaObject.id.in_(media_ids))).all())

    def get_by_id(self, *, project_id: int, media_id: int) -> MediaObject | None:
        return self.db.scalar(
            select(MediaObject).where(
                MediaObject.project_id == project_id,
                MediaObject.id == media_id,
            )
        )

    def list_by_project(self, project_id: int) -> list[MediaObject]:
        return list(
            self.db.scalars(
                select(MediaObject).where(MediaObject.project_id == project_id)
            ).all()
        )

    def delete(self, media: MediaObject) -> None:
        self.db.delete(media)
        self.db.commit()
