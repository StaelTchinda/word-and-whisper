#!/usr/bin/env python3
"""Choosing the verbatim scripture window every composer anchors on.

Shared by all composers rather than reimplemented per composer: the anchor is
the one movement that carries a C1 guarantee, so there should be exactly one
piece of code that produces it and exactly one place to audit.

Everything here returns slices of `passage.full_text` by character offset and
never rebuilds a string from tokens. That is the whole trick -- if the returned
text is always a slice, "byte-exact substring" is true by construction rather
than by a test that hopefully catches a regression.

Two problems this has to solve that are easy to miss:

1. Narrative framing. 1 Sam 1:11 begins "She vowed a vow, and said, ..." --
   quoting that in a first-person prayer makes the user narrate Hannah rather
   than pray. So the quoted speech inside the verse is preferred.
2. Duplicate address. If the passage opens with its own vocative
   ("Yahweh of Armies,") and we use it for the `address` movement, the anchor
   must start after it or the prayer says it twice.
"""
import re
from dataclasses import dataclass
from typing import Optional

from prayer.api.models import AnalyzedSituation, Passage

OPEN_QUOTES = "“"   # "
CLOSE_QUOTES = "”"  # "

# Clause boundaries: sentence enders plus the semicolon, which in WEB's poetry
# usually separates two complete parallel lines.
CLAUSE_END_RE = re.compile(r"[.!?;:]['’”]?\s+|\n")

# Finer boundaries, used only when no sentence-level window fits the word
# bounds. Hannah's vow (1 Sam 1:11) is one 52-word sentence: without this the
# anchor gets cut on a bare word boundary and ends "and no razor shall come".
FINE_CLAUSE_END_RE = re.compile(r"[.!?;:,—]['’”]?\s+|\n")

# A vocative opening: "Yahweh of Armies,", "O Lord,", "God of our fathers,".
ADDRESS_RE = re.compile(
    r"^[“‘\"']?\s*("
    r"(?:O\s+)?(?:most\s+high\s+)?"
    r"(?:Yahweh|LORD|Lord|God|Almighty|Sovereign|Father|Master|King)"
    r"[^,.;!?”]{0,60}?"
    r")\s*[,.!]"
)

# An appositive continuing the vocative: "Yahweh, *the God of Israel*, why...".
# Without this the address is cut short and the anchor begins mid-title.
APPOSITIVE_RE = re.compile(
    r"^\s*((?:the\s+|our\s+|my\s+)?"
    r"(?:God|Lord|Almighty|King|Father|Maker|Creator|Redeemer|Holy\s+One)"
    r"[^,.;!?”]{0,50}?)\s*,")

# Narrative framing that should not be inside an anchor.
NARRATION_RE = re.compile(
    r"\b(said|says|saying|prayed|vowed|answered|cried out|spoke|replied|"
    r"stood|knelt|lifted up (?:his|her|their)|these words)\b", re.I)

SECOND_PERSON_RE = re.compile(r"\b(you|your|yours|thee|thy)\b", re.I)
FIRST_PERSON_RE = re.compile(r"\b(i|me|my|mine|we|us|our)\b", re.I)

MIN_ANCHOR_WORDS = 8
MAX_ANCHOR_WORDS = 45


@dataclass(frozen=True)
class Anchor:
    text: str
    osis: str
    start: int
    end: int


@dataclass(frozen=True)
class PassageAddress:
    """The passage's own way of addressing God, if it has one."""
    text: str
    end: int  # offset in full_text just past the vocative and its comma


def verse_at(passage: Passage, offset: int) -> str:
    """OSIS id of the verse containing `offset` in full_text.

    full_text is the primary ref's verses joined with a single space, which is
    what corpus/build_text guarantee; this walks the same join.
    """
    if not passage.refs:
        return ""
    cursor = 0
    last = passage.refs[0].verses[0].osis if passage.refs[0].verses else ""
    for verse in passage.refs[0].verses:
        end = cursor + len(verse.text)
        if offset < end:
            return verse.osis
        cursor = end + 1  # the joining space
        last = verse.osis
    return last


def find_address(passage: Passage) -> Optional[PassageAddress]:
    """Extract the passage's own vocative, preferring inside quoted speech."""
    text = passage.full_text
    region_start = 0
    quote = text.find(OPEN_QUOTES)
    if quote != -1:
        region_start = quote + 1
    match = ADDRESS_RE.match(text[region_start:region_start + 120])
    if not match:
        return None
    vocative = match.group(1).strip()
    if not vocative:
        return None
    end = region_start + match.end()

    # Absorb a trailing appositive so the address is the whole title.
    appositive = APPOSITIVE_RE.match(text[end:end + 80])
    if appositive:
        vocative = f"{vocative}, {appositive.group(1).strip()}"
        end += appositive.end()

    return PassageAddress(text=vocative, end=end)


