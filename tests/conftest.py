from pathlib import Path

import pytest

from rag_service.api import build_pipeline, create_app
from rag_service.config import Settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_provider="offline",
        corpus_dir=ROOT / "data" / "handbook",
        cache_backend="memory",
        rate_limit_per_minute=1000,
    )


@pytest.fixture
def pipeline(settings):
    return build_pipeline(settings)


@pytest.fixture
def app(settings, pipeline):
    return create_app(settings, pipeline)
