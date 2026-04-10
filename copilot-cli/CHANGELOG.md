# Changelog

## 3.1.0

- **Email notifications** — optionally email the full response (including AI reasoning/thinking log) after each conversation turn
- New `ACPResponse` dataclass captures thinking content from `agent_thought_chunk` ACP notifications (previously discarded)
- Configurable via integration options: notify service, mode (off/always/long only), character threshold
- Email is best-effort and non-blocking — failures never affect the conversation response
- Thinking content capped at 50k chars with truncation notice
- Accepts `notify.service_name` or bare `service_name` format
- Fixed options flow to use merged data+options for correct default values when reopening

## 3.0.9

- **Fix: terminal copy/paste** — disabled tmux mouse capture by default so browser-native copy/paste works in the HA ingress iframe
- Added `Ctrl+b m` keybinding to toggle mouse mode on/off (enable for wheel scrolling when needed)
- Removed complex WheelUpPane/WheelDownPane bindings in favor of simpler keyboard scrolling (`Ctrl+b [`)
- Updated docs with new copy/paste and scrolling instructions

## 3.0.8

- **Train of thought logging** — every conversation turn now logs a full reasoning trace to the `conversation_trace` SQLite table
- `TraceLog` captures: route decision (with pattern + confidence), each step with millisecond timestamps, tool calls, model used, response summary, success/failure
- Queryable via `async_get_traces(limit=20)` for analysis
- Query traces: `sqlite3 /homeassistant/.storage/ghcp_conversation_analytics.db "SELECT timestamp, route, steps, latency_ms FROM conversation_trace ORDER BY id DESC LIMIT 10"`

## 3.0.7

- **Self-modification: CLI can edit its own repo** — HAGHCPHelper repo auto-cloned to `/data/projects/HAGHCPHelper` on startup using the configured GitHub token
- Git credentials set up automatically for push access
- Copilot instructions include full self-modification workflow: repo structure, 5 version locations, branch/commit/push workflow, key rules
- New aliases: `self-edit` and `repo` to jump to the project directory
- Persistent across restarts (stored in `/data/projects/`)

## 3.0.6

- **Fix: `ToolResultContent` attribute** — HA uses `.tool_result` not `.result` in `_build_messages()`. This was the actual cause of Azure route crashes (`'ToolResultContent' object has no attribute 'result'`)
- **CLI model default changed to `claude-opus-4.6`** — model dropdown now leads with Opus 4.6 (high quality) instead of gpt-5-mini
- Model list reordered: Opus/Sonnet models first in dropdown

## 3.0.5

- **Comprehensive logging at every decision point** — enable debug logging via Settings → Devices & Services → GitHub Copilot Conversation → 3-dot menu → "Enable debug logging" to see:
  - Integration startup: backend type, config keys loaded
  - Every incoming message: backend, agent name, prompt text
  - Hybrid router: route decision, matched pattern
  - ACP handler: host/port, response size, session ID
  - Azure fast handler: endpoint, model, message count, tool count, iterations, response size
  - API client: full URL, HTTP status code, model name
  - Tool calls: which tools called and in what order

## 3.0.4

- **Fix: `'APIInstance' object has no attribute 'prompt'`** — HA's `llm.APIInstance` uses `api_prompt` not `prompt`. Fixed in all 3 occurrences (Azure fast handler, direct API handler, expert escalation handler). This was the cause of Azure route failures falling back to CLI.

## 3.0.3

- **Fix: graceful fallback when aiosqlite not installed** — analytics import failure no longer crashes the entire integration; analytics is skipped and a warning is logged
- All `metrics` references guarded with `if metrics` checks
- Added debug logging to Azure fast handler and URL builder for diagnostics
- Integration will now load and work even if aiosqlite pip install hasn't completed yet

## 3.0.2

- **Fix: Hybrid routing now works for all 3 tiers** — LOCAL and AZURE routes now correctly use the Azure router credentials instead of trying to use missing GitHub token
- `_get_client()` handles `BACKEND_HYBRID` by using Azure router endpoint/key
- LOCAL route in hybrid mode uses Azure fast model (not direct API which requires GitHub token)
- Graceful fallthrough: if no Azure credentials configured, all routes go to CLI
- Better error logging for debugging route failures

## 3.0.1

- **Fix: Azure OpenAI endpoint URL construction** — base URLs like `https://barnabeefoundry.cognitiveservices.azure.com` now correctly build the full `/openai/deployments/{model}/chat/completions?api-version=...` path
- Hybrid config step now passes the model/deployment name to the Azure client builder
- Distinct error message for Azure connection failures vs CLI connection failures

## 3.0.0

### Hybrid Routing Engine
- **Azure AI Foundry fast-routing** — simple queries (device control, state checks) are handled locally or via a fast Azure model in < 1s; complex tasks route to Copilot CLI expert
- **Deterministic intent classifier** — regex-based pattern matching for instant local routing of common commands (turn on/off, state queries, set values) with zero API calls
- **Configurable hybrid backend** — new "Hybrid — Azure fast + CLI expert" option combines fast Azure inference with Copilot CLI expert fallback; select during integration setup
- **Graceful fallback chain** — if Azure is unavailable or fails, automatically falls through to Copilot CLI; if no Azure configured, uses direct API

