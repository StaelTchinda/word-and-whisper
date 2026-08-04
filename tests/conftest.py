import sys
from pathlib import Path

import pytest


from prayer.api import registry
from prayer.api.config import get_settings
from prayer.api.corpus import load_corpus

# At import time, not in a fixture: tests/test_invariants.py parametrizes over
# the registered composers, and parametrization is resolved during collection.
registry.load_builtins()


@pytest.fixture(scope="session")
def settings():
    return get_settings(reload=True)


@pytest.fixture(scope="session")
def corpus(settings):
    registry.load_builtins()
    return load_corpus(settings.dataset_dir, settings.text_dir,
                       settings.policy_dir, settings.translation)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from prayer.api.app import app
    with TestClient(app) as c:
        yield c
