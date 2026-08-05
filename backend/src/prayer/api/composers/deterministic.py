#!/usr/bin/env python3
"""The deterministic composer: no model, always works.

It is the fallback for every other composer (C5) and therefore the floor of
the whole product's quality. Everything it emits comes from the phrase bank,
the record's own labels, and a verbatim window of the passage. Nothing is
generated, so nothing can be fabricated.

`selectable=False` by default keeps it out of /config while PRODUCT_BOOK
section 11 item 4 is open -- whether users may pick it directly is the human's
call, and flipping it is a one-word change here.
"""
import functools
import hashlib
from pathlib import Path
from typing import Optional

import yaml

from prayer.api import registry
from prayer.api.composers import anchor as anchor_mod
from prayer.api.composers.base import CompositionError
from prayer.api.models import (AnalyzedSituation, Composition, Instructions, Movement,
                        MAX_PRAYER_WORDS, MIN_PRAYER_WORDS, Passage, PrayerRecord)

# Records carrying either label get the section 7.3 treatment.
IMPRECATORY_LABELS = frozenset({"imprecation", "curse"})


@functools.cache
def load_phrases(phrases_dir: Path) -> dict:
    path = phrases_dir / "movements.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def pick(options: list[str], seed: str, salt: str = "") -> str:
    """Stable choice from a list, keyed by prayer_id.

    Deterministic rather than random so the same record always reads the same
    way: the golden-file tests depend on it, and a user who asks twice should
    not get a subtly different prayer for no reason.
    """
    if not options:
        return ""
    digest = hashlib.sha256(f"{seed}|{salt}".encode()).digest()
    return options[digest[0] % len(options)]


@registry.register("composer", "deterministic",
                   description="Templates and phrase bank only; no model. "
                               "The fallback path for every other composer.",
                   selectable=False)
