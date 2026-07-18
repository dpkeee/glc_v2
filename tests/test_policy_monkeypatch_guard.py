from __future__ import annotations

import pytest

from glc.policy.schemas import PolicyVerdict


def test_policy_evaluate_monkeypatch_blocked_in_production(monkeypatch):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.delenv("GLC_ALLOW_POLICY_MONKEYPATCH", raising=False)

    import glc.policy.engine as e

    with pytest.raises(PermissionError):
        e.evaluate = lambda *a, **k: PolicyVerdict(action="allow", reason="pwned")


def test_policy_evaluate_monkeypatch_allowed_with_override(monkeypatch):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.setenv("GLC_ALLOW_POLICY_MONKEYPATCH", "1")

    import glc.policy.engine as e

    original = e.evaluate
    e.evaluate = lambda *a, **k: PolicyVerdict(action="allow", reason="override")
    try:
        v = e.evaluate({}, {})
        assert v.action == "allow"
    finally:
        e.evaluate = original
