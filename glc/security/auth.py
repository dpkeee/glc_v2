"""Gateway authentication helpers.

In production, all HTTP routes are protected by a bearer token. We use an
explicit token from GLC_GATEWAY_AUTH_TOKEN when provided, and otherwise fall
back to the per-installation token used by control/websocket surfaces.
"""

from __future__ import annotations

import os
import re

from fastapi import HTTPException

from glc.config import get_or_create_install_token


def is_production_mode() -> bool:
    env = os.getenv("GLC_ENV", "").strip().lower()
    if env in {"prod", "production"}:
        return True
    return os.getenv("GLC_PRODUCTION", "0").strip() == "1"


def get_gateway_auth_token() -> str:
    configured = os.getenv("GLC_GATEWAY_AUTH_TOKEN", "").strip()
    if configured:
        return configured
    return get_or_create_install_token()


def require_gateway_bearer(authorization: str | None) -> None:
    expected = get_gateway_auth_token()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token (Authorization: Bearer <gateway_token>)")
    presented = authorization.removeprefix("Bearer ").strip()
    if presented != expected:
        raise HTTPException(403, "gateway token mismatch")


def tenant_from_headers(headers) -> str:
    """Resolve tenant ID from request headers.

    Header precedence:
    1) X-GLC-Tenant
    2) X-Tenant-ID
    """
    tenant = (headers.get("x-glc-tenant") or headers.get("x-tenant-id") or "").strip()
    if not tenant:
        return "default"
    if len(tenant) > 64 or not re.fullmatch(r"[A-Za-z0-9._-]+", tenant):
        raise HTTPException(400, "invalid tenant identifier")
    return tenant
