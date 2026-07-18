"""V9-compatible per-call ledger. Same schema as llm_gatewayV9/db.py, but
the database lives under ~/.glc/ so the gateway is installable as a daemon
without writing into the source tree.

Note: this is the *worker call* ledger, used by /v1/cost/by_agent. The
audit log (every channel message, policy verdict, tool dispatch) is a
separate append-only store under glc/audit/store.py.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DIR = Path(os.path.expanduser("~/.glc"))
DB_PATH = os.getenv("GLC_GATEWAY_DB", str(DEFAULT_DIR / "gateway.sqlite"))

_MAX_TOKEN_COUNT = 10_000_000
_MAX_LATENCY_MS = 3_600_000
_MAX_TEXT_CHARS = 5_000_000
_MAX_TOOL_CALLS = 10_000
_MAX_RETRIES = 100
_MAX_EMBED_DIM = 1_000_000


def _ensure_parent() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def conn():
    _ensure_parent()
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_create_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT,
                error TEXT,
                prompt_chars INTEGER DEFAULT 0,
                response_chars INTEGER DEFAULT 0,
                override TEXT,
                attempted TEXT,
                tool_calls INTEGER DEFAULT 0,
                reasoning_applied INTEGER DEFAULT 0,
                tool_dialect TEXT,
                call_role TEXT DEFAULT 'worker',
                router_decision TEXT,
                embed_dim INTEGER,
                agent TEXT,
                session TEXT,
                tenant TEXT,
                retries INTEGER DEFAULT 0
            )"""
        )
        cols = {r[1] for r in c.execute("PRAGMA table_info(calls)").fetchall()}
        if "tenant" not in cols:
            c.execute("ALTER TABLE calls ADD COLUMN tenant TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON calls(ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_prov_ts ON calls(provider, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_role_ts ON calls(call_role, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_agent_ts ON calls(agent, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_session_ts ON calls(session, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tenant_ts ON calls(tenant, ts DESC)")


def _require_non_empty_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_bounded_int(name: str, value: object, *, min_value: int = 0, max_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < min_value or value > max_value:
        raise ValueError(f"{name} out of range [{min_value}, {max_value}]")
    return value


def _validate_log_call_inputs(
    provider,
    model,
    input_tokens,
    output_tokens,
    latency_ms,
    prompt_chars,
    response_chars,
    cache_create_tokens,
    cache_read_tokens,
    tool_calls,
    embed_dim,
    retries,
) -> None:
    _require_non_empty_str("provider", provider)
    _require_non_empty_str("model", model)

    _require_bounded_int("input_tokens", input_tokens, max_value=_MAX_TOKEN_COUNT)
    _require_bounded_int("output_tokens", output_tokens, max_value=_MAX_TOKEN_COUNT)
    _require_bounded_int("cache_create_tokens", cache_create_tokens, max_value=_MAX_TOKEN_COUNT)
    _require_bounded_int("cache_read_tokens", cache_read_tokens, max_value=_MAX_TOKEN_COUNT)
    _require_bounded_int("latency_ms", latency_ms, max_value=_MAX_LATENCY_MS)
    _require_bounded_int("prompt_chars", prompt_chars, max_value=_MAX_TEXT_CHARS)
    _require_bounded_int("response_chars", response_chars, max_value=_MAX_TEXT_CHARS)
    _require_bounded_int("tool_calls", tool_calls, max_value=_MAX_TOOL_CALLS)
    _require_bounded_int("retries", retries, max_value=_MAX_RETRIES)

    if embed_dim is not None:
        _require_bounded_int("embed_dim", embed_dim, min_value=1, max_value=_MAX_EMBED_DIM)


def log_call(
    provider,
    model,
    input_tokens=0,
    output_tokens=0,
    latency_ms=0,
    status="ok",
    error=None,
    prompt_chars=0,
    response_chars=0,
    override=None,
    attempted=None,
    cache_create_tokens=0,
    cache_read_tokens=0,
    tool_calls=0,
    reasoning_applied=False,
    tool_dialect=None,
    call_role="worker",
    router_decision=None,
    embed_dim=None,
    agent=None,
    session=None,
    tenant=None,
    retries=0,
) -> None:
    _validate_log_call_inputs(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        cache_create_tokens=cache_create_tokens,
        cache_read_tokens=cache_read_tokens,
        tool_calls=tool_calls,
        embed_dim=embed_dim,
        retries=retries,
    )

    with conn() as c:
        c.execute(
            """INSERT INTO calls (ts, provider, model, input_tokens, output_tokens,
                                  cache_create_tokens, cache_read_tokens,
                                  latency_ms, status, error, prompt_chars, response_chars,
                                  override, attempted, tool_calls, reasoning_applied, tool_dialect,
                                  call_role, router_decision, embed_dim,
                                  agent, session, tenant, retries)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(),
                provider,
                model,
                input_tokens,
                output_tokens,
                cache_create_tokens,
                cache_read_tokens,
                latency_ms,
                status,
                error,
                prompt_chars,
                response_chars,
                override,
                attempted,
                tool_calls,
                1 if reasoning_applied else 0,
                tool_dialect,
                call_role,
                router_decision,
                embed_dim,
                agent,
                session,
                tenant,
                retries,
            ),
        )


def by_agent(session=None, since=None, tenant=None):
    where = ["ts >= ?"]
    # Day-rollover fix: bucket by calendar day, not by 24h window.
    args = [since if since is not None else (time.time() - (time.time() % 86400))]
    if session:
        where.append("session=?")
        args.append(session)
    if tenant:
        where.append("tenant=?")
        args.append(tenant)
    q = (
        "SELECT agent, provider, COUNT(*) AS calls, "
        "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
        "SUM(latency_ms) AS total_latency_ms, "
        "SUM(retries) AS total_retries, "
        "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok, "
        "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors "
        "FROM calls WHERE " + " AND ".join(where) + " AND agent IS NOT NULL "
        "GROUP BY agent, provider"
    )
    with conn() as c:
        rows = c.execute(q, args).fetchall()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["agent"], []).append(dict(r))
        return out


def recent(limit=100, provider=None, status=None, tenant=None):
    q = "SELECT * FROM calls"
    where, args = [], []
    if provider:
        where.append("provider=?")
        args.append(provider)
    if status:
        where.append("status=?")
        args.append(status)
    if tenant:
        where.append("tenant=?")
        args.append(tenant)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def aggregate(call_role=None):
    now = time.time()
    day_start = now - (now % 86400)
    q = """SELECT provider,
                  COUNT(*) AS calls,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_calls,
                  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                  SUM(input_tokens) AS in_tok,
                  SUM(output_tokens) AS out_tok,
                  SUM(cache_read_tokens) AS cache_reads,
                  SUM(cache_create_tokens) AS cache_creates,
                  SUM(tool_calls) AS tool_calls,
                  AVG(latency_ms) AS avg_latency,
                  MAX(ts) AS last_ts
             FROM calls WHERE ts >= ?"""
    args = [day_start]
    if call_role == "worker":
        q += " AND (call_role='worker' OR call_role IS NULL)"
    elif call_role == "router":
        q += " AND call_role LIKE 'router%'"
    elif call_role:
        q += " AND call_role=?"
        args.append(call_role)
    q += " GROUP BY provider"
    with conn() as c:
        rows = c.execute(q, args).fetchall()
        return {r["provider"]: dict(r) for r in rows}
