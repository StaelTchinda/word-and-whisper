"""Keep .env.example honest.

A template that documents variables which silently do nothing is worse than no
template — that was the state before the settings sources were reordered, when
19 of 24 PRAYER_* variables were ignored because the YAML was passed as init
kwargs and outranked the environment.
"""
import re

from prayer import paths
from prayer.api.config import Settings, get_settings

EXAMPLE = paths.ROOT / ".env.example"
NAMES = set(re.findall(r"^#?([A-Z][A-Z0-9_]*)=", EXAMPLE.read_text(), re.M))


def test_every_setting_is_documented():
    missing = {f"PRAYER_{n.upper()}" for n in Settings.model_fields} - NAMES
    assert not missing, f".env.example does not mention: {sorted(missing)}"


def test_no_variable_is_documented_that_nothing_reads():
    known = {f"PRAYER_{n.upper()}" for n in Settings.model_fields}
    # Read directly rather than through Settings.
    known |= {"PRAYER_ROOT", "PRAYER_HOST", "PRAYER_PORT", "PRAYER_RELOAD",
              "PORT", "PRAYER_DATA_URL", "PRAYER_DATA_TOKEN",
              "HF_HUB_DISABLE_TELEMETRY"}
    assert not NAMES - known, f".env.example invents: {sorted(NAMES - known)}"


def test_the_one_required_variable_is_not_commented_out():
    body = EXAMPLE.read_text()
    assert re.search(r"^PRAYER_DATA_URL=", body, re.M), \
        "PRAYER_DATA_URL is required, so it must be an active line to fill in"


def test_environment_overrides_the_yaml(monkeypatch):
    """The precedence the file claims. `retriever` is set in configs/base.yaml,
    so this is exactly the case that used to fail."""
    assert "retriever" in _yaml_keys()
    monkeypatch.setenv("PRAYER_RETRIEVER", "hybrid")
    assert get_settings(reload=True).retriever == "hybrid"


def test_yaml_still_beats_the_field_default(monkeypatch):
    monkeypatch.delenv("PRAYER_ABSTAIN_THRESHOLD", raising=False)
    from prayer.api.config import CONFIG_PATH, _yaml_values
    assert get_settings(reload=True).abstain_threshold == \
        _yaml_values(CONFIG_PATH)["abstain_threshold"]


def _yaml_keys():
    from prayer.api.config import CONFIG_PATH, _yaml_values
    return _yaml_values(CONFIG_PATH)
