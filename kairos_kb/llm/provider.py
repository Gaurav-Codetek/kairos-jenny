"""Which LLM service Kairos talks to: Azure OpenAI, the OpenAI API platform, or NVIDIA Nemotron on Nebius.

LLM_PROVIDER picks it: "azure" (the default, Azure AI Foundry deployments), "openai" (the OpenAI API platform, kept
ready as a fallback) or "nebius" (NVIDIA Nemotron on Nebius Token Factory, an OpenAI-compatible API). A key in the
environment never switches the service on its own. Every chat model, raw client and embedding call in Kairos comes
from here, so moving between them is one setting.

Model names: on OpenAI they are model ids (OPENAI_MODEL, e.g. gpt-6-luna); on Azure they are deployment names
(AZURE_OPENAI_DEPLOYMENT); on Nebius they are Token Factory model ids (NEBIUS_MODEL, e.g.
nvidia/Nemotron-3.5-Super-VL).

Embeddings are separate (EMBEDDING_PROVIDER): by default they follow LLM_PROVIDER, except on Nebius, where they stay on
Azure (or OpenAI) — the vectors already stored were made by text-embedding-3-large, and a different model would mean
re-indexing everything.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from kairos_kb.config import get_settings

logger = logging.getLogger(__name__)

PROVIDERS = ("azure", "openai", "nebius")


def provider() -> str:
    chosen = (get_settings().llm_provider or "").strip().lower()
    return chosen if chosen in PROVIDERS else "azure"


def _configured(name: str) -> bool:
    s = get_settings()
    if name == "openai":
        return bool(s.openai_api_key)
    if name == "nebius":
        return bool(s.nebius_api_key)
    return bool(s.azure_openai_api_key and s.azure_openai_endpoint)


def configured() -> bool:
    return _configured(provider())


def model_name() -> str:
    """The default chat model: an OpenAI model id, the Azure deployment, or the Nebius model id."""
    s = get_settings()
    return {"openai": s.openai_model, "nebius": s.nebius_model}.get(provider(), s.azure_openai_deployment)


def is_nemotron(model: Optional[str]) -> bool:
    return "nemotron" in (model or "").lower()


def nebius_client(timeout: float = 60):
    """A raw async client for Nebius Token Factory (OpenAI-compatible), or None without a key."""
    s = get_settings()
    if not s.nebius_api_key:
        return None
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=s.nebius_base_url, api_key=s.nebius_api_key, timeout=timeout)


def _nebius_chat(**kwargs: Any):
    """Nemotron through LangChain. Structured output goes through tool calling, which every Nemotron on Token
    Factory supports (strict JSON-schema response formats are not guaranteed there)."""
    from langchain_openai import ChatOpenAI

    class NemotronChat(ChatOpenAI):
        def with_structured_output(self, schema: Any = None, *, method: str = "function_calling",
                                   include_raw: bool = False, **kw: Any):
            inner = super().with_structured_output(schema, method=method, include_raw=True, **kw)
            return inner if include_raw else _recovering(inner, schema)

    return NemotronChat(**kwargs)


def _recovering(inner: Any, schema: Any):
    """Structured output that doesn't come back as None. Nemotron sometimes writes its function call as text
    (<tool_call>…</tool_call>) instead of making it; LangChain then returns None, and the caller failed later with
    "'NoneType' object has no attribute …". The call is read from the text; failing that, the model is asked once more;
    failing that, a clear error."""
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda

    name = getattr(schema, "__name__", None) or (schema.get("title") if isinstance(schema, dict) else None) or "answer"

    def again(messages: Any) -> Any:
        nudge = f"Answer only by calling the function {name}, with every required field filled in."
        if isinstance(messages, str):
            return [HumanMessage(messages), HumanMessage(nudge)]
        if hasattr(messages, "to_messages"):
            return messages.to_messages() + [HumanMessage(nudge)]
        return list(messages) + [("human", nudge)]

    async def run(messages: Any, config: Any = None) -> Any:
        problem = None
        for attempt in range(2):
            out = await inner.ainvoke(messages if attempt == 0 else again(messages), config)
            got = out.get("parsed")
            if got is None:
                got = from_text(out.get("raw"), schema)
            if got is not None:
                return got
            problem = out.get("parsing_error")
            logger.warning("Nemotron gave no usable %s (attempt %d)%s", name, attempt + 1,
                           f": {str(problem)[:300]}" if problem else "")
        raise ValueError(f"The model gave no usable {name}" + (f": {str(problem)[:200]}" if problem else "") + ".")

    def run_sync(messages: Any, config: Any = None) -> Any:
        import asyncio

        return asyncio.run(run(messages, config))

    return RunnableLambda(run_sync, afunc=run, name=f"{name}Recovering")


def from_text(raw: Any, schema: Any) -> Any:
    """A structured answer the model wrote as text: a <tool_call> block (XML or JSON) or a bare JSON object."""
    import json
    import re

    text = getattr(raw, "content", raw)
    if not isinstance(text, str) or not text.strip():
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    candidates: List[Any] = []
    from kairos_kb.companion.chat import fix_lists, text_tool_calls

    for call in text_tool_calls(text):
        try:
            candidates.append(json.loads(call["arguments"]))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                a = obj.get("arguments") or obj.get("parameters")
                candidates.append(json.loads(a) if isinstance(a, str) else a if isinstance(a, dict) else obj)
        except (json.JSONDecodeError, ValueError):
            pass
    for args in candidates:
        if not isinstance(args, dict):
            continue
        if not hasattr(schema, "model_validate"):
            return args
        for attempt in (args, fix_lists(args)):
            try:
                return schema.model_validate(attempt)
            except Exception:  # noqa: BLE001 — try the next reading
                continue
    return None


def chat_model(model: Optional[str] = None, **kwargs: Any):
    """A LangChain chat model for the configured service, or None when it is not configured."""
    if not configured():
        return None
    s = get_settings()
    if provider() == "openai":
        from langchain_openai import ChatOpenAI

        # The Responses API: OpenAI's newer models only allow function tools on Chat
        # Completions with reasoning switched off; here they keep it.
        kwargs.setdefault("use_responses_api", True)
        return ChatOpenAI(model=model or s.openai_model, api_key=s.openai_api_key, **kwargs)
    if provider() == "nebius":
        return _nebius_chat(model=model or s.nebius_model, api_key=s.nebius_api_key, base_url=s.nebius_base_url,
                            **kwargs)
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
        azure_deployment=model or s.azure_openai_deployment,
        **kwargs,
    )


def _raw_client(name: str):
    if not _configured(name):
        return None
    s = get_settings()
    if name == "openai":
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=s.openai_api_key)
    if name == "nebius":
        return nebius_client()
    from openai import AsyncAzureOpenAI

    return AsyncAzureOpenAI(azure_endpoint=s.azure_openai_endpoint, api_key=s.azure_openai_api_key,
                            api_version=s.azure_openai_api_version)


def async_client():
    """A raw async OpenAI SDK client for chat completions on the configured service, or None when not configured."""
    return _raw_client(provider())


# ── embeddings ───────────────────────────────────────────────────────


def embedding_provider() -> str:
    s = get_settings()
    chosen = (s.embedding_provider or "").strip().lower()
    if chosen in ("azure", "openai"):
        return chosen
    if provider() != "nebius":
        return provider()
    # On Nebius, embeddings stay where the stored vectors were made.
    return "azure" if _configured("azure") else "openai"


def embedding_model() -> str:
    s = get_settings()
    return s.openai_embedding_model if embedding_provider() == "openai" else s.azure_openai_embedding_deployment


def embedding_client():
    """A raw async client for embeddings, or None when that service is not configured."""
    return _raw_client(embedding_provider())
