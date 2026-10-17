"""Which LLM service Kairos talks to: the OpenAI API platform or Azure OpenAI.

LLM_PROVIDER picks it: "azure" (the default, Azure AI Foundry deployments) or
"openai" (the OpenAI API platform, kept ready as a fallback). An OpenAI key in
the environment never switches the service on its own. Every chat model, raw
client and embedding call in Kairos comes from here, so moving between them is
one setting.

Model names: on OpenAI they are model ids (OPENAI_MODEL, e.g. gpt-6-luna); on
Azure they are deployment names (AZURE_OPENAI_DEPLOYMENT).
"""

from __future__ import annotations

from typing import Any, Optional

from kairos_kb.config import get_settings


def provider() -> str:
    chosen = (get_settings().llm_provider or "").strip().lower()
    return "openai" if chosen == "openai" else "azure"


def configured() -> bool:
    s = get_settings()
    if provider() == "openai":
        return bool(s.openai_api_key)
    return bool(s.azure_openai_api_key and s.azure_openai_endpoint)


def model_name() -> str:
    """The default chat model: an OpenAI model id, or the Azure deployment."""
    s = get_settings()
    return s.openai_model if provider() == "openai" else s.azure_openai_deployment


def embedding_model() -> str:
    s = get_settings()
    return s.openai_embedding_model if provider() == "openai" else s.azure_openai_embedding_deployment


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
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
        azure_deployment=model or s.azure_openai_deployment,
        **kwargs,
    )


def async_client():
    """A raw async OpenAI SDK client (chat completions, embeddings), or None when not configured."""
    if not configured():
        return None
    s = get_settings()
    if provider() == "openai":
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=s.openai_api_key)
    from openai import AsyncAzureOpenAI

    return AsyncAzureOpenAI(azure_endpoint=s.azure_openai_endpoint, api_key=s.azure_openai_api_key,
                            api_version=s.azure_openai_api_version)
