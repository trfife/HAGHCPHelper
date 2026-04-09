---
description: "Use when modifying api.py or build_azure_client. Covers Azure OpenAI URL construction, auth headers, and client patterns."
applyTo: "**/api.py"
---
# API Client Rules

## Azure OpenAI URL Construction
`build_azure_client(session, endpoint, api_key, model="")` handles:
- Full URL with `/chat/completions` → use as-is
- Base URL + model → builds `/openai/deployments/{model}/chat/completions?api-version=...`
- Base URL without model → appends `/chat/completions` (will likely fail on Azure OpenAI)

**Always pass model** when calling `build_azure_client()`.

## Auth Headers
- GitHub Models: `Authorization: Bearer {token}` + `X-GitHub-Api-Version` + Accept header
- Azure OpenAI: `api-key: {key}` header (NOT Bearer token, NOT Authorization header)

## Error Handling
- 401 → `APIError("Authentication failed", 401)`
- 403 → `APIError("Access denied", 403)`
- 429 → `APIError("Rate limited", 429)`
- Other 4xx/5xx → include response body in error message
- `aiohttp.ClientError` → wrap as `APIError("Connection error: ...")`

## Timeout
- Default: 120 seconds (`aiohttp.ClientTimeout(total=120)`)
- Validation requests use `max_tokens=5` to be fast

## Logging
- DEBUG: full URL, model name, message count, tool count
- DEBUG: HTTP response status code
