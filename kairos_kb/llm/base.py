"""Abstract LLM provider interface.

Business logic services depend ONLY on this interface — they never import
Azure OpenAI, LangChain, or any other SDK directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class LLMProvider(ABC):
    """Contract that every LLM backend must implement."""

    @abstractmethod
    async def generate_rca(
        self,
        incident_context: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        lineage: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate a Root Cause Analysis report from evidence."""

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]]) -> str:
        """General-purpose chat completion."""
