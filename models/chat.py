import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Conversation(Base):
    """对话会话表"""

    __tablename__ = "conversation"
    __table_args__ = (
        Index("ix_conversation_account_id", "account_id"),
        Index("ix_conversation_updated_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")
    dataset_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # 历史对话摘要：当对话轮次超过阈值时，早期消息会被压缩为摘要
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())


class Message(Base):
    """对话消息表"""

    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_conversation_id", "conversation_id"),
        Index("ix_message_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 知识库引用上下文（RAG 检索到的片段信息，JSON 格式）
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieval_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    retrieval_k: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retrieval_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
