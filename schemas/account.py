import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from utils.security import validate_password_strength


class CurrentUserOut(BaseModel):
    """当前登录账号信息响应"""

    id: str
    name: str
    username: str
    avatar: str
    last_login_at: datetime
    last_login_ip: str
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _to_str(cls, v):
        return str(v) if v is not None else v


class UpdateAccountReq(BaseModel):
    """账号信息部分更新请求（所有字段可选，至少传一个）"""

    name: Optional[str] = Field(default=None, min_length=3, max_length=30, description="账号名称")
    avatar: Optional[str] = Field(default=None, max_length=500, description="头像 URL")
    password: Optional[str] = Field(default=None, description="新密码")

    @field_validator("avatar")
    @classmethod
    def _validate_avatar(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^https?://", v):
            raise ValueError("头像必须必须为合法的 URL 地址")
        return v

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            validate_password_strength(v)
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if self.name is None and self.avatar is None and self.password is None:
            raise ValueError("至少需要提供一个更新字段")
        return self
