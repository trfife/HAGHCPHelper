# HAGHCPHelper — Project Guidelines

## Project Overview

Home Assistant add-on + custom integration that brings GitHub Copilot CLI into HA.
Two main components ship together and must stay in sync.

## Architecture

| Directory | Purpose |
|-----------|---------|
| `custom_components/ghcp_conversation/` | HA custom integration (conversation entity) |
| `copilot-cli/` | HA add-on (Docker container with Copilot CLI + web terminal) |
| `copilot-cli/ghcp_conversation/` | **Synced copy** of the integration bundled in the add-on |
| `research/` | Architecture research and decisions (read-only reference) |

## Version Locations — CRITICAL

**5 places** must ALL match on every version bump:

1. `custom_components/ghcp_conversation/manifest.json` → `"version"`
2. `copilot-cli/ghcp_conversation/manifest.json` → `"version"` (synced via Copy-Item)
3. `copilot-cli/config.yaml` → `version`
4. `custom_components/ghcp_conversation/acp_client.py` → `CLIENT_VERSION`
5. `copilot-cli/ghcp_conversation/acp_client.py` → `CLIENT_VERSION` (synced via Copy-Item)

**Workflow:** Update #1, #3, #4 first, then sync #2 and #5 via:
```powershell
Copy-Item -Path "custom_components\ghcp_conversation\*" -Destination "copilot-cli\ghcp_conversation\" -Recurse -Force
```

## Git Workflow

- Create branches for features: `feature/name`, `release/X.Y.Z`
- Commit after each milestone, not at the end
- Always bump version + update CHANGELOG before pushing
- Tag releases: `git tag -a vX.Y.Z -m "description"`
- Push with tags: `git push origin main --tags`

## Build & Test

No automated tests yet. Verify by:
1. Updating the add-on in HA
2. Checking HA logs: Settings → System → Logs → filter `ghcp_conversation`
3. Enable debug logging: Integration → 3-dot menu → "Enable debug logging"

## Code Conventions

- Python 3.14+ (HA requirement), type hints everywhere
- Use `_LOGGER` (module-level `logging.getLogger(__name__)`)
- Log at INFO for routing decisions, DEBUG for details, ERROR for failures
- Async throughout — all HA APIs are async
- Use `aiohttp.ClientSession` for HTTP calls (short-lived, create per-request)
- Config flow follows HA patterns: `ConfigFlow`, `OptionsFlow`, subentry flows
- All user-facing strings in `strings.json` AND `translations/en.json` (must match)

## Key Patterns

### Conversation Entity
- Inherits from `ConversationEntity`
- `_async_handle_message()` is the entry point
- Must return `ConversationResult` with `IntentResponse`

### Hybrid Routing
- `router.py` classifies intent → LOCAL / AZURE / CLI
- LOCAL + AZURE use `build_azure_client()` with Azure Foundry endpoint
- CLI uses `ACPClient` to talk to `copilot --acp` over TCP

### Azure OpenAI
- Base URL: `https://{resource}.cognitiveservices.azure.com`
- `build_azure_client()` constructs full deployment URL automatically
- Auth via `api-key` header (not Bearer token)
- `llm.APIInstance` uses `.api_prompt` (NOT `.prompt`)

### Don't

- Never hardcode secrets, tokens, or API keys
- Never use `data[KEY]` for optional config — use `data.get(KEY, default)`
- Never assume aiosqlite is installed — always guard with try/except ImportError
- Never call `chat_log.async_provide_llm_data()` more than once per request
