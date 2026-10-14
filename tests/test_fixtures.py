"""Synthetic fixture generation: determinism, contract conformance, manifest accuracy."""
import hashlib
import json

import pytest

from normalization.fixture_generator import BUILDERS, DEFAULT_SEED, SCENARIOS, dumps, generate, write
from normalization.fixture_generator.validate import check, validate_snapshot
from conftest import FIXTURES, PROVIDERS


def test_committed_fixtures_match_generator():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["seed"] == DEFAULT_SEED
    fresh = generate(manifest["seed"])
    for provider, meta in manifest["providers"].items():
        committed = (FIXTURES / meta["file"]).read_bytes()
        assert hashlib.sha256(committed).hexdigest() == meta["sha256"]
        assert dumps(fresh[provider]).encode() == committed, f"{provider} fixture drifted from its generator"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_same_seed_same_bytes_different_seed_different_data(provider):
    assert dumps(BUILDERS[provider](1)) == dumps(BUILDERS[provider](1))
    assert dumps(BUILDERS[provider](1)) != dumps(BUILDERS[provider](2))


@pytest.mark.parametrize("seed", [1, 7, 2024])
@pytest.mark.parametrize("provider", PROVIDERS)
def test_any_seed_produces_contract_valid_snapshots(provider, seed):
    report = validate_snapshot(BUILDERS[provider](seed))
    assert report["errors"] == [] and report["checked"] > 20


@pytest.mark.parametrize("seed", [3, 11])
def test_any_seed_normalises_without_errors(seed):
    from normalization.adapters import normalize_snapshot
    for provider, build in BUILDERS.items():
        b = normalize_snapshot(provider, build(seed))
        assert b.employees and b.paychecks


def test_validator_catches_unknown_fields_and_types():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "array", "items": {"type": "string"}}}}
    assert check({"a": 1, "b": ["x"]}, schema, {}) == []
    problems = dict(check({"a": "1", "b": [2], "zz": 0}, schema, {}))
    assert problems == {"a": "expected integer, got str", "b[]": "expected string, got int", "zz": "field not in contract"}


def test_manifest_lists_scenarios(tmp_path):
    m = write(tmp_path)
    for provider in PROVIDERS:
        assert m["providers"][provider]["scenarios"] == SCENARIOS[provider]
        assert m["providers"][provider]["contract_validation"]["errors"] == 0


def test_fixture_pii_is_synthetic():
    import re
    for provider in PROVIDERS:
        text = (FIXTURES / provider / "snapshot.json").read_text()
        assert all(s.startswith("9") for s in re.findall(r"\b\d{3}-\d{2}-\d{4}\b", text))   # never-issued SSN area
        assert all(e.endswith((".example", "example.com")) for e in re.findall(r"[\w.]+@[\w.-]+", text))
