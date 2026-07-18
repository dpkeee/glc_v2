from __future__ import annotations

import pytest

from glc.security.pairing import get_pairing_store


def test_force_pair_owner_blocked_in_production_without_override(monkeypatch):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.delenv("GLC_ALLOW_FORCE_PAIR_OWNER", raising=False)

    with pytest.raises(PermissionError):
        get_pairing_store().force_pair_owner("telegram", "attacker-id", user_handle="me")


def test_force_pair_owner_allowed_with_override(monkeypatch):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.setenv("GLC_ALLOW_FORCE_PAIR_OWNER", "1")

    rec = get_pairing_store().force_pair_owner("telegram", "owner-id", user_handle="owner")
    assert rec.trust_level == "owner_paired"
