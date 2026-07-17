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

## Verification After Fix

The following endpoints now return:

```json
{"detail":"Not Found"}
```

Endpoints verified:

- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/redoc
- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/openapi.json
- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/docs

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

## Verification After Fix

Without Authorization header, the following endpoints now return:

```json
{"detail":"missing bearer token (Authorization: Bearer <gateway_token>)"}
```

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

## Verification After Fix

Without Authorization header, LLM routes now return:

```json
{"detail":"missing bearer token (Authorization: Bearer <gateway_token>)"}
```

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

## Verification After Fix

Validated with unit tests:

- `tests/test_image_url_ssrf.py::test_image_fetch_rejects_without_allowlist`
- `tests/test_image_url_ssrf.py::test_image_fetch_blocks_private_ipv4_even_with_wildcard`
- `tests/test_image_url_ssrf.py::test_image_fetch_blocks_ipv6_loopback`
- `tests/test_image_url_ssrf.py::test_image_fetch_rechecks_destination_on_redirect`

Test run:

```powershell
uv run pytest tests/test_image_url_ssrf.py tests/test_v9_compat.py::test_chat_request_minimal_body_validates
```

Observed result:

- All tests passed, confirming allowlist enforcement, private-range blocking for IPv4/IPv6, and redirect-hop re-validation.
