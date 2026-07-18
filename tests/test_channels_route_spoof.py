from __future__ import annotations

from datetime import UTC, datetime

from starlette.websockets import WebSocketDisconnect

from glc.channels.envelope import ChannelMessage


def _mk_msg(channel: str) -> ChannelMessage:
    return ChannelMessage(
        channel=channel,
        channel_user_id="u-1",
        user_handle="user",
        text="hello",
        trust_level="untrusted",
        arrived_at=datetime.now(UTC),
        metadata={},
    )


def test_webhook_rejects_cross_channel_spoof(app_client, monkeypatch):
    class _FakeAdapter:
        async def on_message(self, raw):
            return _mk_msg(channel="discord")

        async def send(self, reply):
            return None

    monkeypatch.setattr("glc.routes.channels.registry.instantiate", lambda name: _FakeAdapter())

    r = app_client.post("/v1/channels/telegram/webhook", json={"event": "x"})
    assert r.status_code == 400
    assert r.json()["error"] == "envelope channel mismatch"


def test_ws_rejects_cross_channel_spoof(app_client, install_token):
    payload = {
        "channel": "discord",
        "channel_user_id": "u-1",
        "user_handle": "user",
        "text": "hello",
        "attachments": [],
        "voice_audio_ref": None,
        "thread_id": None,
        "trust_level": "untrusted",
        "arrived_at": datetime.now(UTC).isoformat(),
        "metadata": {},
    }

    with app_client.websocket_connect(f"/v1/channels/telegram?token={install_token}") as ws:
        ws.send_json(payload)
        msg = ws.receive_json()
        assert "dropped: envelope channel mismatch" in msg["error"]
        try:
            ws.receive_text()
            raise AssertionError("expected websocket close after spoofed envelope")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
