from typing import Optional
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_chat_llm(
    streaming: bool = True,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> ChatOpenAI:
    """Factory function returning a ChatOpenAI client configured for Token Harbor DeepSeek."""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.LLM_MODEL_NAME,
        api_key=settings.TOKEN_HARBOR_API_KEY,
        base_url=settings.TOKEN_HARBOR_BASE_URL,
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        max_tokens=max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS,
        streaming=streaming,
    )
