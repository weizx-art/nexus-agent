import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator, Optional

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from weaviate.exceptions import WeaviateBaseError

from models import Document, Segment
from services.embedding_service import EmbeddingService
from services.llm_service import LLMService
from services.vector_service import VectorService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个综合业务智能助手。你的职责是帮助用户解答问题、完成任务。

当提供了知识库参考内容时，请优先基于这些参考信息来回答。如果参考信息不足以回答问题，你可以结合自身知识补充，但需要说明哪些内容来自知识库、哪些是你的补充。

回答要求：
- 使用中文回答
- 条理清晰，必要时使用列表或分段
- 如果无法确定答案，请如实告知，不要编造信息
- 保持专业、友好的语气"""


def _make_retrieval_tool(db: AsyncSession, dataset_ids: list[uuid.UUID]):
    """工厂函数：创建绑定了特定知识库的检索工具"""

    @tool
    async def knowledge_retrieval(query: str) -> str:
        """从知识库中检索与用户问题相关的内容。当需要查找专业知识、公司制度、操作规范等信息时调用此工具。"""
        try:
            query_vector = await EmbeddingService.embed_query(query)

            # 并行检索多个知识库
            tasks = [
                VectorService.search(query_vector, str(ds_id), k=5, score_threshold=0.0)
                for ds_id in dataset_ids
            ]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

            all_results = []
            for ds_id, results in zip(dataset_ids, results_list):
                if isinstance(results, Exception):
                    logger.warning("知识库 %s 检索失败: %s", ds_id, results)
                    continue
                for r in results:
                    r["dataset_id"] = str(ds_id)
                all_results.extend(results)

            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            top_results = all_results[:5]

            if not top_results:
                return "未在知识库中找到相关内容。"

            seg_ids = [uuid.UUID(r["segment_id"]) for r in top_results if r.get("segment_id")]
            if not seg_ids:
                return "未在知识库中找到相关内容。"

            stmt = select(Segment, Document).join(Document, Segment.document_id == Document.id).where(Segment.id.in_(seg_ids))
            result = await db.execute(stmt)
            seg_doc_map = {seg.id: (seg, doc) for seg, doc in result.all()}

            segments = []
            for r in top_results:
                seg_id = r.get("segment_id")
                if seg_id and uuid.UUID(seg_id) in seg_doc_map:
                    seg, doc = seg_doc_map[uuid.UUID(seg_id)]
                    segments.append({
                        "content": seg.content,
                        "source": doc.name if doc else "未知文档",
                        "score": round(r.get("score", 0), 3),
                    })

            if not segments:
                return "未在知识库中找到相关内容。"

            parts = []
            for i, s in enumerate(segments, 1):
                parts.append(f"【参考{i}】来源: {s['source']}（相关度: {s['score']}）\n{s['content']}")
            return "\n\n".join(parts)

        except (WeaviateBaseError, ValueError) as e:
            logger.warning("知识库检索失败: %s", e)
            return f"知识库检索出错: {e}"

    return knowledge_retrieval


def _build_system_prompt(base_prompt: str, summary: str | None = None) -> str:
    """构建 system prompt，可选注入历史摘要"""
    if summary:
        return f"{base_prompt}\n\n以下是之前对话的摘要，供你参考上下文：\n{summary}"
    return base_prompt


def _build_langchain_messages(
    chat_history: list[dict],
    user_message: str,
) -> list:
    """将对话历史转换 LangChain 消息格式（不含 system prompt）"""
    messages = []
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=user_message))
    return messages


async def run_chat_stream(
    db: AsyncSession,
    user_message: str,
    chat_history: list[dict],
    dataset_ids: Optional[list[uuid.UUID]] = None,
    summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """执行流式对话，yield SSE 格式的 token"""

    llm = LLMService.get_streaming_llm()
    system_prompt = _build_system_prompt(SYSTEM_PROMPT, summary)
    messages = _build_langchain_messages(chat_history, user_message)

    if dataset_ids:
        retrieval_tool = _make_retrieval_tool(db, dataset_ids)
        agent = create_agent(llm, [retrieval_tool], system_prompt=system_prompt)

        async for event in agent.astream_events(
            {"messages": messages},
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", None)
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse_data({"type": "token", "content": chunk.content})
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                yield _sse_data({"type": "tool_call", "tool": tool_name, "status": "calling"})
            elif kind == "on_tool_end":
                raw_output = event.get("data", {}).get("output", "")
                tool_output = raw_output.content if hasattr(raw_output, "content") else str(raw_output)
                preview = tool_output[:200] + "..." if len(tool_output) > 200 else tool_output
                yield _sse_data({"type": "tool_result", "content": preview})

        yield _sse_data({"type": "done"})
    else:
        agent = create_agent(llm, tools=[], system_prompt=system_prompt)

        async for event in agent.astream_events(
            {"messages": messages},
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", None)
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse_data({"type": "token", "content": chunk.content})

        yield _sse_data({"type": "done"})


async def run_chat(
    db: AsyncSession,
    user_message: str,
    chat_history: list[dict],
    dataset_ids: Optional[list[uuid.UUID]] = None,
    summary: Optional[str] = None,
) -> dict:
    """执行非流式对话，返回完整响应"""

    llm = LLMService.get_llm()
    system_prompt = _build_system_prompt(SYSTEM_PROMPT, summary)
    messages = _build_langchain_messages(chat_history, user_message)

    if dataset_ids:
        retrieval_tool = _make_retrieval_tool(db, dataset_ids)
        agent = create_agent(llm, [retrieval_tool], system_prompt=system_prompt)
        result = await agent.ainvoke({"messages": messages})

        final_messages = result.get("messages", [])
        answer = ""
        context_parts = []
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content:
                answer = msg.content
                break

        for msg in final_messages:
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "knowledge_retrieval":
                        context_parts.append(tc.get("args", {}))

        return {"answer": answer, "context": context_parts}
    else:
        agent = create_agent(llm, tools=[], system_prompt=system_prompt)
        result = await agent.ainvoke({"messages": messages})
        return {"answer": result["messages"][-1].content, "context": []}


def _sse_data(data: dict) -> str:
    """构造 SSE data 行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
