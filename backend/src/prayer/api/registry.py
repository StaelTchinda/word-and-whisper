#!/usr/bin/env python3
"""Component registry: the seam that keeps retrievers and composers pluggable.

A new retriever or composer becomes available by importing its module and
decorating its class. Nothing in api/app.py, api/models.py or bench/ needs to
know it exists. tests/test_contract.py registers a stub from a test module and
drives it end to end -- that test is the executable definition of the
modularity requirement in PRODUCT_BOOK section 5.1.
"""
from typing import Any, Callable, TypeVar

_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {}

T = TypeVar("T")


def register(kind: str, name: str, *, description: str = "",
             selectable: bool = True,
             conformant: bool = True) -> Callable[[type[T]], type[T]]:
    """Class decorator. `kind` is "retriever" | "composer" | "llm".

    `selectable=False` keeps a component out of the public /config listing and
    out of request validation while still making it reachable internally --
    that is how the deterministic composer stays a fallback rather than a
    user-facing choice (open decision 4).

    `conformant=False` marks a component that is *deliberately* broken, which
    only the fallback tests need: they register composers that fabricate
    scripture or raise on purpose, and the shared invariant suite must not
    treat those as regressions. Everything else, including test stubs meant to
    work, stays conformant and is held to the full suite.
    """
    def decorate(cls: type[T]) -> type[T]:
        slot = _REGISTRY.setdefault(kind, {})
        if name in slot and slot[name]["cls"] is not cls:
            raise ValueError(f"{kind} {name!r} already registered by {slot[name]['cls']!r}")
        cls.name = name  # type: ignore[attr-defined]
        slot[name] = {
            "cls": cls,
            "description": description or (cls.__doc__ or "").strip().split("\n")[0],
            "selectable": selectable,
            "conformant": conformant,
        }
        return cls
    return decorate


def get(kind: str, name: str) -> type:
    try:
        return _REGISTRY[kind][name]["cls"]
    except KeyError:
        raise KeyError(
            f"no {kind} named {name!r}; available: {sorted(_REGISTRY.get(kind, {}))}"
        ) from None


def available(kind: str, *, selectable_only: bool = False,
              conformant_only: bool = False) -> list[str]:
    slot = _REGISTRY.get(kind, {})
    return sorted(
        n for n, e in slot.items()
        if (e["selectable"] or not selectable_only)
        and (e["conformant"] or not conformant_only)
    )


def describe(kind: str, *, selectable_only: bool = False) -> list[dict[str, Any]]:
    slot = _REGISTRY.get(kind, {})
    return [
        {"name": n, "kind": kind, "description": e["description"],
         "selectable": e["selectable"]}
        for n, e in sorted(slot.items())
        if e["selectable"] or not selectable_only
    ]


def load_builtins() -> None:
    """Import the shipped components so their decorators run.

    Import errors are swallowed per-module on purpose: a missing optional
    dependency (onnxruntime, torch) must degrade to "that component is not
    available", never to a dead API.
    """
    modules = [
        "prayer.api.retrievers.bm25",
        "prayer.api.retrievers.dense",
        "prayer.api.retrievers.hybrid",
        "prayer.api.composers.deterministic",
        "prayer.api.composers.phrasebank",
        "prayer.api.composers.schema",
        "prayer.api.composers.free",
        "prayer.api.llm.null",
        "prayer.api.llm.transformers_lm",
    ]
    import importlib
    for mod in modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            continue


def _reset_for_tests() -> None:
    _REGISTRY.clear()
