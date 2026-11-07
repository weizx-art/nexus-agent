"""对话服务：管理对话历史、协调 Agent 调用"""

import asyncio
import json
import logging
import uuid

from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import auto_commit
from models import Conversation, Dataset, Message
from services.chat_agent import run_chat, run_chat_stream
from services.summary_service import SummaryService, RECENT_TURNS
from utils.exception import BusinessException, NotFoundException, ValidateErrorException

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


class ChatService:
    """对话服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Conversation CRUD ----------

    async def create_conversation(self, account_id: uuid.UUID, title: str = "新对话") -> Conversation:
        conv = Conversation(account_id=account_id, title=title)
        async with auto_commit(self.db):
            self.db.add(conv)
        return conv

    async def get_conversation(self, account_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        conv = await self.db.get(Conversation, conversation_id)
        if not conv or conv.account_id != account_id:
            raise NotFoundException("对话不存在")
        return conv

    async def list_conversations(self, account_id: uuid.UUID, current_page: int, page_size: int) -> dict:
        q = select(Conversation).where(Conversation.account_id == account_id)
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0

        rows_q = q.order_by(desc(Conversation.updated_at)).offset((current_page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()

        if not rows:
            return {
                "items": [],
                "paginator": {
                    "current_page": current_page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": 0,
                },
            }

        # 批量查询消息计数，避免 N+1
        conv_ids = [conv.id for conv in rows]
        msg_count_q = (
            select(Message.conversation_id, func.count().label("count"))
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
        )
        msg_count_result = await self.db.execute(msg_count_q)
        msg_counts = {row.conversation_id: row.count for row in msg_count_result.all()}

        items = []
        for conv in rows:
            items.append({
                "id": str(conv.id),
                "title": conv.title,
                "message_count": msg_counts.get(conv.id, 0),
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
            })

        return {
            "items": items,
            "paginator": {
                "current_page": current_page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        }

    async def delete_conversation(self, account_id: uuid.UUID, conversation_id: uuid.UUID):
        await self.get_conversation(account_id, conversation_id)
        async with auto_commit(self.db):
            await self.db.execute(delete(Message).where(Message.conversation_id == conversation_id))
            await self.db.execute(delete(Conversation).where(Conversation.id == conversation_id))

    async def update_conversation_title(self, account_id: uuid.UUID, conversation_id: uuid.UUID, title: str):
        conv = await self.get_conversation(account_id, conversation_id)
        async with auto_commit(self.db):
            conv.title = title

    # ---------- Message ----------

    async def get_messages(self, account_id: uuid.UUID, conversation_id: uuid.UUID) -> list[dict]:
        await self.get_conversation(account_id, conversation_id)
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        return [self._message_to_dict(msg) for msg in messages]

    async def get_chat_history(self, conversation_id: uuid.UUID) -> tuple[str | None, list[dict]]:
        """获取对话摘要 + 最近 N 轮对话历史（不含 system 消息）

        返回: (summary, recent_messages)
        """
        conv = await self.db.get(Conversation, conversation_id)
        summary = conv.summary if conv else None

        result = await self.db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(desc(Message.created_at))
            .limit(RECENT_TURNS * 2)
        )
        messages = list(reversed(result.scalars().all()))
        return summary, [{"role": msg.role, "content": msg.content} for msg in messages]

    async def save_user_message(
        self, conversation_id: uuid.UUID, content: str, token_count: int = 0
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            token_count=token_count,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def save_assistant_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        context: list[dict] | None = None,
        token_count: int = 0,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            context=json.dumps(context, ensure_ascii=False) if context else None,
            token_count=token_count,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    # ---------- Chat 执行 ----------

    async def chat(
        self,
        account_id: uuid.UUID,
        user_message: str,
        conversation_id: uuid.UUID | None = None,
        dataset_ids: list[uuid.UUID] | None = None,
    ) -> dict:
        """非流式对话"""
        if dataset_ids:
            await self._validate_datasets(account_id, dataset_ids)

        if conversation_id:
            conv = await self.get_conversation(account_id, conversation_id)
        else:
            title = user_message[:50] + ("..." if len(user_message) > 50 else "")
            conv = await self.create_conversation(account_id, title)
            conversation_id = conv.id

        summary, chat_history = await self.get_chat_history(conversation_id)

        await self.save_user_message(conversation_id, user_message)

        result = await run_chat(self.db, user_message, chat_history, dataset_ids, summary=summary)

        await self.save_assistant_message(
            conversation_id,
            result["answer"],
            context=result.get("context"),
            token_count=len(result["answer"]),
        )

        async with auto_commit(self.db):
            pass

        # 后台异步检查并更新摘要，不阻塞响应
        task = asyncio.create_task(self._background_summarize(conversation_id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return {
            "conversation_id": str(conversation_id),
            "message_id": str(uuid.uuid4()),
            "content": result["answer"],
            "context": result.get("context", []),
        }

    async def chat_stream(
        self,
        account_id: uuid.UUID,
        user_message: str,
        conversation_id: uuid.UUID | None = None,
        dataset_ids: list[uuid.UUID] | None = None,
    ):
        """流式对话，返回 SSE 事件生成器"""
        try:
            if dataset_ids:
                await self._validate_datasets(account_id, dataset_ids)

            if conversation_id:
                conv = await self.get_conversation(account_id, conversation_id)
            else:
                title = user_message[:50] + ("..." if len(user_message) > 50 else "")
                conv = await self.create_conversation(account_id, title)
                conversation_id = conv.id

            # 发送 start 事件，携带 conversation_id
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': str(conversation_id)}, ensure_ascii=False)}\n\n"

            summary, chat_history = await self.get_chat_history(conversation_id)

            await self.save_user_message(conversation_id, user_message)
            await self.db.commit()
        except (SQLAlchemyError, BusinessException) as e:
            error_msg = e.message if isinstance(e, BusinessException) else '服务异常，请稍后重试'
            logger.error("流式对话准备阶段异常: %s", error_msg, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg}, ensure_ascii=False)}\n\n"
            return

        answer_parts = []
        try:
            async for sse_event in run_chat_stream(self.db, user_message, chat_history, dataset_ids, summary=summary):
                yield sse_event
                if sse_event.startswith("data: "):
                    try:
                        data = json.loads(sse_event[6:].strip())
                        if data.get("type") == "token" and "content" in data:
                            answer_parts.append(data["content"])
                    except (json.JSONDecodeError, KeyError):
                        pass
        except (ValueError, RuntimeError, BusinessException) as e:
            error_msg = e.message if isinstance(e, BusinessException) else '服务异常，请稍后重试'
            logger.error("流式对话生成阶段异常: %s", error_msg, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg}, ensure_ascii=False)}\n\n"

        answer = "".join(answer_parts)

        if answer:
            try:
                await self.save_assistant_message(conversation_id, answer, token_count=len(answer))
                await self.db.commit()
            except SQLAlchemyError:
                logger.warning("保存助手消息失败", exc_info=True)

        # 后台异步检查并更新摘要
        task = asyncio.create_task(self._background_summarize(conversation_id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # ---------- 私有方法 ----------

    async def _background_summarize(self, conversation_id: uuid.UUID):
        """后台摘要任务：使用独立的数据库会话"""
        from core.database import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as db:
                await SummaryService.maybe_summarize(db, conversation_id)
        except SQLAlchemyError:
            logger.warning("后台摘要任务失败 conversation_id=%s", conversation_id, exc_info=True)

    async def _validate_datasets(self, account_id: uuid.UUID, dataset_ids: list[uuid.UUID]):
        """验证知识库是否属于当前用户"""
        for ds_id in dataset_ids:
            ds = await self.db.get(Dataset, ds_id)
            if not ds or ds.account_id != account_id:
                raise ValidateErrorException(f"知识库 {ds_id} 不存在或无权访问")

    def _message_to_dict(self, msg: Message) -> dict:
        context = None
        if msg.context:
            try:
                context = json.loads(msg.context)
            except (json.JSONDecodeError, TypeError):
                context = None
        return {
            "id": str(msg.id),
            "conversation_id": str(msg.conversation_id),
            "role": msg.role,
            "content": msg.content,
            "context": context,
            "token_count": msg.token_count,
            "created_at": msg.created_at.isoformat(),
        }
