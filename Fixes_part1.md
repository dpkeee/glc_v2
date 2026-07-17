# Part 1 
## Disable API Documentation Endpoints in Production

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

## Require Bearer Token for Sensitive Operational Endpoints

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

## Unauthenticated LLM Abuse

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

Endpoints verified:

- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/chat
- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/vision
- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/embed
- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/transcribe
- https://rainitover--glc-v1-gateway-fastapi-app.modal.run/v1/speak


