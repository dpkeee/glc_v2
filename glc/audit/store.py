"""Append-only SQLite audit log.

Every channel message, agent decision, policy verdict, and tool dispatch
lands here. Append-only is enforced at the application layer: only
`append()` is exposed; there is no update or delete function. The schema
ships with `audit_schema` version 1; bumping it requires a documented
migration step (see schema.sql).

Each append commits immediately so writes survive a hard kill.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(os.path.expanduser("~/.glc"))


def _resolve_path() -> str:
    """Resolve at call time, not import time, so tests that swap the env
    var see the change."""
    return os.getenv("GLC_AUDIT_DB", str(DEFAULT_DIR / "audit.sqlite"))


@contextmanager
def _conn():
    p = _resolve_path()
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, isolation_level=None)  # autocommit; each insert flushes
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _row_digest(row: dict[str, Any]) -> str:
    """Stable digest for one audit row, used by the hash chain."""
    payload = {
        "id": row.get("id"),
        "ts": row.get("ts"),
        "session_id": row.get("session_id"),
        "channel": row.get("channel"),
        "channel_user_id": row.get("channel_user_id"),
        "trust_level": row.get("trust_level"),
        "event_type": row.get("event_type"),
        "tool": row.get("tool"),
        "policy_verdict": row.get("policy_verdict"),
        "params_json": row.get("params_json"),
        "result_json": row.get("result_json"),
        "prev_hash": row.get("prev_hash"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def init_store() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA_PATH.read_text())
        cols = {r["name"] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
        if "prev_hash" not in cols:
            c.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
        c.execute("INSERT OR IGNORE INTO audit_schema (version, applied_at) VALUES (2, strftime('%s','now'))")


def _jsonify(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, default=str)
    except Exception:
        return json.dumps({"_repr": repr(v)})


class AuditStore:
    """Application-layer write-once store. The class deliberately exposes
    no update or delete methods. Reads (for the replay viewer) live in
    query() which is read-only."""

    def append(
        self,
        *,
        channel: str,
        channel_user_id: str,
        trust_level: str,
        event_type: str,
        session_id: str | None = None,
        tool: str | None = None,
        policy_verdict: str | None = None,
        params: Any = None,
        result: Any = None,
    ) -> int:
        with _conn() as c:
            c.execute("BEGIN IMMEDIATE")
            prev = c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = _row_digest(dict(prev)) if prev is not None else None
            cur = c.execute(
                """INSERT INTO audit_log
                   (ts, session_id, channel, channel_user_id, trust_level,
                    event_type, tool, policy_verdict, params_json, result_json, prev_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    session_id,
                    channel,
                    channel_user_id,
                    trust_level,
                    event_type,
                    tool,
                    policy_verdict,
                    _jsonify(params),
                    _jsonify(result),
                    prev_hash,
                ),
            )
            c.execute("COMMIT")
            return int(cur.lastrowid or 0)


_singleton: AuditStore | None = None


def get_store() -> AuditStore:
    global _singleton
    if _singleton is None:
        init_store()
        _singleton = AuditStore()
    return _singleton


def append(**kwargs: Any) -> int:
    return get_store().append(**kwargs)


def query(limit: int = 100, session_id: str | None = None, channel: str | None = None) -> list[dict]:
    q = "SELECT * FROM audit_log"
    where, args = [], []
    if session_id:
        where.append("session_id=?")
        args.append(session_id)
    if channel:
        where.append("channel=?")
        args.append(channel)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def schema_version() -> int:
    with _conn() as c:
        row = c.execute("SELECT MAX(version) AS v FROM audit_schema").fetchone()
        return int(row["v"] or 0)


def verify_chain() -> bool:
    """Return True when the append-only hash chain is consistent."""
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()]
    if not rows:
        return True
    first_prev = rows[0].get("prev_hash")
    if first_prev not in (None, ""):
        return False
    for prev, cur in zip(rows, rows[1:]):
        if cur.get("prev_hash") != _row_digest(prev):
            return False
    return True
