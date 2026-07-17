# Part 1 Fix: Disable API Documentation Endpoints in Production

## Finding

The production gateway exposed a full route inventory through OpenAPI and docs endpoints.

## Reproduction

Command:

```powershell
curl.exe -sS "https://rainitover--glc-v1-gateway-fastapi-app.modal.run/openapi.json"
```

Observed result:

- Returned the OpenAPI schema with route and channel details.

## Security Impact

Publicly exposing documentation and schema endpoints increases attack surface by revealing internal API structure and capabilities.

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

