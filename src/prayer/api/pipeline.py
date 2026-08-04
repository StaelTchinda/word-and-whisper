#!/usr/bin/env python3
"""Stage orchestration and every fallback decision in one place.

    situation -> SafetyGate -> SituationAnalyzer -> Retriever -> TextResolver
              -> Composer -> response

The constraints that live here rather than in any stage:

  C4  Every response is a complete suggestion or an explicit abstention.
      Never a partial or empty success.
  C5  Composition never fails the request. A composer that raises, returns
      something the verifier rejects, or times out is replaced by the
      deterministic composer, and the response says so in `provenance`.
  C7  The safety gate runs before retrieval on every request, regardless of
      configuration.

Keeping the fallbacks here means a new composer inherits all of them by
existing, and cannot accidentally opt out.
"""
import logging
import time
from typing import Optional

from prayer.api import registry
from prayer.api.analyze import SituationAnalyzer
from prayer.api.composers import anchor as anchor_mod
from prayer.api.composers.base import CompositionError
from prayer.api.composers.verify import spoken_text, verify, word_count
from prayer.api.config import Settings
from prayer.api.corpus import Corpus
from prayer.api.models import (AnalyzedSituation, Candidate, Composition, Filters,
                        Instructions, LabelBlock, MatchBlock, Movement,
                        Passage, PrayerRecord, ProvenanceBlock, QueryEcho,
                        ReferenceBlock, SafetyBlock, SpokenPrayer, Suggestion,
                        SuggestRequest, SuggestResponse, Timings,
                        WORDS_PER_MINUTE)
from prayer.api.safety import SafetyGate, load_gate

log = logging.getLogger("prayer.pipeline")

ABSTAIN_MESSAGE = (
    "I don't have anything close enough to suggest for this. The corpus is 224 "
    "prayers from the Bible, and many real situations have no near analogue in "
    "it. Rather than hand you a generic psalm, I would rather say so."
)

FALLBACK_COMPOSER = "deterministic"


