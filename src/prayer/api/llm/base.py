#!/usr/bin/env python3
"""The local-model seam (PRODUCT_BOOK section 5.3).

Only local inference lives behind this Protocol. No implementation may make a
network call in the request path (C2, C3); llm/null.py exists so the fallback
paths can be tested without a model present at all.
"""
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel


class LLMUnavailable(Exception):
    """No usable local model. Callers must treat this as a fallback trigger."""


class LLMTimeout(Exception):
    """Generation exceeded its hard timeout. Also a fallback trigger."""


@runtime_checkable
class LocalLM(Protocol):
    name: str

    def generate(self, prompt: str, *, max_tokens: int, timeout_s: float,
                 schema: Optional[type[BaseModel]] = None) -> str: ...