### Analytics & Learning
- **Request analytics database** — every conversation logs route taken, latency (ms), tokens in/out, success/failure to a SQLite database for performance analysis
- **Knowledge store upgrade** — migrated from JSON to SQLite with hit-count tracking; every knowledge search bumps hit_count on matched entries
- **Promotion candidate detection** — knowledge entries with high hit counts are flagged as candidates for future fast-engine rule promotion via `async_get_promotion_candidates()`
- **Legacy migration** — existing JSON knowledge store entries automatically imported into SQLite on first load

### Copilot CLI Enhancements
- **Memory MCP server** — persistent knowledge graph (`@modelcontextprotocol/server-memory`) across CLI sessions, stored at `/data/copilot-persist/memory/`
- **Git config tracking** — automatic `git init` + `.gitignore` on `/homeassistant`; takes config snapshots on every add-on startup for change tracking and rollback
- **Path-specific instructions** — targeted Copilot instructions for automation editing (`automations.instructions.md`) and debugging workflows (`debugging.instructions.md`) with `applyTo` globs
- **AGENTS.md agent modes** — four specialized modes: Device Controller, Config Editor, Automation Builder, and Diagnostics Expert
- Node.js/npm added to container for MCP server support

### Infrastructure
- New `router.py` — intent classification and routing engine with LOCAL/AZURE/CLI routes
- New `analytics.py` — SQLite-based request logging, statistics, knowledge storage with hit tracking
- Updated `entity.py` — `_async_handle_hybrid()` orchestrator, `_async_handle_azure_fast()` for Azure AI Foundry
- Updated `const.py` — `BACKEND_HYBRID`, Azure router config constants
- Updated `config_flow.py` — new hybrid backend setup step with Azure + ACP validation
- Updated `manifest.json` — `aiosqlite>=0.20.0` dependency
- Updated `Dockerfile` — Node.js, npm, `@modelcontextprotocol/server-memory`
- Updated `ttyd/run` — Memory MCP, git tracking, path instructions, AGENTS.md generation

## 2.2.0

- **Fix: ACP server now respects model config** — the `model` option from add-on settings is now passed to `copilot --acp --model <model>`, matching the ttyd terminal behavior
- **Updated model list** — config schema now includes all available Copilot CLI models: GPT-5 mini, GPT-4.1, GPT-5.4, Claude Haiku/Sonnet/Opus families
- **Default model changed to `gpt-5-mini`** — fastest available model (0x cost) for routine tasks
- Fixed fallback model names — removed non-existent `openai/gpt-5-nano` and `openai/gpt-4.1-nano`

## 2.1.0

- **Orchestrator mode with expert escalation** — fast model (default: gpt-5-nano) handles simple tasks directly; complex questions are escalated to a configurable expert model (e.g., Claude Opus 4.6) via synthetic `ask_expert` tool
- **Persistent knowledge memory** — every expert answer is auto-logged to a knowledge store (`.storage/ghcp_conversation.knowledge`); the fast model checks `search_knowledge` before escalating, learning from past answers and avoiding redundant expert calls
- New `expert_model` config option in setup flow, options flow, and per-agent subentry overrides
- Knowledge store uses HA's `Store` helper — persists across restarts, FIFO eviction at 200 entries
- Keyword-based search with stopword filtering for knowledge retrieval
- System prompt automatically augmented with orchestrator instructions when expert model is configured
- Updated default model from `gpt-4.1-mini` to `gpt-5-nano` (fastest with reasoning)
- Updated fallback model list to include gpt-5 family
- Fully backward compatible — no expert model configured = existing behavior unchanged

## 2.0.2

- **Major: Copilot CLI ACP integration** — conversation agent now routes through the Copilot CLI add-on via the Agent Client Protocol (ACP) for full AI capabilities
- New `copilot_cli` backend: connects to `copilot --acp --port 3000` running as an s6 service inside the add-on container
- Full CLI power: shell commands, file editing, MCP server access, reasoning/planning — all handled by the Copilot CLI agent
- New ACP s6 service (`copilot-acp`) starts automatically when `enable_conversation_agent` is enabled
- Auto-detects add-on hostname within the HA Docker network
- Existing GitHub Models (direct API) and Azure AI backends remain available as fallback
- New `acp_client.py`: async NDJSON/TCP client implementing JSON-RPC 2.0 ACP protocol
- Auto-approves tool permission requests so the CLI agent can operate autonomously

## 1.3.2

- **Fix**: Default conversation agent now always gets HA Assist API access for entity control (was previously only enabled for subentry agents)
- "Close the office blinds", "turn on the lights", etc. now work out of the box

## 1.3.1

- Show all chat models from the catalog (not just tool-calling ones), only exclude embedding models

## 1.3.0

- **Dynamic model catalog** — models are now fetched live from the GitHub Models API instead of a hardcoded list
- Only chat-capable models (with tool-calling support) are shown
- Fallback to a small default list if the catalog API is unavailable
- Options flow also fetches live models when changing model selection

