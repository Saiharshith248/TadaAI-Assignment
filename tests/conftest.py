"""Shared test fixtures. Everything runs offline from the committed synthetic snapshots."""
import copy
import json
from pathlib import Path

import pytest

from normalization.adapters import normalize_snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
PROVIDERS = ("prismhr", "isolved", "ukg-ready")


def load_snapshot(provider: str) -> dict:
    return json.loads((FIXTURES / provider / "snapshot.json").read_text(encoding="utf-8"))


_BUNDLES = {}


def bundle_for(provider: str):
    if provider not in _BUNDLES:
        _BUNDLES[provider] = normalize_snapshot(provider, load_snapshot(provider))
    return _BUNDLES[provider]


@pytest.fixture(scope="session")
def bundles():
    return {p: bundle_for(p) for p in PROVIDERS}


@pytest.fixture
def snapshot():
    """Fresh deep copy so a test can mutate it."""
    return lambda provider: copy.deepcopy(load_snapshot(provider))


def by_id(records, suffix):
    """Record whose canonical id ends with ``suffix``."""
    hits = [r for r in records if r.id.endswith(suffix)]
    assert len(hits) == 1, f"{len(hits)} records end with {suffix!r}"
    return hits[0]


def codes(record):
    return {(i.code.value, i.field) for i in record.issues}
