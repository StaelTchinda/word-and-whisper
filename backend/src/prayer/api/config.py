#!/usr/bin/env python3
"""Settings: config.yaml is the reviewable source, env vars are the override.

Precedence is env > config.yaml > field default, so a deployment can flip
`PRAYER_COMPOSER=schema` without editing a tracked file, while the checked-in
YAML stays the thing a human reads to know how the service behaves.
"""
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import Field
from pydantic_settings import (BaseSettings, PydanticBaseSettingsSource,
                               SettingsConfigDict)

from prayer import paths

CONFIG_PATH = paths.CONFIG_FILE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRAYER_",
        extra="ignore",
        # A local .env is a convenience for development; it is gitignored, and
        # real deployments set the variables directly.
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                   env_settings, dotenv_settings,
                                   file_secret_settings):
        # Highest priority first.
        return (init_settings, env_settings, dotenv_settings,
                _YamlSource(settings_cls, _config_path), file_secret_settings)

    # paths
    # Points at one source directory. data/build/datasets/ now holds several
    # (sources/parks2021, sources/lockyer1959) plus links/.
    dataset_dir: Path = paths.DATASETS / "sources/parks2021"
    # All three source directories, for the read-only /sources browse+search
    # surface (prayer.api.sources) -- independent of dataset_dir above, which
    # stays parks2021-only and feeds only Corpus/{suggest,prayers/{id}}.
    sources_dir: Path = paths.DATASETS / "sources"
    text_dir: Path = paths.TEXT
    policy_dir: Path = paths.POLICY
    phrases_dir: Path = paths.PHRASES
    index_dir: Path = paths.INDEX
    embedding_model_dir: Path = paths.EMBEDDING_MODEL

    # defaults for a request that does not specify
    retriever: str = "bm25"
    composer: str = "deterministic"
    translation: str = "WEB"
    k: int = 3

    # retrieval
    abstain_threshold: float = 0.08
    psalm_penalty: float = 0.0  # diversification, tuned in M8 on dev only
    candidate_pool: int = 25
    # Query-side ONNX threads. The index build always uses 1 (reproducible).
    embedding_threads: int = 4

    # composition
    max_passage_verses_inline: int = 20
    excerpt_verses: int = 8
    compose_timeout_s: float = 8.0

    # F4 is off by default: a small local model will fabricate confidently and
    # verify.py cannot catch a plausible-sounding false theological claim.
    enable_free_composer: bool = False

    # local model (M5+); no hosted call ever happens at request time (C2)
    llm_backend: str = "null"
    llm_model_path: Optional[str] = None
    llm_max_tokens: int = 512
    llm_timeout_s: float = 6.0

    # ops
    log_situations: bool = False  # situations are sensitive; log hashes instead
    rate_limit_per_minute: int = 60

    # /sources browse+search (prayer.api.sources). Lockyer's exposition, poetry
    # and outline are protected expression still in copyright (c. 1959
    # Zondervan) -- see docs/datasets.md licensing section. Off by default so
    # the API never serves or republishes them. Personal, local use is fine;
    # settle the rights question before turning this on for a public
    # deployment.
    include_copyrighted_text: bool = False


def _yaml_values(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flat: dict[str, Any] = {}
    for section, value in loaded.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[section] = value
    return flat


class _YamlSource(PydanticBaseSettingsSource):
    """configs/base.yaml as a settings source, ranked below the environment.

    It has to be a source rather than init kwargs: pydantic-settings ranks init
    kwargs *above* env vars, so passing the YAML that way made every key it
    contains impossible to override — `PRAYER_RETRIEVER=hybrid` was silently
    ignored, contradicting this module's own docstring.
    """

    def __init__(self, settings_cls, path: Path):
        super().__init__(settings_cls)
        self.path = path

    def get_field_value(self, field, field_name):  # pragma: no cover - unused hook
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return _yaml_values(self.path)


_settings: Optional[Settings] = None
_config_path: Path = CONFIG_PATH


def get_settings(reload: bool = False, path: Path = CONFIG_PATH) -> Settings:
    """Resolve settings once, then cache.

    Precedence, highest first: environment > .env > configs/base.yaml > field
    default. So a deployment flips `PRAYER_COMPOSER=schema` without editing a
    tracked file, and the checked-in YAML stays the thing a human reads to know
    how the service behaves.
    """
    global _settings, _config_path
    if _settings is None or reload:
        _config_path = path
        _settings = Settings()
    return _settings
