"""Test-only accommodation: the production code imports ``sentence_transformers``
at module import time (embeddings_service). If that heavy package is not
installed (e.g. a lightweight CI box), stub it so unrelated unit tests can run.
When the real package is present it is used untouched."""
import os
import sys
import types

os.environ.setdefault("ENVIRONMENT", "test")

try:  # pragma: no cover
    import sentence_transformers  # noqa: F401
except ImportError:  # pragma: no cover
    stub = types.ModuleType("sentence_transformers")

    class _SentenceTransformer:  # minimal stand-in, never used for real encoding
        def __init__(self, *a, **k):
            pass

    stub.SentenceTransformer = _SentenceTransformer
    stub.util = types.SimpleNamespace(cos_sim=lambda a, b: 0.0)
    sys.modules["sentence_transformers"] = stub


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _curated_resources_off_by_default(monkeypatch):
    """Existing search tests mock the web and must not pick up the real
    dataset/curated_resources.json. Tests of the curated feature opt back in."""
    from app.utils.config import settings
    monkeypatch.setattr(settings, "USE_CURATED_RESOURCES", False)
