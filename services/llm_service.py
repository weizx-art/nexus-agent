import logging
import threading

from langchain_openai import ChatOpenAI

from core.config import settings

logger = logging.getLogger(__name__)

_llm_instance: ChatOpenAI | None = None
_streaming_llm_instance: ChatOpenAI | None = None
_llm_lock = threading.Lock()


class LLMService:
    """LLM 服务：封装 OpenAI 兼容 API 调用，懒加载单例"""

    @staticmethod
    def get_llm(temperature: float | None = None) -> ChatOpenAI:
        """获取非流式 LLM 实例（线程安全懒加载）"""
        global _llm_instance
        if _llm_instance is None:
            with _llm_lock:
                if _llm_instance is None:
                    if not settings.LLM_API_KEY:
                        raise ValueError("LLM_API_KEY 未配置，请在 .env 中设置")
                    _llm_instance = ChatOpenAI(
                        model=settings.LLM_MODEL_NAME,
                        api_key=settings.LLM_API_KEY,
                        base_url=settings.LLM_API_BASE,
                        streaming=False,
                        temperature=temperature if temperature is not None else 0.7,
                    )
                    logger.info("LLM 初始化完成: model=%s, base=%s, temperature=%s", 
                               settings.LLM_MODEL_NAME, settings.LLM_API_BASE, _llm_instance.temperature)
        return _llm_instance

    @staticmethod
    def get_streaming_llm(temperature: float | None = None) -> ChatOpenAI:
        """获取流式 LLM 实例（线程安全懒加载）"""
        global _streaming_llm_instance
        if _streaming_llm_instance is None:
            with _llm_lock:
                if _streaming_llm_instance is None:
                    if not settings.LLM_API_KEY:
                        raise ValueError("LLM_API_KEY 未配置，请在 .env 中设置")
                    _streaming_llm_instance = ChatOpenAI(
                        model=settings.LLM_MODEL_NAME,
                        api_key=settings.LLM_API_KEY,
                        base_url=settings.LLM_API_BASE,
                        streaming=True,
                        temperature=temperature if temperature is not None else 0.7,
                    )
                    logger.info("LLM 流式实例初始化完成: model=%s, temperature=%s", 
                               settings.LLM_MODEL_NAME, _streaming_llm_instance.temperature)
        return _streaming_llm_instance
