---
description: "Use when modifying entity.py, the conversation entity handler. Covers routing, tool calling, chat_log usage, and common pitfalls."
applyTo: "**/entity.py"
---
# Entity.py — Conversation Handler Rules

## Routing Architecture
- `_async_handle_message()` dispatches by backend: copilot_cli → hybrid → direct_api
- `_async_handle_hybrid()` uses `classify_intent()` → LOCAL / AZURE / CLI
- LOCAL and AZURE both use `_async_handle_azure_fast()` with Azure Foundry
- CLI uses `_async_handle_acp()` with ACP protocol over TCP

## Critical: HA LLM API
- `chat_log.async_provide_llm_data()` can only be called ONCE per request
- `chat_log.llm_api` is an `APIInstance` — use `.api_prompt` NOT `.prompt`
- `chat_log.llm_api.tools` returns the tool list
- Tools are executed via `chat_log.llm_api.async_call_tool(ToolInput(...))`

## Critical: Config Data
- Always use `data.get(KEY, default)` — never `data[KEY]` for optional fields
- Hybrid backend has NO `github_token` — don't assume it exists
- `_get_client()` must handle BACKEND_HYBRID using Azure router creds

## Analytics
- Import with try/except ImportError (aiosqlite may not be installed)
- `RequestMetrics` may be None — guard all `.route`, `.model`, etc. with `if metrics`
- Log at `finally` block so stats are recorded even on error

## Logging
- INFO: routing decisions, response sizes
- DEBUG: message counts, tool counts, iterations, API URLs
- ERROR: only for actual failures, include context
