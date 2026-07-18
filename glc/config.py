"""Loads channels.yaml and policy.yaml. Resolves user-config directory.

The default config lives in `~/.glc/`. Override with GLC_CONFIG_DIR for
tests and CI. The directory is created on import if missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_DIR = Path(os.path.expanduser("~/.glc"))
CONFIG_DIR = Path(os.getenv("GLC_CONFIG_DIR", str(DEFAULT_DIR)))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
_INSTALL_TOKEN_CACHE: str | None = None

# Packaged defaults shipped with glc (under the policy/ subpackage).
PACKAGED_POLICY = Path(__file__).parent / "policy" / "policy.yaml"
PACKAGED_CHANNELS = Path(__file__).parent / "channels.yaml"


def policy_yaml_path() -> Path:
    user = CONFIG_DIR / "policy.yaml"
    return user if user.exists() else PACKAGED_POLICY


def channels_yaml_path() -> Path:
    user = CONFIG_DIR / "channels.yaml"
    return user if user.exists() else PACKAGED_CHANNELS


def load_channels() -> dict:
    p = channels_yaml_path()
    if not p.exists():
        return {"channels": {}}
    return yaml.safe_load(p.read_text()) or {"channels": {}}


def install_token_path() -> Path:
    return CONFIG_DIR / "install_token"


def _ram_only_install_token_enabled() -> bool:
    return os.getenv("GLC_INSTALL_TOKEN_RAM_ONLY", "1") == "1"


def get_or_create_install_token() -> str:
    """Per-installation token used to authenticate WS adapter connections
    and /v1/control/* requests. Generated once and persisted to disk."""
    global _INSTALL_TOKEN_CACHE
    if _INSTALL_TOKEN_CACHE:
        return _INSTALL_TOKEN_CACHE

    p = install_token_path()
    if p.exists():
        tok = p.read_text().strip()
        _INSTALL_TOKEN_CACHE = tok
        if _ram_only_install_token_enabled():
            try:
                p.unlink()
            except OSError:
                pass
        return tok
    import secrets

    tok = secrets.token_urlsafe(32)
    p.write_text(tok)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    _INSTALL_TOKEN_CACHE = tok
    if _ram_only_install_token_enabled():
        try:
            p.unlink()
        except OSError:
            pass
    return tok


def get_install_token_for_display() -> str:
    """Installer-facing token export helper.

    Partial hardening: disallow token display by default in production-like
    environments unless explicitly enabled.
    """
    env = os.getenv("GLC_ENV", "").strip().lower()
    if env in {"prod", "production"} and os.getenv("GLC_ALLOW_TOKEN_EXPORT", "0") != "1":
        raise RuntimeError(
            "token export is disabled in production (set GLC_ALLOW_TOKEN_EXPORT=1 to override)"
        )
    return get_or_create_install_token()
