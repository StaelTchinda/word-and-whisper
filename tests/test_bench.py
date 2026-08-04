"""M3: the harness reproduces, and the M2 baseline does not silently regress.

The baseline numbers below are the ones recorded in
bench/baselines/m2-baseline/report.md. They are floors, not targets: a change
that improves them is fine and should be re-recorded, a change that drops
below them needs an explanation.
"""
import json
from pathlib import Path

import pytest

from prayer.api import registry
from prayer.bench import metrics as M

from prayer import paths

TIER1 = paths.BENCH / "queries/tier1.jsonl"
BASELINE = paths.BASELINES / "m2-baseline/report.md"


def test_tier1_covers_the_whole_corpus():
    rows = [json.loads(l) for l in TIER1.read_text().splitlines() if l.strip()]
    assert len(rows) == 224
    assert len({r["gold"] for r in rows}) == 224
    for row in rows:
        assert row["relevance"][row["gold"]] == 2
        assert len(row["situation"]) > 20


def test_tier1_queries_are_paraphrases_not_copies(corpus):
    """If the query were the title verbatim, the metric would be meaningless."""
    rows = [json.loads(l) for l in TIER1.read_text().splitlines() if l.strip()]
    identical = sum(1 for row in rows
                    if corpus.record(row["gold"]).title.lower() in row["situation"])
    assert identical / len(rows) < 0.5


def test_harness_discovers_components_from_the_registry():
    """M3 DoD: no hardcoded component list in the harness."""
    source = (paths.SRC / "prayer/bench/run.py").read_text()
    assert 'registry.available("retriever"' in source
    assert 'registry.available("composer"' in source
    assert '"bm25"' not in source, "harness must not name a concrete retriever"


def test_baseline_report_exists():
    assert BASELINE.exists(), "M2's numbers must be recorded as the baseline"
    text = BASELINE.read_text()
    assert "Tier 1 measures wiring, not product quality" in text


@pytest.mark.parametrize("metric,floor", [
    ("R@1", 0.75), ("R@5", 0.90), ("MRR", 0.83), ("nDCG@10", 0.85),
])
def test_recorded_baseline_meets_its_floor(metric, floor):
    """Reads the recorded report rather than re-running: the full matrix is
    slow, and a stale baseline file is itself the thing worth catching."""
    header, row = None, None
    for line in BASELINE.read_text().splitlines():
        if line.startswith("| retriever | composer | R@1"):
            header = [c.strip() for c in line.strip("|").split("|")]
        elif header and line.startswith("| bm25 |"):
            row = [c.strip() for c in line.strip("|").split("|")]
            break
    assert header and row
    assert float(row[header.index(metric)]) >= floor


def test_anchor_verbatim_in_baseline_is_exactly_one():
    """C1 is a release blocker, not a metric to trend."""
    for line in BASELINE.read_text().splitlines():
        if line.startswith("| bm25 | deterministic |") and line.count("|") > 10:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 5 and cells[2].isdigit():  # the composition row
                assert cells[3] == "1.000", "anchor-verbatim must be 1.000"
                assert cells[4] == "1.000", "citation-valid must be 1.000"
                return
    pytest.fail("composition row not found in the baseline report")


# --- metric definitions -----------------------------------------------------

def test_recall_and_mrr():
    ranked = ["a", "b", "c"]
    assert M.recall_at_k(ranked, {"b": 2}, 1) == 0.0
    assert M.recall_at_k(ranked, {"b": 2}, 5) == 1.0
    assert M.reciprocal_rank(ranked, {"b": 2}) == pytest.approx(0.5)
    assert M.reciprocal_rank(ranked, {"z": 2}) == 0.0


def test_ndcg_is_one_for_a_perfect_ranking():
    assert M.ndcg_at_k(["a", "b"], {"a": 2, "b": 1}, 2) == pytest.approx(1.0)
    assert M.ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 2) < 1.0


def test_ndcg_handles_graded_relevance():
    """Tier 3 uses 2/1/0, so this must not assume binary."""
    assert 0 < M.ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 2) < 1


def test_psalm_share_reference_line(corpus):
    psalms = [r.id for r in corpus.records if corpus.is_psalm(r.id)]
    assert len(psalms) == 43
    assert M.psalm_share_at_k(psalms[:5], corpus.is_psalm, 5) == 1.0


def test_label_precision(corpus):
    contents = {"x": ["petition"], "y": ["praise"]}
    assert M.label_precision_at_k(["x", "y"], {"petition"}, contents, 2) == 0.5
