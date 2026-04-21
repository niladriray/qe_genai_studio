"""Shared chat LLM factory (OpenAI or Ollama) backed by settings_store."""

import os

from configs import settings_store
from utilities.customlogger import logger


def build_llm():
    """Pick the chat backend from runtime settings (editable via /config):
      llm.backend=ollama  → ChatOllama at llm.ollama.base_url / llm.ollama.model.
      anything else       → ChatOpenAI with llm.openai.model.
    """
    backend = (settings_store.get("llm.backend") or "openai").lower()
    if backend == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as e:
            raise RuntimeError(
                "llm.backend=ollama but `langchain-ollama` is not installed. "
                "Run: pip install langchain-ollama"
            ) from e
        model = settings_store.get("llm.ollama.model")
        base_url = settings_store.get("llm.ollama.base_url")
        logger.info(f"Using Ollama LLM: model={model} base_url={base_url}")
        extra_kwargs = {}
        if not settings_store.get("llm.ollama.think", False):
            extra_kwargs["think"] = False
        return ChatOllama(model=model, base_url=base_url, temperature=0.7, **extra_kwargs)

    from langchain_openai import ChatOpenAI
    model = settings_store.get("llm.openai.model")
    api_key = settings_store.get("llm.openai.api_key") or ""
    if api_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = api_key
    logger.info(f"Using OpenAI LLM: model={model}")
    return ChatOpenAI(model=model, temperature=0.7, max_tokens=4096)
