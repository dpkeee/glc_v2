from __future__ import annotations

import pytest
from fastapi import HTTPException

from glc.routes import chat as chat_route


class _FakeResponse:
    def __init__(self, url: str, status_code: int, headers: dict | None = None, content: bytes = b""):
        import httpx

        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.request = httpx.Request("GET", url)

    def raise_for_status(self) -> None:
        import httpx

        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=self.request, response=self)


class _FakeClient:
    def __init__(self, responses: dict[str, _FakeResponse]):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str):
        return self._responses[url]


@pytest.mark.asyncio
async def test_image_fetch_rejects_without_allowlist(monkeypatch):
    monkeypatch.delenv("GLC_IMAGE_FETCH_ALLOWLIST", raising=False)

    with pytest.raises(HTTPException) as exc:
        await chat_route._fetch_to_data_url("https://example.com/image.png")

    assert exc.value.status_code == 400
    assert "allowlist" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_image_fetch_blocks_private_ipv4_even_with_wildcard(monkeypatch):
    monkeypatch.setenv("GLC_IMAGE_FETCH_ALLOWLIST", "*")

    with pytest.raises(HTTPException) as exc:
        await chat_route._fetch_to_data_url("http://127.0.0.1/image.png")

    assert exc.value.status_code == 400
    assert "blocked" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_image_fetch_blocks_ipv6_loopback(monkeypatch):
    monkeypatch.setenv("GLC_IMAGE_FETCH_ALLOWLIST", "*")

    with pytest.raises(HTTPException) as exc:
        await chat_route._fetch_to_data_url("http://[::1]/image.png")

    assert exc.value.status_code == 400
    assert "blocked" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_image_fetch_rechecks_destination_on_redirect(monkeypatch):
    import httpx

    monkeypatch.setenv("GLC_IMAGE_FETCH_ALLOWLIST", "*")

    responses = {
        "https://example.com/start": _FakeResponse(
            "https://example.com/start",
            302,
            headers={"location": "http://127.0.0.1/internal.png"},
        )
    }

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeClient(responses))

    with pytest.raises(HTTPException) as exc:
        await chat_route._fetch_to_data_url("https://example.com/start")

    assert exc.value.status_code == 400
    assert "blocked" in str(exc.value.detail).lower()
