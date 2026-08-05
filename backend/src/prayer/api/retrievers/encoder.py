#!/usr/bin/env python3
"""Local ONNX sentence encoder, shared by the index builder and R2.

onnxruntime + the Rust `tokenizers` library only -- no torch and no
transformers at request time. That keeps the runtime import light and the
request path provably local (C2, C3).

The builder and the retriever must produce identical vectors for identical
text, so both go through this one class rather than each rolling their own
pooling and normalisation.
"""
import functools
import threading
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

# bge asks for an instruction prefix on the *query* side only. Embedding the
# documents with it too would cancel the effect it exists for.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

MAX_TOKENS = 512


class OnnxEncoder:
    def __init__(self, model_dir: Path, max_tokens: int = MAX_TOKENS,
                 threads: int = 1):
        """`threads=1` is the reproducible setting and the default.

        Thread count changes float accumulation order, so the index build --
        which section 12 requires to be byte-reproducible -- always uses one
        thread. The query side takes the default from config
        (`embedding_threads`) because it is not persisted and single-threaded
        encoding puts R2's p95 over the M4 budget. Ranking is unaffected in
        practice: the differences are last-few-ULP.
        """
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model_dir = Path(model_dir)
        self.name = self.model_dir.name
        self.threads = threads

        self.tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_tokens)
        self.tokenizer.enable_padding(length=None)

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(self.model_dir / "model.onnx"), options,
            providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}
        # onnxruntime sessions are not documented as thread-safe for
        # concurrent run() with all providers; the API is served by multiple
        # workers, so serialise.
        self._lock = threading.Lock()

    def encode(self, texts: Iterable[str], batch_size: int = 16) -> np.ndarray:
        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        vectors = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start:start + batch_size]
            encodings = self.tokenizer.encode_batch(chunk)
            ids = np.array([e.ids for e in encodings], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feed["token_type_ids"] = np.zeros_like(ids)
            with self._lock:
                hidden = self.session.run(None, feed)[0]
            # CLS pooling, which is what bge was trained with. Mean pooling
            # here would quietly degrade retrieval rather than fail.
            vectors.append(hidden[:, 0].astype(np.float32))

        stacked = np.vstack(vectors)
        norms = np.linalg.norm(stacked, axis=1, keepdims=True)
        return stacked / np.maximum(norms, 1e-12)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode([QUERY_PREFIX + text])[0]

    @property
    def dim(self) -> int:
        return self.session.get_outputs()[0].shape[-1]


@functools.cache
def load_encoder(model_dir: Path, threads: int = 1) -> Optional[OnnxEncoder]:
    """None rather than an exception when the model is absent.

    A missing embedding model must degrade to "the dense retriever is not
    available", never to a dead service -- BM25 still works.
    """
    model_dir = Path(model_dir)
    if not (model_dir / "model.onnx").exists():
        return None
    try:
        return OnnxEncoder(model_dir, threads=threads)
    except Exception:
        return None
