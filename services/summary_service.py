import logging
import uuid

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import auto_commit
from models import Conversation, Message
from services.llm_service import LLMService

logger = logging.getLogger(__name__)

RECENT_TURNS = 10
SUMMARY_TRIGGER_TURNS = 15

SUMMARY_PROMPT = """你是一个对话摘要助手。请将以下对话历史压缩为一段简洁的摘要，要求：

1. 保留关键信息：用户的核心需求、重要结论、用户偏好
2. 去除冗余：问候语、重复内容、无意义的过渡
3. 如果提供了旧摘要，请将其与新内容合并，生成一份完整且连贯的新摘要
4. 使用第三人称描述（"用户询问了..."、"助手建议..."）
5. 摘要长度控制在 500 字以内

{existing_summary_section}

以下是需要摘要的对话内容：

{conversation_text}

请直接输出摘要内容，不要添加任何前缀或解释。"""


class SummaryService:
    """对话摘要服务"""

    @classmethod
    async def maybe_summarize(cls, db: AsyncSession, conversation_id: uuid.UUID):
        """检查是否需要摘要，如果需要则执行。适合作为后台任务调用。"""
        try:
            conv = await db.get(Conversation, conversation_id)
            if not conv:
                return

            # 统计总消息数（user + assistant）
            total_count = (await db.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role.in_(["user", "assistant"]),
                )
            )).scalar() or 0

            if total_count <= SUMMARY_TRIGGER_TURNS * 2:
                return

            # 获取需要摘要的旧消息（排除最近 RECENT_TURNS * 2 条）
            recent_ids_q = (
                select(Message.id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role.in_(["user", "assistant"]),
                )
                .order_by(desc(Message.created_at))
                .limit(RECENT_TURNS * 2)
            )
            recent_ids = (await db.execute(recent_ids_q)).scalars().all()

            old_messages_q = (
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role.in_(["user", "assistant"]),
                )
            )
            if recent_ids:
                old_messages_q = old_messages_q.where(Message.id.notin_(recent_ids))
            old_messages_q = old_messages_q.order_by(Message.created_at)
            old_messages = (await db.execute(old_messages_q)).scalars().all()

            if not old_messages:
                return

            # 格式化旧消息
            conversation_text = "\n".join(
                f"{'用户' if msg.role == 'user' else '助手'}: {msg.content}"
                for msg in old_messages
            )

            existing_summary_section = ""
            if conv.summary:
                existing_summary_section = f"旧摘要：\n{conv.summary}\n"

            new_summary = await cls._generate_summary(
                existing_summary_section, conversation_text
            )

            if new_summary:
                async with auto_commit(db):
                    conv.summary = new_summary
                logger.info(
                    "对话 %s 摘要已更新 (旧消息 %d 条 → %d 字)",
                    conversation_id, len(old_messages), len(new_summary),
                )

        except SQLAlchemyError:
            logger.warning("对话摘要生成失败 conversation_id=%s", conversation_id, exc_info=True)

    @classmethod
    async def _generate_summary(
        cls, existing_summary_section: str, conversation_text: str
    ) -> str | None:
        """调用 LLM 生成摘要"""
        try:
            llm = LLMService.get_llm(temperature=0.3)

            prompt = SUMMARY_PROMPT.format(
                existing_summary_section=existing_summary_section or "（无旧摘要）",
                conversation_text=conversation_text,
            )

            messages: list[BaseMessage] = [
                SystemMessage(content="你是一个专业的对话摘要助手，擅长提取对话中的关键信息并生成简洁摘要。"),
                HumanMessage(content=prompt),
            ]

            result = await llm.ainvoke(messages)
            return result.content.strip() if result.content else None

        except (ValueError, RuntimeError):
            logger.warning("LLM 摘要生成失败", exc_info=True)
            return None