class Pipeline:
    def __init__(self, corpus: Corpus, settings: Settings):
        self.corpus = corpus
        self.settings = settings
        self.analyzer = SituationAnalyzer(settings.policy_dir)
        self.gate: SafetyGate = load_gate(settings.policy_dir)
        self._retrievers: dict[str, object] = {}
        self._composers: dict[str, object] = {}

    # --- component access --------------------------------------------------

    def retriever(self, name: str):
        if name not in self._retrievers:
            self._retrievers[name] = registry.get("retriever", name)(
                self.corpus, self.settings)
        return self._retrievers[name]

    def composer(self, name: str):
        if name not in self._composers:
            cls = registry.get("composer", name)
            self._composers[name] = cls(self.corpus, self.settings, self._llm())
        return self._composers[name]

    def _llm(self):
        """Local model, or None. Never raises -- absence is a fallback, not an error."""
        try:
            return registry.get("llm", self.settings.llm_backend)(self.settings)
        except Exception:
            return None

    # --- main path ---------------------------------------------------------

    def suggest(self, request: SuggestRequest) -> SuggestResponse:
        started = time.perf_counter()

        # C7: before retrieval, on every request, whatever the configuration.
        verdict = self.gate.check(request.situation)

        retriever_name = request.retriever or self.settings.retriever
        composer_name = self._resolve_composer(request.composer, verdict.is_crisis)

        q = self.analyzer.analyze(request.situation, verdict.status)
        filters = Filters(
            canon=request.canon,
            require_text=True,
            # In crisis the corpus is narrowed to its honest prayers, so the
            # answer cannot be a cheerful psalm of praise (section 7.1).
            allowed_contents=self.gate.allowed_contents if verdict.is_crisis else None,
        )

        t0 = time.perf_counter()
        candidates = self.retriever(retriever_name).retrieve(
            q, self.settings.candidate_pool, filters)
        retrieval_ms = int((time.perf_counter() - t0) * 1000)

        safety = SafetyBlock(status=verdict.status, notice=verdict.notice)
        echo = QueryEcho(situation=request.situation, k=request.k,
                         retriever=retriever_name, composer=composer_name)

        # C4: abstain loudly rather than return the nearest generic psalm.
        if not candidates or candidates[0].score < self.settings.abstain_threshold:
            log.info("abstained: best=%.4f threshold=%.4f",
                     candidates[0].score if candidates else 0.0,
                     self.settings.abstain_threshold)
            return SuggestResponse(
                query=echo, safety=safety, abstained=True,
                message=ABSTAIN_MESSAGE, suggestions=[],
                timings=Timings(total_ms=int((time.perf_counter() - started) * 1000),
                                retrieval_ms=retrieval_ms))

        t0 = time.perf_counter()
        suggestions = []
        for candidate in candidates:
            if len(suggestions) >= request.k:
                break
            built = self._build(candidate, q, composer_name,
                                request.include_passage_text)
            if built is not None:
                suggestions.append(built)
        composition_ms = int((time.perf_counter() - t0) * 1000)

        # C4 again: if every candidate failed to build, that is an abstention,
        # not a success with an empty list.
        if not suggestions:
            return SuggestResponse(
                query=echo, safety=safety, abstained=True,
                message=ABSTAIN_MESSAGE, suggestions=[],
                timings=Timings(total_ms=int((time.perf_counter() - started) * 1000),
                                retrieval_ms=retrieval_ms,
                                composition_ms=composition_ms))

        return SuggestResponse(
            query=echo, safety=safety, abstained=False, suggestions=suggestions,
            timings=Timings(total_ms=int((time.perf_counter() - started) * 1000),
                            retrieval_ms=retrieval_ms,
                            composition_ms=composition_ms))

    def _resolve_composer(self, requested: Optional[str], crisis: bool) -> str:
        """Pick the composer, honouring the crisis and config overrides.

        In crisis the deterministic composer is forced regardless of what was
        requested: a small local model must never improvise words to a person
        in crisis (section 7.1).
        """
        if crisis:
            return FALLBACK_COMPOSER
        name = requested or self.settings.composer
        if name == "free" and not self.settings.enable_free_composer:
            log.warning("free composer requested but disabled; using %s", FALLBACK_COMPOSER)
            return FALLBACK_COMPOSER
        return name

    # --- per-suggestion ----------------------------------------------------

    def _build(self, candidate: Candidate, q: AnalyzedSituation,
               composer_name: str, include_passage: bool) -> Optional[Suggestion]:
        record = self.corpus.record(candidate.prayer_id)
        passage = self.corpus.passage(candidate.prayer_id)
        if record is None or passage is None or not passage.text_available:
            return None
        if record.compose_policy == "exclude":
            return None  # belt and braces; the retriever filters these already

        started = time.perf_counter()
        if record.compose_policy == "explain_only":
            return self._explain_only(candidate, record, passage, q, include_passage,
                                      started)

        composition, fallback_used = self._compose_with_fallback(
            composer_name, q, record, passage)
        if composition is None:
            return None

        latency_ms = int((time.perf_counter() - started) * 1000)
        text = spoken_text(composition)
        n_words = word_count(composition)

        return Suggestion(
            prayer_id=record.id,
            title=record.title,
            reference=self._reference(record),
            **self._passage_fields(passage, composition, include_passage),
            labels=self._labels(record),
            match=MatchBlock(score=candidate.score, matched_on=candidate.matched_on),
            instructions=composition.instructions,
            spoken_prayer=SpokenPrayer(
                text=text,
                movements=self._ordered(composition.movements),
                word_count=n_words,
                read_time_seconds=max(1, round(n_words / WORDS_PER_MINUTE * 60)),
            ),
            provenance=ProvenanceBlock(
                composer=composition.composer, model=composition.model,
                fallback_used=fallback_used or composition.fallback_used,
                retry_count=composition.retry_count, latency_ms=latency_ms),
        )

    def _compose_with_fallback(self, composer_name: str, q: AnalyzedSituation,
                               record: PrayerRecord,
                               passage: Passage) -> tuple[Optional[Composition], bool]:
        """C5: the request never fails because a composer did.

        The verifier runs on the requested composer's output as well as the
        fallback's. A composition that fails verification is discarded exactly
        like one that raised -- a violation is not something to report and ship.
        """
        address = anchor_mod.find_address(passage)
        allow = address.text if address else None

        if composer_name != FALLBACK_COMPOSER:
            try:
                composition = self.composer(composer_name).compose(q, record, passage)
                result = verify(composition, passage, record, allow_address_span=allow)
                if result.ok:
                    return composition, False
                log.warning("%s failed verification for %s: %s", composer_name,
                            record.id, "; ".join(result.violations))
            except Exception as exc:
                # Deliberately broad: C5 says the request survives whatever a
                # composer does, including exceptions its author never
                # anticipated. CompositionError is the polite case.
                log.warning("%s raised for %s: %s", composer_name, record.id, exc)

        try:
            composition = self.composer(FALLBACK_COMPOSER).compose(q, record, passage)
        except Exception as exc:
            # The deterministic composer failing means the record is genuinely
            # uncomposable (no text, no anchor window). Drop the candidate and
            # let the next one through rather than emitting something partial.
            log.error("deterministic composer failed for %s: %s", record.id, exc)
            return None, True

        result = verify(composition, passage, record, allow_address_span=allow)
        if not result.ok:
            log.error("deterministic composer violated invariants for %s: %s",
                      record.id, "; ".join(result.violations))
            return None, True
        return composition, composer_name != FALLBACK_COMPOSER

    def _explain_only(self, candidate: Candidate, record: PrayerRecord,
                      passage: Passage, q: AnalyzedSituation,
                      include_passage: bool, started: float) -> Suggestion:
        """A retrieved record the policy will not put in the user's mouth.

        Returned with instructions and no spoken prayer, and with `note` saying
        why. That is a complete answer under C4, not a partial one.
        """
        composer = self.composer(FALLBACK_COMPOSER)
        instructions = composer.build_instructions(q, record, passage)
        note = composer.phrases["explain_only_note"].strip()
        if record.policy_reason:
            note = f"{note} {' '.join(record.policy_reason.split())}"
        return Suggestion(
            prayer_id=record.id,
            title=record.title,
            reference=self._reference(record),
            **self._passage_fields(passage, None, include_passage),
            labels=self._labels(record),
            match=MatchBlock(score=candidate.score, matched_on=candidate.matched_on),
            instructions=instructions,
            spoken_prayer=None,
            note=note,
            provenance=ProvenanceBlock(
                composer="explain_only", latency_ms=int((time.perf_counter() - started) * 1000)),
        )

    # --- assembly helpers --------------------------------------------------

    @staticmethod
    def _ordered(movements: list[Movement]) -> list[Movement]:
        from prayer.api.composers.base import MOVEMENT_ORDER
        return sorted(movements, key=lambda m: MOVEMENT_ORDER.index(m.kind))

    def _reference(self, record: PrayerRecord) -> ReferenceBlock:
        return ReferenceBlock(
            osis=record.primary_ref,
            display=record.refs[0].raw if record.refs else record.primary_ref,
            translation=self.corpus.translation,
            # Parallel accounts are listed, never concatenated (section 3).
            parallels=[r.raw for r in record.refs[1:]],
        )

    @staticmethod
    def _labels(record: PrayerRecord) -> LabelBlock:
        return LabelBlock(context=record.context, contents=record.contents,
                          speaker=record.speaker.raw,
                          canon_section=record.canon_section)

    def _passage_fields(self, passage: Passage, composition: Optional[Composition],
                        include_passage: bool) -> dict:
        """Full text plus, for long passages, an excerpt around the anchor.

        Psalm 89 is 52 verses. Returning it inline as the thing to pray would
        be useless, so the full text is still available but flagged, and an
        excerpt centred on the anchor carries the part that matters (section 5.4).
        """
        limit = self.settings.max_passage_verses_inline
        verses = passage.refs[0].verses if passage.refs else []
        truncated = len(verses) > limit

        excerpt = None
        if truncated and composition is not None:
            excerpt = self._excerpt(passage, composition, verses)

        return {
            "passage_text": passage.full_text if include_passage else None,
            "passage_truncated": truncated,
            "passage_excerpt": excerpt,
        }

    def _excerpt(self, passage: Passage, composition: Composition, verses) -> str:
        anchor = next((m for m in composition.movements if m.kind == "anchor"), None)
        centre = 0
        if anchor and anchor.verbatim_from:
            centre = next((i for i, v in enumerate(verses)
                           if v.osis == anchor.verbatim_from), 0)
        span = self.settings.excerpt_verses
        lo = max(0, centre - span // 2)
        hi = min(len(verses), lo + span)
        lo = max(0, hi - span)
        return " ".join(v.text for v in verses[lo:hi])
