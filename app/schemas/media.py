from datetime import datetime

from pydantic import BaseModel


class MediaObjectRead(BaseModel):
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    download_url: str
    created_at: datetime

    model_config = {"from_attributes": True}

