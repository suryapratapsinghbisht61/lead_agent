"""Shared test setup: every test gets its own empty database, cache and export folder."""

import pytest

from app.core import config
from app.db import session
from app.services import cache, llm


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    # Never read the developer's real .env (keys, users) in tests.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("MIN_FIT_SCORE", "6")
    monkeypatch.setenv("MAX_SEARCH_ROUNDS", "3")
    # Settings, engine and cache are created once and memoised; reset them for this test.
    for fn in (config.get_settings, session.get_engine, cache._cache, llm.get_llms):
        fn.cache_clear()
    session.init_db()
    yield tmp_path
    for fn in (config.get_settings, session.get_engine, cache._cache, llm.get_llms):
        fn.cache_clear()
