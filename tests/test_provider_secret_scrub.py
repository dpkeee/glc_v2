from __future__ import annotations

import os

from glc import providers as P


def test_scrub_provider_key_env_removes_known_provider_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GITHUB_ACCESS_TOKEN", "gh-key")
    monkeypatch.setenv("GROQ_API_KEY", "gr-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-key")
    monkeypatch.setenv("CEREBRAS_API_KEY", "cb-key")
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "or-key")

    P.scrub_provider_key_env()

    for key in P.PROVIDER_SECRET_ENV_VARS:
        assert key not in os.environ
