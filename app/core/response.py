from datetime import date, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def normalize_response_data(data: Any) -> Any:
    if isinstance(data, datetime):
        return format_datetime(data)
    if isinstance(data, date):
        return format_date(data)
    if isinstance(data, BaseModel):
        return normalize_response_data(data.model_dump(mode="python"))
    if isinstance(data, dict):
        return {key: normalize_response_data(value) for key, value in data.items()}
    if isinstance(data, (list, tuple, set)):
        return [normalize_response_data(item) for item in data]
    return data


def success(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": jsonable_encoder(normalize_response_data(data)),
    }
