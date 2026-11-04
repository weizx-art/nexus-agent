import re
from pydantic import BaseModel, Field, field_validator

USERNAME_PATTERN = r"^[a-zA-Z0-9_]{3,30}$"
USERNAME_HINT = "用户名须为 3-30 位字母、数字或下划线"


class PasswordLoginReq(BaseModel):
    """账号密码登录请求"""

    username: str = Field(..., min_length=3, max_length=30, description="用户名")
    password: str = Field(..., min_length=8, max_length=16, description="密码")

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        if not re.match(USERNAME_PATTERN, v):
            raise ValueError(USERNAME_HINT)
        return v


class RegisterReq(BaseModel):
    """注册请求"""

    username: str = Field(..., min_length=3, max_length=30, description="用户名")
    password: str = Field(..., min_length=8, max_length=16, description="密码")
    name: str = Field(default="", max_length=64, description="昵称")

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        if not re.match(USERNAME_PATTERN, v):
            raise ValueError(USERNAME_HINT)
        return v
