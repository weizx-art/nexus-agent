import uuid
from datetime import datetime
from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Dataset(Base):
    """知识库表"""

    __tablename__ = "dataset"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_dataset_account_name"),
        Index("ix_dataset_account_id", "account_id"),
        Index("ix_dataset_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
