import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Account(Base):
    """账号模型"""

    __tablename__ = "account"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    avatar: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    password: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default="")
    password_salt: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default="")
    last_login_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    last_login_ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    @property
    def is_password_set(self) -> bool:
        return self.password is not None and self.password != ""
