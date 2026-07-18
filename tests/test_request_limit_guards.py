from __future__ import annotations


def test_chat_batch_rejects_too_many_calls(app_client):
    calls = [{"prompt": "hi"} for _ in range(51)]
    r = app_client.post("/v1/chat/batch", json={"calls": calls, "max_concurrency": 4})
    assert r.status_code == 422


def test_chat_batch_rejects_excessive_concurrency(app_client):
    r = app_client.post(
        "/v1/chat/batch",
        json={"calls": [{"prompt": "hi"}], "max_concurrency": 10_000},
    )
    assert r.status_code == 422


def test_chat_rejects_overly_deep_response_schema(app_client):
    deep = {}
    cur = deep
    for i in range(35):
        nxt = {f"lvl_{i}": {}}
        cur["properties"] = nxt
        cur = nxt[f"lvl_{i}"]

    r = app_client.post(
        "/v1/chat",
        json={
            "prompt": "hi",
            "response_format": {
                "type": "json_schema",
                "schema": deep,
                "name": "out",
                "strict": True,
            },
        },
    )
    assert r.status_code == 400
    assert "response schema too deep" in str(r.json())
