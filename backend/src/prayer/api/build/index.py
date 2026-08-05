#!/usr/bin/env python3
"""Precompute the dense retrieval index — PRODUCT_BOOK M4.

    python -m prayer.api.build.index                 # build if missing or stale
    python -m prayer.api.build.index --force
    python -m prayer.api.build.index --download      # fetch the ONNX model first

Writes api/index/<model-name>.npz holding 224 L2-normalised vectors plus the
inputs' fingerprint. This is a build step, not a request-time one: after it
runs the API needs no network (C3).

Determinism: onnxruntime is pinned to one thread in api/retrievers/encoder.py,
and the documents are built from committed data, so the same inputs produce
the same bytes. `--force` is only needed when the model itself changes.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


from prayer.api.config import get_settings
from prayer.api.corpus import load_corpus
from prayer.api.retrievers.dense import dense_document
from prayer.api.retrievers.encoder import OnnxEncoder

from prayer import paths

DEFAULT_MODEL_DIR = paths.EMBEDDING_MODEL
HF_REPO = "BAAI/bge-small-en-v1.5"
HF_FILES = {"onnx/model.onnx": "model.onnx",
            "tokenizer.json": "tokenizer.json",
            "config.json": "config.json"}


def download_model(model_dir: Path) -> None:
    """Build-time only. Nothing here runs in the request path."""
    import shutil
    from huggingface_hub import hf_hub_download

    model_dir.mkdir(parents=True, exist_ok=True)
    for remote, local in HF_FILES.items():
        print(f"fetching {HF_REPO}/{remote}")
        shutil.copy(hf_hub_download(HF_REPO, remote), model_dir / local)


def fingerprint(documents: list[str], model_dir: Path) -> str:
    """Identifies the inputs, so a stale index is detected rather than used."""
    digest = hashlib.sha256()
    for document in documents:
        digest.update(document.encode("utf-8"))
        digest.update(b"\0")
    digest.update((model_dir / "model.onnx").stat().st_size.to_bytes(8, "big"))
    return digest.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.download:
        download_model(args.model_dir)
    if not (args.model_dir / "model.onnx").exists():
        print(f"no model at {args.model_dir}; run with --download", file=sys.stderr)
        return 1

    settings = get_settings(reload=True)
    corpus = load_corpus(settings.dataset_dir, settings.text_dir,
                         settings.policy_dir, settings.translation)

    # Every record is embedded, including policy-excluded ones: the filter
    # belongs at retrieval time, and rebuilding the index after a policy edit
    # would be a surprising coupling.
    records = corpus.records
    documents = [dense_document(corpus, r) for r in records]
    stamp = fingerprint(documents, args.model_dir)

    out_dir = args.out_dir or Path(settings.index_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.model_dir.name}.npz"

    if out_path.exists() and not args.force:
        existing = np.load(out_path, allow_pickle=False)
        if str(existing.get("fingerprint", np.array("")).item()) == stamp:
            if not args.quiet:
                print(f"index up to date ({out_path})")
            return 0

    if not args.quiet:
        print(f"embedding {len(documents)} records with {args.model_dir.name}...")
    encoder = OnnxEncoder(args.model_dir)
    vectors = encoder.encode(documents)

    np.savez(out_path,
             ids=np.array([r.id for r in records]),
             vectors=vectors.astype(np.float32),
             fingerprint=np.array(stamp),
             model=np.array(args.model_dir.name))

    meta = {
        "model": args.model_dir.name,
        "hf_repo": HF_REPO,
        "records": len(records),
        "dim": int(vectors.shape[1]),
        "pooling": "cls",
        "normalised": True,
        "fingerprint": stamp,
    }
    (out_dir / "index_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not args.quiet:
        print(f"wrote {vectors.shape[0]} x {vectors.shape[1]} vectors -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
