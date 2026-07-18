from __future__ import annotations


def test_install_token_defaults_to_ram_only(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setenv("GLC_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("GLC_INSTALL_TOKEN_RAM_ONLY", raising=False)

    import glc.config as c

    c.CONFIG_DIR = cfg
    c._INSTALL_TOKEN_CACHE = None

    token = c.get_or_create_install_token()
    assert token
    assert not c.install_token_path().exists()


def test_install_token_can_be_persisted_when_disabled(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setenv("GLC_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("GLC_INSTALL_TOKEN_RAM_ONLY", "0")

    import glc.config as c

    c.CONFIG_DIR = cfg
    c._INSTALL_TOKEN_CACHE = None

    token = c.get_or_create_install_token()
    assert token
    assert c.install_token_path().exists()
