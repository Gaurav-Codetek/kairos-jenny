"""Meaning vectors for context documents and search questions.

Embeddings are an enhancement, never a dependency: if the deployment is not
configured or the call fails, callers get None and search falls back to
keyword and name matching.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from kairos_kb.config import get_settings

logger = logging.getLogger(__name__)

BATCH = 32
# text-embedding-3 accepts 8191 tokens; characters are a safe proxy.
MAX_CHARS = 24000

_client = None


def _get_client():
    global _client
    from kairos_kb.llm.provider import embedding_client, embedding_model

    if not embedding_model():
        return None
    if _client is None:
        _client = embedding_client()  # its own service (stays Azure when chat runs on Nebius)
    return _client


def embeddings_enabled() -> bool:
    return _get_client() is not None


async def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """One vector per text, in order. None if embeddings are unavailable."""
    from kairos_kb.llm.provider import embedding_model

    client = _get_client()
    if client is None or not texts:
        return None
    settings = get_settings()
    vectors: List[List[float]] = []
    for start in range(0, len(texts), BATCH):
        batch = [t[:MAX_CHARS] or " " for t in texts[start:start + BATCH]]
        for attempt in range(3):
            try:
                response = await client.embeddings.create(
                    model=embedding_model(),
                    input=batch,
                    dimensions=settings.embedding_dimensions,
                )
                vectors.extend(item.embedding for item in response.data)
                break
            except Exception as exc:  # noqa: BLE001 — degrade to keyword search
                if attempt == 2:
                    logger.warning("Embedding failed; continuing without vectors: %s", exc)
                    return None
                await asyncio.sleep(1.5 * (attempt + 1))
    return vectors


async def embed_query(text: str) -> Optional[List[float]]:
    vectors = await embed_texts([text])
    return vectors[0] if vectors else None
