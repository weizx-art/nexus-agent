from enum import Enum
from typing import Any


class HttpCode(str, Enum):
    """响应业务码"""

    SUCCESS = "success"
    FAIL = "fail"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    VALIDATE_ERROR = "validate_error"


def success_json(data: Any = None) -> dict:
    return {"code": HttpCode.SUCCESS, "message": "", "data": data}


def success_message(msg: str = "") -> dict:
    return {"code": HttpCode.SUCCESS, "message": msg, "data": {}}
