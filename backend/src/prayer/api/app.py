#!/usr/bin/env python3
"""FastAPI application: routes, startup wiring, error handling.

This module knows about the registry and the corpus. It deliberately does not
know the name of any concrete retriever or composer -- adding one must never
require an edit here (PRODUCT_BOOK section 5.1).
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from prayer.api import registry
from prayer.api.config import get_settings
from prayer.api.corpus import Corpus, load_corpus
from prayer.api.models import (ComponentInfo, ConfigResponse, HealthResponse,
                        LabelBlock, PrayerDetail, ReferenceBlock,
                        SuggestRequest, SuggestResponse)
from prayer.api.pipeline import Pipeline
from prayer.api.sources import load_sources
from prayer.api.sources import router as sources_router
from prayer.api.sources import set_stores

log = logging.getLogger("prayer.api")

_corpus: Optional[Corpus] = None
_pipeline: Optional[Pipeline] = None
_load_error: Optional[str] = None


def corpus() -> Corpus:
    if _corpus is None:
        raise HTTPException(503, detail=f"corpus not loaded: {_load_error}")
    return _corpus


def pipeline() -> Pipeline:
    if _pipeline is None:
        raise HTTPException(503, detail=f"pipeline not ready: {_load_error}")
    return _pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _corpus, _pipeline, _load_error
    settings = get_settings()
    registry.load_builtins()
    try:
        _corpus = load_corpus(settings.dataset_dir, settings.text_dir,
                              settings.policy_dir, settings.translation)
        _pipeline = Pipeline(_corpus, settings)
        # Build the default retriever's index at startup, not on first request:
        # a cold p95 that includes indexing is not the number M2's DoD means.
        _pipeline.retriever(settings.retriever)
        log.info("corpus loaded: %s", _corpus.stats())
        if not _pipeline.gate.notice_is_approved:
            log.warning("crisis notice wording is UNAPPROVED (safety_terms.yaml "
                        "sign_off: pending) — see PRODUCT_BOOK section 11 item 3")
    except Exception as exc:  # startup must report, not crash silently
        _load_error = f"{type(exc).__name__}: {exc}"
        log.error("startup failed: %s", _load_error)
    set_stores(load_sources(settings.sources_dir, settings.include_copyrighted_text))
    yield


app = FastAPI(
    title="Prayer Suggestion API",
    version="0.4.0",
    description="Suggests biblical prayers for a described life situation, "
                "with instructions and a ready-to-speak prayer. Runs fully "
                "offline; scripture is never paraphrased.",
    lifespan=lifespan,
)
app.include_router(sources_router)


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    if _corpus is None:
        return HealthResponse(status="degraded", corpus_loaded=False, prayers=0,
                              passages=0, detail=_load_error)
    stats = _corpus.stats()
    # Text is the prerequisite for every other stage, so no resolved passages
    # is degraded even though the process is up.
    degraded = stats["passages"] == 0
    return HealthResponse(
        status="degraded" if degraded else "ok",
        corpus_loaded=True,
        prayers=stats["prayers"],
        passages=stats["passages"],
        detail="no resolved passages; run prayer.extract.text" if degraded else None,
    )


@app.get("/config", response_model=ConfigResponse)
def config() -> ConfigResponse:
    settings = get_settings()
    composers = [ComponentInfo(**c)
                 for c in registry.describe("composer", selectable_only=True)
                 if settings.enable_free_composer or c["name"] != "free"]
    return ConfigResponse(
        retrievers=[ComponentInfo(**c)
                    for c in registry.describe("retriever", selectable_only=True)],
        composers=composers,
        translations=[settings.translation],
        defaults={"retriever": settings.retriever, "composer": settings.composer,
                  "translation": settings.translation, "k": str(settings.k)},
        corpus=_corpus.stats() if _corpus else {},
    )


@app.post("/suggest", response_model=SuggestResponse)
def suggest(request: SuggestRequest) -> SuggestResponse:
    settings = get_settings()
    pipe = pipeline()

    # Validate component names here so a caller gets 400 with the available
    # options rather than a 500 from deep in the pipeline.
    if request.retriever and request.retriever not in registry.available(
            "retriever", selectable_only=True):
        raise HTTPException(400, detail=f"unknown retriever {request.retriever!r}; "
                            f"available: {registry.available('retriever', selectable_only=True)}")
    if request.composer:
        allowed = registry.available("composer", selectable_only=True)
        if not settings.enable_free_composer:
            allowed = [c for c in allowed if c != "free"]
        if request.composer not in allowed:
            raise HTTPException(400, detail=f"unknown or disabled composer "
                                f"{request.composer!r}; available: {allowed}")
    if request.translation != settings.translation:
        raise HTTPException(400, detail=f"only {settings.translation} is bundled")

    response = pipe.suggest(request)
    # Situations are sensitive (section 9, M9). Log a hash by default so a
    # latency regression is still debuggable without retaining what people
    # wrote about their lives.
    log.info("suggest sha=%s k=%d retriever=%s composer=%s abstained=%s ms=%d%s",
             __import__("hashlib").sha256(request.situation.encode()).hexdigest()[:12],
             request.k, response.query.retriever, response.query.composer,
             response.abstained, response.timings.total_ms,
             f" situation={request.situation!r}" if settings.log_situations else "")
    return response


@app.get("/prayers/{prayer_id}", response_model=PrayerDetail)
def prayer(prayer_id: str) -> PrayerDetail:
    c = corpus()
    rec = c.record(prayer_id)
    if rec is None:
        raise HTTPException(404, detail=f"no prayer {prayer_id!r}")
    passage = c.passage(prayer_id)
    return PrayerDetail(
        prayer_id=rec.id,
        title=rec.title,
        reference=ReferenceBlock(
            osis=rec.primary_ref,
            display=rec.refs[0].raw if rec.refs else rec.primary_ref,
            translation=c.translation,
            parallels=[r.raw for r in rec.refs[1:]],
        ),
        labels=LabelBlock(context=rec.context, contents=rec.contents,
                          speaker=rec.speaker.raw, canon_section=rec.canon_section),
        compose_policy=rec.compose_policy,
        policy_reason=rec.policy_reason,
        text_available=bool(passage and passage.text_available),
        passage_text=passage.full_text if passage and passage.text_available else None,
        verse_count=passage.verse_count if passage else 0,
    )
