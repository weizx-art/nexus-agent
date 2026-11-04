import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import Account
from schemas.chat import ChatReq
from services.chat_service import ChatService
from utils.deps import get_current_user
from utils.response import success_json, success_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["智能对话"])


@router.post("/completions")
async def chat_completions(
    req: ChatReq,
    current_user: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """非流式对话：一次性返回完整回复"""
    service = ChatService(db)
    result = await service.chat(
        account_id=current_user.id,
        user_message=req.message,
        conversation_id=req.conversation_id,
        dataset_ids=req.dataset_ids,
    )
    return success_json(result)


@router.post("/completions/stream")
async def chat_completions_stream(
    req: ChatReq,
    current_user: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """流式对话：SSE 逐 token 返回"""
    service = ChatService(db)

    async def event_generator():
        try:
            async for sse_data in service.chat_stream(
                account_id=current_user.id,
                user_message=req.message,
                conversation_id=req.conversation_id,
                dataset_ids=req.dataset_ids,
            ):
                yield sse_data
        except (SQLAlchemyError, ValueError, RuntimeError) as e:
            logger.error("流式对话异常: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 对话管理接口 ====================


@router.get("/conversations")
async def list_conversations(
    current_page: int = Query(default=1, ge=1, description="当前页"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    current_user: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取对话列表"""
    service = ChatService(db)
    result = await service.list_conversations(current_user.id, current_page, page_size)
    return success_json(result)


@router.get("/conversations/{conversation_id}")
async def get_conversation_messages(
    conversation_id: UUID,
    current_user: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取指定对话的消息列表"""
    service = ChatService(db)
    messages = await service.get_messages(current_user.id, conversation_id)
    return success_json(messages)


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: UUID,
    body: dict,
    current_user: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新对话标题"""
    title = body.get("title")
    if not title or not title.strip():
        from utils.exception import ValidateErrorException
        raise ValidateErrorException("标题不能为空")
    service = ChatService(db)
    await service.update_conversation_title(current_user.id, conversation_id, title.strip())
    return success_message("更新成功")


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    current_user: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除对话"""
    service = ChatService(db)
    await service.delete_conversation(current_user.id, conversation_id)
    return success_message("删除成功")
