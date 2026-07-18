from __future__ import annotations

import sys

import glc.cli as cli


def test_token_command_blocked_in_production_without_override(monkeypatch, capsys):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.delenv("GLC_ALLOW_TOKEN_EXPORT", raising=False)
    monkeypatch.setattr(sys, "argv", ["glc", "token"])

    rc = cli.main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "token export is disabled in production" in captured.err


def test_token_command_allowed_with_override(monkeypatch, capsys):
    monkeypatch.setenv("GLC_ENV", "production")
    monkeypatch.setenv("GLC_ALLOW_TOKEN_EXPORT", "1")
    monkeypatch.setattr(sys, "argv", ["glc", "token"])

    rc = cli.main()
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip()
