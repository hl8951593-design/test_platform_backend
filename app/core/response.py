from typing import Any


def success(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": data,
    }