## 1.2.3

- Fixed syntax error in github_auth.py (leftover code from previous refactor) that prevented the integration from loading

## 1.2.2

- Fixed device flow sign-in: now shows the code and URL on a proper form page instead of a blank progress spinner
- User flow: see code + link, open browser, authorize, click Submit

## 1.2.1

- Fixed auto-install not updating when OAuth client_id was added without a version bump

## 1.2.0

- **Browser sign-in for GitHub Models** — OAuth device flow: open browser, enter code, authorize, done. Token never expires.
- Two auth options: "Sign in with GitHub" (OAuth) or Personal Access Token (PAT) fallback
- Requires a GitHub OAuth App client_id (one-time setup by the add-on maintainer)
- If no OAuth App is configured, gracefully falls back to PAT-only

## 1.1.1

- Simplified GitHub authentication — single-page PAT entry, removed OAuth device flow complexity
- Cleaned up config flow: choose backend → enter credentials + model → done
- Fixed strings and translations to match simplified flow

## 1.1.0

- **Conversation Agent integration** — auto-installs a custom HA integration (`ghcp_conversation`) that registers as a conversation entity
- Use GitHub Copilot models (via GitHub Models API) or Azure AI endpoints as an Assist conversation agent
- Full entity control: turn on lights, query sensors, trigger automations — all through natural language
- Supports tool calling (function calling) for reliable HA actions
- Config flow UI: Settings → Integrations → Add → "GitHub Copilot Conversation"
- Two backend options: GitHub Models (PAT with `models:read` scope) or Azure AI (custom endpoint + key)
- Curated model list: GPT-4.1, GPT-5, Llama 4, Mistral Large, Grok 3, DeepSeek R1, and more
- Custom system prompts, temperature, and max token controls per conversation agent
- Subentry support: create multiple conversation agents with different prompts/models
- New config option: `enable_conversation_agent` (default: true) to control auto-install
- Integration auto-updates when the add-on updates (version-checked, only copies when changed)

## 1.0.9

- **Node-RED SSH integration** — connect to a remote Node-RED server and let Copilot edit flows
- Auto-generate SSH key pair on first run (persistent across restarts)
- SSH config with `nodered` host alias for easy access
- Copilot instructions include Node-RED Admin API usage, file locations, and best practices
- New aliases: `nodered` (SSH), `nr-flows` (fetch flows), `ssh-key` (show public key)
- Graceful handling when SSH not yet authorized (shows public key in logs with setup instructions)
- New config options: `nodered_host`, `nodered_port`, `nodered_user`, `nodered_path`

## 1.0.8

- Allow HA Core restarts — container survives independently (managed by Supervisor, not Core)
- Removed curl wrapper and hard restart block
- Updated instructions: Copilot now knows the session persists during Core restarts
- Added restart procedure: validate config → warn user about temp disconnect → restart → continue working
- Documented that ingress shows "Connection lost" during restart but auto-reconnects
- Copilot can now edit files in the background while Core restarts

## 1.0.7

- **HARD BLOCK on HA Core restart** — curl wrapper intercepts and blocks any call to `supervisor/core/restart` or `supervisor/core/stop`
- Strengthened instructions from "warn first" to absolute "NEVER restart" rule
- Instructions now tell Copilot to direct users to restart from HA UI instead
- Added `ha-restart` helper script that explains why restart is blocked

## 1.0.6

- Add critical HA restart safety instructions to copilot-instructions.md
- Copilot now knows restarting HA Core kills its own container/session
- Instructions teach Copilot to use reload APIs instead of full restarts
- Added reload commands for automations, scripts, scenes, and full YAML reload
- Added config validation command
- Clarified that /homeassistant files ARE the live config (no SCP needed)

## 1.0.5

- Add HA-specific `copilot-instructions.md` auto-generated at `/homeassistant/.github/`
- Copilot now has full context on HA path mappings, config files, MCP usage, YAML best practices, and security rules

## 1.0.4

- Fix 502 Bad Gateway: Switch from dynamic `ingress_port: 0` to fixed port `7681`
- Remove malformed theme option from ttyd (was using invalid single-quote JSON)
- Add `--ping-interval 30` for WebSocket keepalive through HA ingress proxy
- Add `--max-clients 5` safety limit
- Remove `-i 0.0.0.0` explicit bind (let ttyd use default)
- Install `procps` for healthcheck `pgrep` command

## 1.0.3

- Fix: Explicit chmod +x in Dockerfile for s6 run script (Windows Docker builds strip execute bit)

## 1.0.2

- Fix executable permission on s6 service script (Permission denied on startup)

## 1.0.1

- Fix repository URLs to match GitHub remote

## 1.0.0

- Initial release
- GitHub Copilot CLI (standalone binary) in web terminal via ttyd + tmux
- Interactive OAuth and PAT authentication
- Home Assistant MCP integration for entity/service control
- Persistent sessions across browser refreshes
- Auto-update on startup
- Multi-architecture support (amd64, aarch64)
- Configurable model selection, font size, scrollback, and auto-approve