class DeterministicComposer:
    def __init__(self, corpus, settings=None, llm=None):
        self.corpus = corpus
        self.settings = settings
        self.phrases = load_phrases(
            settings.phrases_dir if settings else
            Path(__file__).resolve().parent / "phrases")

    # --- public ------------------------------------------------------------

    def compose(self, q: AnalyzedSituation, p: PrayerRecord,
                passage: Passage) -> Composition:
        if not passage.text_available or not passage.full_text.strip():
            raise CompositionError(f"{p.id} has no resolved text to anchor on")

        address_src = anchor_mod.find_address(passage)
        anchor = anchor_mod.select_anchor(
            passage, q, after=address_src.end if address_src else 0)
        if anchor is None and address_src is not None:
            # The vocative swallowed the verse; retry without skipping it.
            anchor = anchor_mod.select_anchor(passage, q, after=0)
        if anchor is None:
            raise CompositionError(f"{p.id} yielded no usable anchor window")

        movements = [
            Movement(kind="address", text=self._address(p, address_src)),
            Movement(kind="anchor", text=anchor.text, verbatim_from=anchor.osis),
            Movement(kind="naming", text=self._naming(q, p)),
            Movement(kind="ask", text=self._ask(q, p)),
        ]
        trust = self._trust(p)
        if trust:
            movements.append(Movement(kind="trust", text=trust))
        movements.append(Movement(kind="close", text=self._close(p)))

        movements = self._fit_word_budget(
            movements, q, p, passage, after=address_src.end if address_src else 0)

        return Composition(
            movements=movements,
            instructions=self.build_instructions(q, p, passage),
            composer="deterministic",
        )

    # --- movements ---------------------------------------------------------

    def _address(self, p: PrayerRecord,
                 src: Optional[anchor_mod.PassageAddress]) -> str:
        """Prefer the passage's own vocative (section 5.4).

        The vocative is quoted from scripture, but it is reproduced as the
        prayer's address rather than as a claim about the text, and the anchor
        starts after it so it is never said twice. The verifier's
        no-scripture-outside-anchor rule allows this one span explicitly.
        """
        if src and src.text:
            text = src.text.strip().rstrip(",")
            return f"{text},"
        return pick(self.phrases["address"]["fallback"], p.id, "address")

    def _naming(self, q: AnalyzedSituation, p: PrayerRecord) -> str:
        bank = self.phrases["naming"]
        options = bank["intercessory"] if q.intercessory else bank["first_person"]
        lead = pick(options, p.id, "naming")
        body = q.subject_phrase or q.situation.strip()
        if q.intercessory:
            from prayer.api.analyze import to_third_person
            body = to_third_person(body)
        return f"{lead} {body}"

    def _ask(self, q: AnalyzedSituation, p: PrayerRecord) -> str:
        bank = self.phrases["ask"]
        if IMPRECATORY_LABELS & set(p.contents):
            return pick(bank["imprecatory"], p.id, "ask")

        # Prefer an ask matching a label the record and the situation share;
        # that is what keeps the petition aligned with what the source prayer
        # actually did rather than with what the user happened to type.
        shared = [c for c in p.contents if c in q.content_labels]
        for label in shared + list(p.contents):
            options = bank["by_content"].get(label)
            if options:
                return pick(options, p.id, f"ask:{label}")
        return pick(bank["default"], p.id, "ask")

    def _trust(self, p: PrayerRecord) -> Optional[str]:
        """Only where the source prayer has some note of confidence.

        A lament with no resolution gets no trust movement. Adding one would
        tell the user the passage says something it does not.
        """
        bank = self.phrases["trust"]
        for label in p.contents:
            options = bank["by_content"].get(label)
            if options:
                return pick(options, p.id, f"trust:{label}")
        return None

    def _close(self, p: PrayerRecord) -> str:
        return pick(self.phrases["close"]["default"], p.id, "close")

    # --- word budget -------------------------------------------------------

    def _fit_word_budget(self, movements: list[Movement], q: AnalyzedSituation,
                         p: PrayerRecord, passage: Passage,
                         after: int = 0) -> list[Movement]:
        """Bring the prayer inside 60-180 words (section 5.4).

        Growing adds a trust movement, then widens the anchor, then appends
        phrase-bank extension lines -- never invented detail, and never
        scripture outside the anchor. Shrinking trims the naming movement (the
        user's own words, which they already know) before touching the anchor,
        so the quoted passage stays a real slice for as long as possible.

        `after` is the offset past the passage's own vocative. Re-selecting the
        anchor without it would let the widened window swallow the address and
        make the prayer say it twice -- which the verifier would then reject.
        """
        def total(ms: list[Movement]) -> int:
            return sum(len(m.text.split()) for m in ms)

        # too short: add optional material, in order of least intrusiveness
        if total(movements) < MIN_PRAYER_WORDS:
            if not any(m.kind == "trust" for m in movements):
                fallback = pick(self.phrases["trust"]["default"], p.id, "trust:pad")
                movements.insert(-1, Movement(kind="trust", text=fallback))

        if total(movements) < MIN_PRAYER_WORDS:
            # Widen the anchor before adding words of our own: more scripture
            # is a better way to reach the floor than more of the composer.
            for i, m in enumerate(movements):
                if m.kind != "anchor":
                    continue
                wider = anchor_mod.select_anchor(
                    passage, q, after=after,
                    min_words=len(m.text.split()) + 1,
                    max_words=anchor_mod.MAX_ANCHOR_WORDS + 30)
                if wider and len(wider.text.split()) > len(m.text.split()):
                    movements[i] = Movement(kind="anchor", text=wider.text,
                                            verbatim_from=wider.osis)
                break

        # Short passages simply cannot reach 60 words on their own: 94 records
        # are a single verse and the shortest is under a dozen words. Append
        # distinct extension lines until the floor is met.
        extensions = list(self.phrases["ask"]["extensions"])
        start = int(hashlib.sha256(p.id.encode()).digest()[1]) % max(1, len(extensions))
        rotated = extensions[start:] + extensions[:start]
        for extra in rotated:
            if total(movements) >= MIN_PRAYER_WORDS:
                break
            for i, m in enumerate(movements):
                if m.kind == "ask":
                    movements[i] = Movement(kind="ask", text=f"{m.text} {extra}")
                    break

        # too long: trim the user's own words first, then the anchor
        if total(movements) > MAX_PRAYER_WORDS:
            over = total(movements) - MAX_PRAYER_WORDS
            for i, m in enumerate(movements):
                if m.kind != "naming":
                    continue
                words = m.text.split()
                keep = max(8, len(words) - over)
                if keep < len(words):
                    movements[i] = Movement(
                        kind="naming",
                        text=" ".join(words[:keep]).rstrip(",;:") + "...")
                break
        if total(movements) > MAX_PRAYER_WORDS:
            over = total(movements) - MAX_PRAYER_WORDS
            for i, m in enumerate(movements):
                if m.kind != "anchor":
                    continue
                target = max(anchor_mod.MIN_ANCHOR_WORDS,
                             len(m.text.split()) - over)
                shorter = anchor_mod.select_anchor(passage, q, after=after,
                                                   max_words=target)
                if shorter:
                    movements[i] = Movement(kind="anchor", text=shorter.text,
                                            verbatim_from=shorter.osis)
                break
        return movements

    # --- instructions ------------------------------------------------------

    def build_instructions(self, q: AnalyzedSituation, p: PrayerRecord,
                           passage: Passage) -> Instructions:
        """Also used for `explain_only` records, which get no spoken prayer."""
        bank = self.phrases["instructions"]
        gloss = bank["context_gloss"].get(p.context, bank["context_gloss"]["other"])

        speaker_tpl = bank["why_it_fits"]["speaker_by_collective"][p.speaker.collective]
        speaker_clause = speaker_tpl.format(speaker=p.speaker.raw, context_gloss=gloss)
        contents_clause = bank["why_it_fits"]["contents_clause"].format(
            contents=_join(p.contents))
        themes_clause = (bank["why_it_fits"]["themes_clause"].format(
            themes=_join(q.themes)) if q.themes else
            bank["why_it_fits"]["themes_clause_empty"])
        why = bank["why_it_fits"]["template"].format(
            speaker_clause=speaker_clause, contents_clause=contents_clause,
            themes_clause=themes_clause)

        how = bank["how_to_pray"]["by_context"].get(
            p.context, bank["how_to_pray"]["by_context"]["other"])
        how += bank["how_to_pray"]["specifics_note"]
        if passage.verse_count == 1:
            how += bank["how_to_pray"]["single_verse_note"]
        elif passage.verse_count > (self.settings.max_passage_verses_inline
                                    if self.settings else 20):
            how += bank["how_to_pray"]["long_passage_note"]
        if IMPRECATORY_LABELS & set(p.contents):
            how += bank["how_to_pray"]["imprecatory_note"]

        posture = bank["posture"].get(p.context, bank["posture"]["other"])
        return Instructions(why_it_fits=why, how_to_pray=how, posture=posture)


def _join(items: list[str]) -> str:
    items = [i.replace("_", " ") for i in items]
    if not items:
        return "prayer"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]
