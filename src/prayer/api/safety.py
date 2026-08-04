#!/usr/bin/env python3
"""Crisis gate — PRODUCT_BOOK section 7.1.

Runs before retrieval on every request, regardless of configuration (C7).

On detection the service still returns a prayer. A person in crisis who asks
for prayer should not be met with a blank refusal. What changes is: a
real-world signposting notice is prepended, retrieval is narrowed to the
corpus's honest prayers (lament, petition, complaint), and composition is
forced to the deterministic path -- a small local model must never improvise
words to someone in crisis.

Deterministic keyword and regex matching so the gate is auditable and
testable. Tuned to over-trigger.
"""
import functools
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SafetyVerdict:
    status: str          # "ok" | "crisis"
    categories: tuple[str, ...] = ()
    notice: str | None = None

    @property
    def is_crisis(self) -> bool:
        return self.status == "crisis"


class SafetyGate:
    def __init__(self, doc: dict):
        self.version = doc.get("version", 0)
        self.sign_off = doc.get("sign_off", "pending")
        self.notice = " ".join((doc.get("notice") or "").split())
        self.allowed_contents = list(doc.get("allowed_contents", []))
        self._categories: list[tuple[str, list[re.Pattern]]] = []
        for cat in doc.get("categories", []):
            regexes = [re.compile(rf"\b{re.escape(t.lower())}\b")
                       for t in cat.get("terms", [])]
            regexes += [re.compile(p, re.I) for p in cat.get("patterns", []) or []]
            self._categories.append((cat["name"], regexes))

    def check(self, situation: str) -> SafetyVerdict:
        lowered = situation.lower()
        hits = tuple(name for name, regexes in self._categories
                     if any(r.search(lowered) for r in regexes))
        if not hits:
            return SafetyVerdict("ok")
        return SafetyVerdict("crisis", hits, self.notice)

    @property
    def notice_is_approved(self) -> bool:
        """False while section 11 item 3 is outstanding.

        Surfaced rather than asserted: the service must still work in
        development, but nothing should be able to claim the wording was
        reviewed when it was not.
        """
        return self.sign_off != "pending"


@functools.cache
def load_gate(policy_dir: Path) -> SafetyGate:
    path = policy_dir / "safety_terms.yaml"
    return SafetyGate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
