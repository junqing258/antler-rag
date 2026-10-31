"""Tests must never inherit deployment model credentials or endpoints."""

import os

import pytest

from core.config import Settings


@pytest.fixture(autouse=True)
def isolated_runtime_configuration(monkeypatch):
    for name in os.environ:
        if name.startswith("RAG_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
