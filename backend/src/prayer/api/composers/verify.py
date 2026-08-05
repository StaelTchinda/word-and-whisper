#!/usr/bin/env python3
"""The composition verifier — PRODUCT_BOOK sections 5.4, 5.5, 7.3.

Every composer's output passes through here before it reaches a user. F2 and
F4 depend on it most, but it runs for all of them: a rule that only applies to
the risky composers is a rule that silently stops applying when someone adds a
new one.

What it can catch: fabricated or altered scripture, scripture smuggled into a
non-anchor movement, a missing required movement, word-count violations, and
an imprecatory ask aimed at a person.

What it cannot catch: a plausible-sounding false theological claim in the
composer's own words. There is no check for that here and there is not going
to be one, which is the substance of the residual risk F4 ships with.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from prayer.api.composers.base import MOVEMENT_ORDER
from prayer.api.models import (Composition, MAX_PRAYER_WORDS, MIN_PRAYER_WORDS,
                        Movement, Passage, PrayerRecord, REQUIRED_MOVEMENTS)

# Runs of words long enough that sharing them with the passage means quoting
# rather than coinciding. Six is comfortably past phrases like "you are the
# one who gives" appearing by chance in both.
QUOTE_NGRAM = 6

IMPRECATORY_LABELS = frozenset({"imprecation", "curse"})

# Asking God to act *against a person*. Section 7.3 allows asking for justice,
# vindication and rescue; it forbids putting a request for harm in the user's
# mouth.
HARM_RE = re.compile(
    r"\b(destroy|kill|slay|strike (?:down|them|him|her)|break (?:their|his|her)|"
    r"repay them|pay them back|curse (?:them|him|her)|"
    r"let them (?:die|perish|suffer|fall)|bring (?:them|him|her) down|"
    r"put them to shame|blot (?:them|him|her) out|avenge me on)\b", re.I)

WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass
class VerificationResult:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def _ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def spoken_text(composition: Composition) -> str:
    ordered = sorted(composition.movements,
                     key=lambda m: MOVEMENT_ORDER.index(m.kind))
    return "\n".join(m.text.strip() for m in ordered if m.text.strip())


def word_count(composition: Composition) -> int:
    return len(spoken_text(composition).split())


def verify(composition: Composition, passage: Passage, record: PrayerRecord,
           *, allow_address_span: Optional[str] = None) -> VerificationResult:
    """Check one Composition against every hard rule in section 5.4.

    `allow_address_span` is the passage's own vocative when a composer used it
    as the `address` movement. It is scripture appearing outside the anchor,
    permitted deliberately and only for that exact span -- passing it in is how
    a composer declares it did that, rather than the verifier guessing.
    """
    violations: list[str] = []
    kinds = [m.kind for m in composition.movements]

    for required in REQUIRED_MOVEMENTS:
        if required not in kinds:
            violations.append(f"missing required movement: {required}")

    for kind in set(kinds):
        if kinds.count(kind) > 1:
            violations.append(f"duplicate movement: {kind}")

    anchors = [m for m in composition.movements if m.kind == "anchor"]
    passage_text = passage.full_text

    for anchor in anchors:
        # C1, the rule this whole product stands on.
        if anchor.text not in passage_text:
            violations.append(
                f"anchor is not a verbatim substring of the passage: {anchor.text[:80]!r}")
        if not anchor.verbatim_from:
            violations.append("anchor is missing verbatim_from")
        elif not _citation_valid(anchor.verbatim_from, passage):
            violations.append(f"anchor cites {anchor.verbatim_from!r}, "
                              "which is not a verse of this passage")

    violations += _check_no_scripture_outside_anchor(
        composition, passage_text, allow_address_span)

    n = word_count(composition)
    if n < MIN_PRAYER_WORDS or n > MAX_PRAYER_WORDS:
        violations.append(f"spoken prayer is {n} words, outside "
                          f"{MIN_PRAYER_WORDS}-{MAX_PRAYER_WORDS}")

    if IMPRECATORY_LABELS & set(record.contents):
        for movement in composition.movements:
            if movement.kind == "ask" and HARM_RE.search(movement.text):
                violations.append(
                    "imprecatory record: `ask` requests harm against a person "
                    "(section 7.3 allows justice, vindication and rescue only)")

    return VerificationResult(ok=not violations, violations=violations)


def _citation_valid(osis: str, passage: Passage) -> bool:
    valid = {v.osis for ref in passage.refs for v in ref.verses}
    return osis in valid


def _check_no_scripture_outside_anchor(
        composition: Composition, passage_text: str,
        allow_address_span: Optional[str]) -> list[str]:
    """No movement but `anchor` may quote the passage (section 5.4).

    Keeping scripture confined to one movement is what lets the response show
    a user which words are the Bible's and which are the composer's -- and it
    is the only reason the anchor-verbatim check is meaningful, since a
    composer could otherwise satisfy C1 with a trivial anchor and paraphrase
    scripture everywhere else.
    """
    violations: list[str] = []
    passage_ngrams = _ngrams(_words(passage_text), QUOTE_NGRAM)
    if not passage_ngrams:
        return violations

    allowed = set(_words(allow_address_span)) if allow_address_span else set()

    for movement in composition.movements:
        if movement.kind == "anchor":
            continue
        tokens = _words(movement.text)
        if allowed and set(tokens) <= allowed:
            continue  # the declared address span, nothing more
        overlap = _ngrams(tokens, QUOTE_NGRAM) & passage_ngrams
        if overlap:
            sample = " ".join(sorted(overlap)[0])
            violations.append(
                f"movement {movement.kind!r} quotes the passage outside the "
                f"anchor: ...{sample}...")
    return violations
