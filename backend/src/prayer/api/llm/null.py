#!/usr/bin/env python3
"""A LocalLM that always fails, immediately.

The default backend, and the tool the fallback tests use. Any composer that
depends on a model must produce a valid response with `fallback_used: true`
when wired to this (C5), which is only checkable if "no model" is a first-class
configuration rather than an error path nobody exercises.
"""
from typing import Optional

from pydantic import BaseModel

from prayer.api import registry
from prayer.api.llm.base import LLMUnavailable


@registry.register("llm", "null", description="Always unavailable; exercises "
                                              "the fallback paths.")
class NullLM:
    name = "null"

    def __init__(self, settings=None):
        self.settings = settings

    def generate(self, prompt: str, *, max_tokens: int, timeout_s: float,
                 schema: Optional[type[BaseModel]] = None) -> str:
        raise LLMUnavailable("no local model configured (llm_backend='null')")
