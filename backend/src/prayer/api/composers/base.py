#!/usr/bin/env python3
"""The Composer seam (PRODUCT_BOOK sections 5.3 and 5.4).

Every composer emits the same ordered movement structure; they differ only in
how each movement's text is produced. That uniformity is what lets
tests/test_invariants.py run one parametrized suite against all of them, and
what lets the pipeline fail any composer over to `deterministic` without
special-casing.
"""
from typing import Protocol, runtime_checkable

from prayer.api.models import (AnalyzedSituation, Composition, MovementKind, Passage,
                        PrayerRecord)

# Canonical order. A Composition is rendered in this order regardless of the
# order a composer happened to emit movements in.
MOVEMENT_ORDER: tuple[MovementKind, ...] = (
    "address", "anchor", "naming", "ask", "trust", "close",
)


@runtime_checkable
class Composer(Protocol):
    name: str

    def compose(self, q: AnalyzedSituation, p: PrayerRecord,
                passage: Passage) -> Composition: ...


class CompositionError(Exception):
    """Raised by a composer that cannot produce a valid Composition.

    The pipeline catches this and falls back to `deterministic` (C5). A
    composer should raise rather than return something invalid: the verifier
    is a safety net, not the primary contract.
    """
