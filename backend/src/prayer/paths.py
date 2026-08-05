"""Canonical locations for everything on disk.

One place, so no module has to derive the repo root by counting `.parent`s off
whatever file it happens to hold — that arithmetic silently breaks the moment
anything moves.

The layout is organised by *lifecycle*, not by topic:

    data/input/     downloaded at setup; the cleaned markdown the extractors read
    data/scans/     the source PDFs; large, never needed after cleaning
    data/vendor/    downloaded artifacts: the embedding model, the WEB archives
    data/build/     everything a command can regenerate — disposable

Only `data/build/` is safe to delete: `make setup` rebuilds all of it in about a
second. `input`, `scans` and `vendor` are downloads, and none of the four are in
version control.

`PRAYER_ROOT` overrides the root, which is how the container points at
`/app` without any of this having to know it is in a container.
"""
import os
from pathlib import Path

# src/prayer/paths.py -> src/prayer -> src -> repo root
ROOT = Path(os.environ.get("PRAYER_ROOT", Path(__file__).resolve().parents[2]))

SRC = ROOT / "src"
CONFIGS = ROOT / "configs"
POLICY = ROOT / "policy"
PHRASES = POLICY / "phrases"
DOCS = ROOT / "docs"
TESTS = ROOT / "tests"
# Recorded milestone results. Not generated on demand — they are the
# historical floors later changes are measured against, so they are kept
# in version control and `make clean` must not touch them.
BASELINES = ROOT / "bench/baselines"

DATA = ROOT / "data"
INPUT = DATA / "input"           # cleaned markdown, one directory per source
SCANS = DATA / "scans"           # original PDFs
VENDOR = DATA / "vendor"         # downloaded, not generated
BUILD = DATA / "build"           # generated, disposable

MODELS = VENDOR / "models"
EMBEDDING_MODEL = MODELS / "bge-small-en-v1.5"
WEB_ARCHIVES = VENDOR / "web"    # eng-web_usfx.zip, eng-web_vpl.zip

DATASETS = BUILD / "datasets"    # the extracted sources and their links
TEXT = BUILD / "text"            # web.jsonl and its coverage report
INDEX = BUILD / "index"          # precomputed embeddings
BENCH = BUILD / "bench"          # queries and ad-hoc run output
FIXTURES = BUILD / "fixtures"    # golden compositions

CONFIG_FILE = CONFIGS / "base.yaml"

# The extractors read one file per source; the ids match the dataset ids.
SOURCE_FILES = {
    "parks2021": INPUT / "parks2021/all_the_prayers_in_the_bible_jimmy_parks.md",
    "lockyer1959": INPUT / "lockyer1959/all_the_prayers_of_the_bible__herbert_lockeyr_s.md",
    "watters1883": INPUT / "watters1883/the-prayers-of-the-bible-watters.md",
}
