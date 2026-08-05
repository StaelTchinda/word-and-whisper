#!/usr/bin/env python3
"""SituationAnalyzer v1: user's words -> the corpus's vocabulary.

Deterministic and lexicon-driven (api/policy/situation_lexicon.yaml). No model
runs here, in M2 or later -- the analyzer's job is to be predictable and
auditable, and a small local model would make both worse for no measured gain.

The hard part of this product lives here: a user writes "I got laid off and I
can't sleep", and the corpus is indexed by "petition" and "complaint". Tier 1
of the benchmark is blind to how well that mapping works, which is exactly why
Tier 3 exists.
"""
import functools
import re
from pathlib import Path
from typing import Optional

import yaml

from prayer.api.models import AnalyzedSituation

WORD_RE = re.compile(r"[a-z']+")

# Contractions expanded before the situation is echoed back in a prayer.
# Spoken aloud, "I've been trying" is fine; but the naming movement reads
# better -- and more like liturgy than like chat -- fully expanded.
CONTRACTIONS = {
    "i'm": "I am", "i've": "I have", "i'd": "I would", "i'll": "I will",
    "can't": "cannot", "won't": "will not", "don't": "do not",
    "doesn't": "does not", "didn't": "did not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "couldn't": "could not", "wouldn't": "would not", "shouldn't": "should not",
    "it's": "it is", "that's": "that is", "there's": "there is",
    "we've": "we have", "we're": "we are", "they're": "they are",
    "he's": "he is", "she's": "she is", "let's": "let us",
}


def _strings(values, where: str) -> list[str]:
    """Reject YAML 1.1's boolean-like tokens instead of silently mangling them.

    `no`, `on`, `off`, `yes`, `false` unquoted in a YAML list become booleans,
    which then flow into a Pydantic list[str] and blow up somewhere far from
    the file that caused it. This is a data file a human edits, so it fails
    here with the offending value named.
    """
    bad = [v for v in (values or []) if not isinstance(v, str)]
    if bad:
        raise ValueError(
            f"{where}: {bad!r} parsed as non-strings. YAML reads no/on/off/"
            f"yes/true/false as booleans -- quote them.")
    return list(values or [])


class Lexicon:
    def __init__(self, doc: dict):
        self.themes = doc.get("themes", [])
        for theme in self.themes:
            for key in ("terms", "expansions", "contents", "contexts"):
                if key in theme:
                    theme[key] = _strings(theme[key], f"theme {theme.get('name')}.{key}")
        self.stopwords = frozenset(_strings(doc.get("stopwords"), "stopwords"))
        self.intercessory = [m.lower() for m in
                             _strings(doc.get("intercessory_markers"),
                                      "intercessory_markers")]
        # Precompiled once: the gate runs on every request and these patterns
        # are the bulk of its work.
        self._theme_res = [
            (t, [re.compile(rf"\b{re.escape(term.lower())}\b") for term in t.get("terms", [])])
            for t in self.themes
        ]
        self._inter_res = [re.compile(rf"\b{re.escape(m)}\b") for m in self.intercessory]

    def match_themes(self, text: str) -> list[dict]:
        return [t for t, regexes in self._theme_res if any(r.search(text) for r in regexes)]

    def is_intercessory(self, text: str) -> bool:
        return any(r.search(text) for r in self._inter_res)


@functools.cache
def load_lexicon(policy_dir: Path) -> Lexicon:
    path = policy_dir / "situation_lexicon.yaml"
    return Lexicon(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def expand_contractions(text: str) -> str:
    def sub(m: re.Match) -> str:
        word = m.group(0)
        repl = CONTRACTIONS.get(word.lower())
        if repl is None:
            return word
        # "I've" -> "I have"; "can't" at the start of a sentence -> "Cannot"
        return repl if word[0].islower() or repl.startswith("I") else repl.capitalize()
    return re.sub(r"\b[A-Za-z]+'[a-z]+\b", sub, text)


def to_third_person(text: str) -> str:
    """Rewrite a first-person situation as an intercession.

    Crude on purpose. The alternative -- a model rewriting the user's own words
    -- is exactly where a small local model would start inventing detail about
    a real person's circumstances.
    """
    swaps = [
        (r"\bI am\b", "they are"), (r"\bI have\b", "they have"),
        (r"\bI was\b", "they were"), (r"\bI\b", "they"),
        (r"\bmy\b", "their"), (r"\bMy\b", "Their"),
        (r"\bme\b", "them"), (r"\bmyself\b", "themselves"),
        (r"\bmine\b", "theirs"),
    ]
    for pattern, repl in swaps:
        text = re.sub(pattern, repl, text)
    return text


class SituationAnalyzer:
    def __init__(self, policy_dir: Path):
        self.lexicon = load_lexicon(policy_dir)

    def analyze(self, situation: str, safety_status: str = "ok") -> AnalyzedSituation:
        lowered = situation.lower()
        matched = self.lexicon.match_themes(lowered)

        contents: list[str] = []
        contexts: list[str] = []
        expansions: list[str] = []
        for theme in matched:
            for label in theme.get("contents", []):
                if label not in contents:
                    contents.append(label)
            for label in theme.get("contexts", []) or []:
                if label not in contexts:
                    contexts.append(label)
            for term in theme.get("expansions", []) or []:
                if term not in expansions:
                    expansions.append(term)

        tokens = [w for w in WORD_RE.findall(lowered)
                  if w not in self.lexicon.stopwords and len(w) > 2]

        return AnalyzedSituation(
            situation=situation.strip(),
            tokens=tokens,
            content_labels=contents,
            context_labels=contexts,
            themes=[t["name"] for t in matched],
            expansions=expansions,
            intercessory=self.lexicon.is_intercessory(lowered),
            subject_phrase=self._subject_phrase(situation),
            safety_status=safety_status,  # type: ignore[arg-type]
        )

    @staticmethod
    def _subject_phrase(situation: str, max_words: int = 40) -> Optional[str]:
        """The user's own words, lightly cleaned, for the naming movement.

        Deliberately not a summary: the naming movement is the one place the
        user hears their own situation said back, and paraphrasing it is how a
        pastoral answer starts sounding generic.
        """
        text = expand_contractions(" ".join(situation.split()))
        if not text:
            return None
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words]).rstrip(",;:") + "..."
        if text[-1] not in ".!?…":
            text += "."
        return text[0].upper() + text[1:]
