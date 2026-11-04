from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChatReq(BaseModel):
    """对话请求"""

    message: str = Field(..., min_length=1, max_length=10000, description="用户消息内容")
    conversation_id: Optional[UUID] = Field(default=None, description="对话 ID，为空则创建新对话")
    dataset_ids: Optional[list[UUID]] = Field(default=None, description="关联知识库 ID 列表，为空则不使用知识库")


class ConversationOut(BaseModel):
    """对话列表项"""

    id: str
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class MessageOut(BaseModel):
    """消息详情"""

    id: str
    conversation_id: str
    role: str
    content: str
    context: Optional[list[dict]] = None
    token_count: int = 0
    created_at: datetime


class ChatResponseOut(BaseModel):
    """对话响应（非流式）"""

    conversation_id: str
    message_id: str
    content: str
    context: Optional[list[dict]] = None
    token_count: int = 0
