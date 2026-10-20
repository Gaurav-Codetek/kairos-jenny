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

from typing import Any, Optional

from kairos_kb.config import get_settings

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
        def with_structured_output(self, schema: Any = None, *, method: str = "function_calling", **kw: Any):
            return super().with_structured_output(schema, method=method, **kw)

    return NemotronChat(**kwargs)


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
