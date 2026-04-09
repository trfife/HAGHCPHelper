# Changelog

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