def _speech_region(passage: Passage) -> tuple[int, int]:
    """Character span of the prayer's actual words within full_text.

    Prefers the outermost run of quoted speech; falls back to the whole
    passage when the verse has no quotation marks (common in the Psalms, which
    are prayer end to end and need no framing).
    """
    text = passage.full_text
    start = text.find(OPEN_QUOTES)
    if start == -1:
        return 0, len(text)
    end = text.rfind(CLOSE_QUOTES)
    if end <= start:
        end = len(text)
    return start + 1, end


def _clauses(text: str, lo: int, hi: int, fine: bool = False) -> list[tuple[int, int]]:
    """Clause spans within [lo, hi), as offsets into `text`."""
    pattern = FINE_CLAUSE_END_RE if fine else CLAUSE_END_RE
    spans: list[tuple[int, int]] = []
    cursor = lo
    for match in pattern.finditer(text, lo, hi):
        end = match.start() + 1  # keep the terminating punctuation
        if end > cursor:
            spans.append((cursor, min(end, hi)))
        cursor = match.end()
    if cursor < hi:
        spans.append((cursor, hi))
    return [(a, b) for a, b in spans if b > a]


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span past quote marks and whitespace. Never grows it.

    Only ever moves the boundaries inward, so the result stays a substring.
    """
    while start < end and text[start] in " \t\n“‘\"'":
        start += 1
    while end > start and text[end - 1] in " \t\n”’\"'":
        end -= 1
    return start, end


def _score_window(text: str, q: AnalyzedSituation) -> float:
    """Prefer windows that sound like prayer and touch the user's situation."""
    lowered = text.lower()
    words = lowered.split()
    if not words:
        return -1e9

    score = 0.0
    # Addressing God directly is the single strongest signal that this span is
    # prayer rather than narration around it.
    score += 2.0 * min(3, len(SECOND_PERSON_RE.findall(lowered)))
    score += 1.0 * min(3, len(FIRST_PERSON_RE.findall(lowered)))
    score -= 4.0 * len(NARRATION_RE.findall(lowered))

    overlap = sum(1 for token in set(q.tokens) if token in lowered)
    score += 2.5 * min(4, overlap)

    # Mild preference for a middling length: very short anchors feel like a
    # proof-text, very long ones swallow the whole prayer.
    n = len(words)
    score -= 0.06 * abs(n - 24)
    return score


def select_anchor(passage: Passage, q: AnalyzedSituation,
                  after: int = 0,
                  min_words: int = MIN_ANCHOR_WORDS,
                  max_words: int = MAX_ANCHOR_WORDS) -> Optional[Anchor]:
    """Best verbatim window in `passage`, starting at or after offset `after`.

    Returns None only when the passage has no usable span at all; callers must
    treat that as a reason to fall back rather than to invent text.
    """
    text = passage.full_text
    if not text.strip():
        return None

    lo, hi = _speech_region(passage)
    lo = max(lo, after)
    if hi - lo < 12:  # the vocative was nearly the whole verse
        lo, hi = max(0, after), len(text)
    if hi <= lo:
        lo, hi = 0, len(text)

    # Sentence-level clauses first; fall back to comma-level splitting only if
    # nothing fits, so an anchor prefers to end at a full stop.
    best: Optional[tuple[float, int, int]] = None
    for fine in (False, True):
        clauses = _clauses(text, lo, hi, fine=fine) or [(lo, hi)]
        for i in range(len(clauses)):
            for j in range(i, len(clauses)):
                start, end = _trim(text, clauses[i][0], clauses[j][1])
                if end <= start:
                    continue
                n_words = len(text[start:end].split())
                if n_words < min_words:
                    continue
                if n_words > max_words:
                    break  # windows only grow with j
                score = _score_window(text[start:end], q)
                if best is None or score > best[0]:
                    best = (score, start, end)
        if best is not None:
            break

    if best is None:
        # Nothing hit the word bounds -- take the longest clause run that fits
        # under the ceiling, and if even one clause is too long, cut on a word
        # boundary so the result is still an exact slice.
        start, end = _trim(text, lo, hi)
        words = text[start:end].split()
        if len(words) > max_words:
            cut = start
            for _ in range(max_words):
                nxt = text.find(" ", cut + 1)
                if nxt == -1 or nxt >= end:
                    break
                cut = nxt
            end = cut
        start, end = _trim(text, start, end)
        if end <= start:
            return None
        best = (0.0, start, end)

    _, start, end = best
    return Anchor(text=text[start:end], osis=verse_at(passage, start),
                  start=start, end=end)
