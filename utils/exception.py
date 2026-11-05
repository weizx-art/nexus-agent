from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from utils.response import HttpCode
import logging

logger = logging.getLogger(__name__)


class BusinessException(Exception):
    """业务异常基类"""

    code: HttpCode = HttpCode.FAIL
    http_status: int = 200

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(message)


class FailException(BusinessException):
    code = HttpCode.FAIL


class NotFoundException(BusinessException):
    code = HttpCode.NOT_FOUND


class UnauthorizedException(BusinessException):
    code = HttpCode.UNAUTHORIZED
    http_status = 401


class ForbiddenException(BusinessException):
    code = HttpCode.FORBIDDEN
    http_status = 403


class ValidateErrorException(BusinessException):
    code = HttpCode.VALIDATE_ERROR


def register_exception_handlers(app):
    """注册全局异常处理器，统一输出 {code, message, data}"""

    @app.exception_handler(BusinessException)
    async def _biz(_: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "data": {}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validate(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        msg = ""
        if errors:
            first = errors[0]
            loc = [str(x) for x in first.get("loc", []) if x not in ("body", "query", "path")]
            msg = f"{'/'.join(loc)}: {first.get('msg')}"
        safe_errors = []
        for e in errors:
            safe_errors.append({
                "loc": [str(x) for x in e.get("loc", [])],
                "msg": str(e.get("msg", "")),
                "type": str(e.get("type", "")),
            })
        return JSONResponse(
            status_code=200,
            content={"code": HttpCode.VALIDATE_ERROR, "message": msg, "data": safe_errors},
        )

    @app.exception_handler(Exception)
    async def _generic(_: Request, exc: Exception):
        logger.exception("未处理的异常: %s", exc)
        return JSONResponse(
            status_code=200,
            content={"code": HttpCode.FAIL, "message": "服务器内部错误，请稍后重试", "data": {}},
        )
