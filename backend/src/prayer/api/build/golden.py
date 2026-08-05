#!/usr/bin/env python3
"""Regenerate tests/fixtures/golden_compositions.json.

Run only when a change to the composer or phrase bank is intended. Review the
resulting diff as prose, not as a checksum -- the file is what a user would
actually be asked to pray.

    python -m prayer.api.build.golden
"""
import json
import sys
from pathlib import Path


from prayer.api import registry
from prayer.api.analyze import SituationAnalyzer
from prayer.api.composers.deterministic import DeterministicComposer
from prayer.api.composers.verify import spoken_text
from prayer.api.config import get_settings
from prayer.api.corpus import load_corpus

from prayer import paths

OUT = paths.FIXTURES / "golden_compositions.json"

# Chosen to cover the corpus's awkward shapes, not its easy ones: a long vow,
# an imprecatory psalm, a lament with no resolution, the Lord's Prayer, an
# eleven-word single verse, and a deuterocanonical record.
CASES = [
    ("parks2021.0037", "I've been trying for a child for four years and I'm losing hope."),
    ("parks2021.0095", "A colleague took credit for my work and told management I was the problem."),
    ("parks2021.0137", "I keep praying and there is nothing back."),
    ("parks2021.0193", "I do not know how to pray at all."),
    ("parks2021.0162", "The scan came back clear this morning."),
    ("parks2021.0179", "I drank again last night after eight months sober."),
]


def main() -> int:
    registry.load_builtins()
    settings = get_settings(reload=True)
    corpus = load_corpus(settings.dataset_dir, settings.text_dir,
                         settings.policy_dir, settings.translation)
    analyzer = SituationAnalyzer(settings.policy_dir)
    composer = DeterministicComposer(corpus, settings)

    rows = []
    for prayer_id, situation in CASES:
        q = analyzer.analyze(situation)
        record = corpus.record(prayer_id)
        composition = composer.compose(q, record, corpus.passage(prayer_id))
        rows.append({
            "prayer_id": prayer_id,
            "situation": situation,
            "title": record.title,
            "reference": record.refs[0].raw,
            "movements": [m.model_dump() for m in composition.movements],
            "spoken_text": spoken_text(composition),
            "instructions": composition.instructions.model_dump(),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print(f"wrote {len(rows)} golden compositions -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
