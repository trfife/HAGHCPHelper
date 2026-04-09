# 06 — MCP Servers, Tools, Skills & Extensions for Home Assistant + Copilot CLI

Created: **2026-07-18**

This document catalogs every MCP server, tool, skill, and extension that Copilot CLI would need (or benefit from) to fully understand and manage a Home Assistant installation. Organized by priority tier.

---

## Table of Contents

1. [Tier 1 — Already Configured / Built-in](#tier-1--already-configured--built-in)
2. [Tier 2 — High-Value MCP Servers to Add](#tier-2--high-value-mcp-servers-to-add)
3. [Tier 3 — Useful Reference MCP Servers](#tier-3--useful-reference-mcp-servers)
4. [Tier 4 — Community HA MCP Servers](#tier-4--community-ha-mcp-servers)
5. [Tier 5 — Skills & Instructions Files](#tier-5--skills--instructions-files)
6. [Tier 6 — Nice-to-Have / Future](#tier-6--nice-to-have--future)
7. [Home Assistant APIs — Full Reference](#home-assistant-apis--full-reference)
8. [What the Add-on Already Generates](#what-the-add-on-already-generates)
9. [Recommendations](#recommendations)

---

## Tier 1 — Already Configured / Built-in

These are set up by the `copilot-cli` add-on's `ttyd/run` script at boot time.

### 1.1 Home Assistant MCP Server (Official)

- **Endpoint:** `http://supervisor/core/api/mcp`
- **Transport:** Streamable HTTP
- **Auth:** `Bearer ${SUPERVISOR_TOKEN}` (auto-injected by Supervisor)
- **Config location:** `/data/copilot-persist/mcp.json`

**Supported MCP features:**

| Feature        | Status |
|----------------|--------|
| Tools          | ✅ Yes |
| Prompts        | ✅ Yes |
| Resources      | ❌ No  |
| Sampling       | ❌ No  |
| Notifications  | ❌ No  |

**Exposed tools (via Assist API):**

The HA MCP Server exposes the built-in Assist API tools to external LLM clients. These are the same tools that the built-in conversation agent has access to, which means the CLI can:

- Query entity states (all domains)
- Call any HA service (`light.turn_on`, `climate.set_temperature`, `lock.lock`, etc.)
- List entities, filter by domain
- Get entity history
- List automations and their states
- Get error logs
- Handle intents (the same ones built-in Assist handles)

**Key limitation:** The Assist API is equivalent to what the built-in conversation agent can do. It does NOT expose administrative tasks (installing integrations, managing users, changing core config). For admin tasks, CLI must use the REST/WebSocket API directly or edit YAML files.

**Client configuration for stdio-only tools:** If Copilot CLI can only speak stdio (not HTTP), you need `mcp-proxy` to bridge:
```bash
npx mcp-proxy --transport http --url http://supervisor/core/api/mcp \
  --header "Authorization: Bearer ${SUPERVISOR_TOKEN}"
```

### 1.2 Copilot Instructions (`copilot-instructions.md`)

Generated at `/homeassistant/.github/copilot-instructions.md` by the add-on. Contains:

- Path mapping table (`/homeassistant` = HA config dir)
- Key configuration files reference
- MCP usage patterns and examples
- YAML editing best practices
- Reload vs restart guidance with exact curl commands
- Security rules (never display secrets/tokens)
- Node-RED integration (if configured)

### 1.3 Filesystem Access (Direct)

The add-on mounts these paths:

| Path             | Description           | Access     |
|------------------|-----------------------|------------|
| `/homeassistant` | HA config dir         | read-write |
| `/share`         | Shared folder         | read-write |
| `/media`         | Media files           | read-only  |
| `/ssl`           | SSL certificates      | read-only  |

CLI already has direct filesystem access — no MCP server needed for file operations.

---

## Tier 2 — High-Value MCP Servers to Add

These would significantly expand what CLI can do with HA.

### 2.1 Filesystem MCP Server (Official Reference)

- **Repo:** `@modelcontextprotocol/server-filesystem`
- **Why:** While CLI has direct file access, the Filesystem MCP server provides structured tools (read, write, search, list directory) that are more predictable for the LLM than raw shell commands.
- **Priority:** Medium — CLI already has shell access, but structured tools reduce errors.

### 2.2 Git MCP Server (Official Reference)

- **Repo:** `@modelcontextprotocol/server-git`
- **Why:** Track changes to HA configuration files in git. Enables rollback of bad config changes, diff review before applying changes, and version history.
- **Priority:** High — git-backed HA config is a best practice.

### 2.3 Memory / Knowledge Graph MCP Server (Official Reference)

- **Repo:** `@modelcontextprotocol/server-memory`
- **Why:** Persistent knowledge graph for storing learned facts about the user's HA setup: which automations exist, what patterns work, device quirks, user preferences. This directly supports the learning engine from `03-hybrid-routing-and-learning-engine.md`.
- **Priority:** High — essential for the learning/promotion loop.

### 2.4 Sequential Thinking MCP Server (Official Reference)

- **Repo:** `@modelcontextprotocol/server-sequentialthinking`
- **Why:** Structured reasoning for complex multi-step HA tasks (debugging automation chains, planning config changes that affect multiple files, analyzing entity relationships).
- **Priority:** Medium — helps with complex tasks but not needed for simple ones.

### 2.5 Fetch MCP Server (Official Reference)

- **Repo:** `@modelcontextprotocol/server-fetch`
- **Why:** Fetch external resources: HA integration docs, community forums, HACS repository info, device manufacturer APIs. Useful when CLI needs to look up how an integration works.
- **Priority:** Medium — useful for research tasks.

### 2.6 Playwright MCP Server (Microsoft Official)

- **Repo:** `github.com/microsoft/playwright-mcp`
- **Why:** Browser automation for interacting with the HA frontend, HACS UI operations, testing dashboard layouts, capturing screenshots of dashboards. Also useful for interacting with any web-based HA integration setup that requires a browser.
- **Priority:** Low-Medium — mainly useful for testing and screenshot capture.

---

## Tier 3 — Useful Reference MCP Servers

### 3.1 Time MCP Server (Official Reference)

- **Repo:** `@modelcontextprotocol/server-time`
- **Why:** Accurate time and timezone handling for debugging time-based automations, sunset/sunrise triggers, scheduling.
- **Priority:** Low — HA already handles time internally.

### 3.2 Azure MCP Server (Microsoft Official)

- **Repo:** `github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server`
- **Why:** If the hybrid routing architecture uses Azure for fast classification/responses, this MCP server connects to Azure services (Cosmos DB, Storage, Azure CLI).
- **Priority:** Future — only relevant when Azure routing is implemented.

### 3.3 GitHub MCP Server (Official via GitLab/GitHub integrations)

- **Why:** Access GitHub repos for looking up integration source code, filing issues, checking HACS repositories.
- **Priority:** Low — CLI already has `gh` CLI available in the container.

---

## Tier 4 — Community HA MCP Servers

Two notable community MCP servers exist specifically for Home Assistant.

### 4.1 `tevonsb/homeassistant-mcp` (564 ⭐)

- **Repo:** `github.com/tevonsb/homeassistant-mcp`
- **Language:** TypeScript
- **Transport:** stdio + HTTP (port 3000)
- **Features:**
  - Device control (lights, climate, covers, switches, media players, fans, locks, vacuums, cameras)
  - Add-on management (list, install, uninstall, start/stop/restart)
  - HACS package management (integrations, themes, scripts, AppDaemon, NetDaemon)
  - Automation management (create, edit, duplicate, enable/disable, trigger)
  - Real-time SSE updates (state changes, automation triggers)
  - Area/floor-based device grouping
  - Historical data access
  - WebSocket support for real-time updates
- **Auth:** Long-lived access token + WebSocket URL
- **Why relevant:** This is the most feature-complete community HA MCP server. It covers admin tasks (add-on management, HACS) that the official HA MCP Server does NOT expose. Could be added alongside the official server for admin operations.
- **Priority:** High consideration — fills the admin-task gap.

### 4.2 `voska/hass-mcp` (285 ⭐)

- **Repo:** `github.com/voska/hass-mcp`
- **Language:** Python (FastMCP)
- **Transport:** stdio (Docker or uvx)
- **Features:**
  - `get_version` — HA version
  - `get_entity` — entity state with field filtering
  - `entity_action` — turn on/off/toggle
  - `list_entities` — domain filtering + search
  - `search_entities_tool` — entity search
  - `domain_summary_tool` — domain-level summaries
  - `list_automations` — all automations
  - `call_service_tool` — any HA service call
  - `restart_ha` — restart Home Assistant
  - `get_history` — entity state history
  - `get_error_log` — HA error log
  - **Prompts:** `create_automation`, `debug_automation`, `troubleshoot_entity`, `routine_optimizer`, `automation_health_check`, `entity_naming_consistency`, `dashboard_layout_generator`
  - **Resources:** `hass://entities/{id}`, `hass://entities`, `hass://entities/domain/{domain}`, `hass://search/{query}/{limit}`
- **Why relevant:** Lighter weight than tevonsb's. Has excellent guided conversation prompts (automation debugging, routine optimization, health checks). The prompts are particularly valuable for the CLI's expert mode.
- **Priority:** Medium — good prompts library to draw inspiration from.

### 4.3 `coding-sailor/mcp-server-hc3` (Fibaro)

- **Why:** Only relevant if the user has Fibaro Home Center 3 hardware.
- **Priority:** Skip — HA already integrates Fibaro natively.

### 4.4 `Yeelight/yeelight-iot-mcp` (Yeelight Official)

- **Why:** Direct smart device control. HA already integrates Yeelight.
- **Priority:** Skip — redundant with HA integration.

### 4.5 `ThinQ Connect` (LG Official)

- **Repo:** `github.com/thinq-connect/thinqconnect-mcp`
- **Why:** LG smart appliance control. HA already integrates LG ThinQ.
- **Priority:** Skip — redundant with HA integration.

### 4.6 `ThingsBoard MCP` (IoT Platform)

- **Repo:** `github.com/thingsboard/thingsboard-mcp`
- **Why:** Only if the user runs ThingsBoard alongside HA for IoT device management.
- **Priority:** Niche.

---

## Tier 5 — Skills & Instructions Files

These are not MCP servers but Copilot CLI customization files that help the CLI understand HA better.

### 5.1 Path-Specific `.instructions.md` Files

Create domain-specific instruction files to keep context short and targeted:

```
/homeassistant/.github/instructions/
├── automations.instructions.md   # Rules for editing automations.yaml
├── dashboards.instructions.md    # Lovelace/dashboard editing rules
├── integrations.instructions.md  # How to add/configure integrations
├── nodered.instructions.md       # Node-RED flow editing patterns
└── debugging.instructions.md     # Troubleshooting procedures
```

Each file applies only when CLI is working on files matching its `applyTo` glob pattern.

### 5.2 `AGENTS.md` (Agent Modes)

Define specialized agent modes that activate different tool sets:

```markdown
# HA Device Controller
- Focus: entity control, service calls, state queries
- Tools: HA MCP Server only
- Instructions: minimal, action-oriented

# HA Config Editor
- Focus: YAML editing, validation, reload
- Tools: Filesystem + HA MCP (for validation)
- Instructions: YAML best practices, reload commands

# HA Automation Builder
- Focus: creating/debugging automations
- Tools: HA MCP + Sequential Thinking
- Instructions: trigger types, condition syntax, action patterns

# HA Diagnostics Expert
- Focus: troubleshooting, log analysis, entity debugging
- Tools: HA MCP + Memory (for known issues)
- Instructions: common failure patterns, debug procedures
```

### 5.3 Copilot Memory

Enable Copilot Memory to persist facts across sessions:
- Which automations the user has
- Known device quirks
- User's preferred naming conventions
- Previous troubleshooting results
- Configuration patterns that work

---

## Tier 6 — Nice-to-Have / Future

### 6.1 n8n MCP Server

- **Repo:** `github.com/gomakers-ai/mcp-n8n`
- **Why:** If the user uses n8n workflow automation alongside HA.
- **Priority:** Niche.

### 6.2 MQTT MCP Server (none exists yet)

- **Gap:** No MCP server exists for direct MQTT interaction. HA handles MQTT through its integration, but a dedicated MQTT MCP server would let CLI publish/subscribe to MQTT topics directly for debugging.
- **Workaround:** Use HA MCP to call MQTT services, or shell into `mosquitto_pub`/`mosquitto_sub`.

### 6.3 Zigbee/Z-Wave MCP Server (none exists)

- **Gap:** No MCP server for direct Zigbee2MQTT or Z-Wave JS interaction. HA handles these through integrations.
- **Workaround:** Use HA MCP to query device states, or access Zigbee2MQTT's web UI via Playwright MCP.

### 6.4 ESPHome MCP Server (none exists)

- **Gap:** ESPHome device configuration and OTA updates. Currently done through ESPHome's web UI or CLI.
- **Workaround:** SSH or file access to ESPHome config directory, or ESPHome add-on API.

### 6.5 Docker/Container MCP Server

- **Repo:** `github.com/ckreiling/mcp-server-docker`
- **Why:** Manage Docker containers if HA add-ons need debugging at the container level.
- **Priority:** Low.

---

## Home Assistant APIs — Full Reference

This section catalogs every HA API surface that CLI might need to interact with.

### REST API (`/api/...`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/` | GET | Check API running, get message |
| `/api/config` | GET | Current HA configuration |
| `/api/components` | GET | All loaded components |
| `/api/events` | GET | List all event listeners |
| `/api/services` | GET | List all available services |
| `/api/history/period/<timestamp>` | GET | State history for a time period |
| `/api/logbook/<timestamp>` | GET | Logbook entries |
| `/api/states` | GET | All current entity states |
| `/api/states/<entity_id>` | GET | Single entity state |
| `/api/states/<entity_id>` | POST | Set entity state |
| `/api/error_log` | GET | Error log contents |
| `/api/camera_proxy/<entity_id>` | GET | Camera snapshot |
| `/api/calendars` | GET | List calendars |
| `/api/calendars/<entity_id>` | GET | Calendar events |
| `/api/events/<event_type>` | POST | Fire an event |
| `/api/services/<domain>/<service>` | POST | Call a service |
| `/api/template` | POST | Render a Jinja2 template |
| `/api/config/core/check_config` | POST | Validate config |
| `/api/intent/handle` | POST | Handle an intent |
| `/api/mcp` | POST | MCP Server endpoint (Streamable HTTP) |

**Auth:** `Authorization: Bearer <long_lived_access_token>` or `Bearer ${SUPERVISOR_TOKEN}`

### WebSocket API (`/api/websocket`)

| Command Type | Purpose |
|-------------|---------|
| `auth` | Authenticate with access token |
| `subscribe_events` | Subscribe to event bus (all or filtered) |
| `unsubscribe_events` | Unsubscribe from events |
| `subscribe_trigger` | Subscribe to automation-style triggers |
| `fire_event` | Fire an event on the event bus |
| `call_service` | Call a service action (with `return_response` support) |
| `get_states` | Dump all current entity states |
| `get_config` | Dump current HA configuration |
| `get_services` | Dump all available services |
| `get_panels` | List registered UI panels |
| `ping` / `pong` | Connection heartbeat |
| `validate_config` | Validate trigger/condition/action configs |
| `extract_from_target` | Resolve targets (entities, devices, areas, labels) |
| `get_triggers_for_target` | Get applicable triggers for entities |
| `get_conditions_for_target` | Get applicable conditions for entities |
| `get_services_for_target` | Get applicable services for entities |
| `config/entity_registry/list_for_display` | Lightweight entity list (optimized) |
| `homeassistant/expose_entity/list` | List entity exposure per assistant |
| `homeassistant/expose_entity` | Expose/unexpose entities to assistants |

**Key advantage of WebSocket over REST:** Real-time event subscriptions, trigger subscriptions, and bidirectional communication.

### LLM API (Internal — `homeassistant.helpers.llm`)

The framework for exposing tools to LLMs:

- **Built-in Assist API:** Exposes intent-based entity control (same as voice assistants). Registered automatically.
- **Custom LLM APIs:** Integrations can register their own `llm.API` subclass with custom `Tool` objects. Each tool has `name`, `description`, `parameters` (voluptuous schema), and `async_call()`.
- **Architecture:** `ChatLog.async_provide_llm_data()` fetches tools from selected API → passed to LLM → LLM calls tools → results fed back → loop up to 10 iterations.

### Supervisor API (Add-on specific)

Available inside add-on containers via `http://supervisor/...`:

| Endpoint | Purpose |
|----------|---------|
| `http://supervisor/core/api/...` | Proxy to HA Core REST API |
| `http://supervisor/core/restart` | Restart HA Core |
| `http://supervisor/addons` | List add-ons |
| `http://supervisor/addons/<slug>/start` | Start an add-on |
| `http://supervisor/addons/<slug>/stop` | Stop an add-on |
| `http://supervisor/addons/<slug>/restart` | Restart an add-on |
| `http://supervisor/addons/<slug>/info` | Add-on info |
| `http://supervisor/host/info` | Host system info |
| `http://supervisor/os/info` | OS info |

---

## What the Add-on Already Generates

At startup, the `ttyd/run` script creates:

### 1. MCP Configuration (`/data/copilot-persist/mcp.json`)
```json
{
  "mcpServers": {
    "homeassistant": {
      "type": "http",
      "url": "http://supervisor/core/api/mcp",
      "headers": {
        "Authorization": "Bearer ${SUPERVISOR_TOKEN}"
      }
    }
  }
}
```

### 2. Copilot Instructions (`/homeassistant/.github/copilot-instructions.md`)
- Path mapping, key files, MCP usage patterns
- YAML editing rules, reload commands
- Security rules (never show secrets)
- Node-RED section (if SSH configured)

### 3. SSH Keys (`/data/copilot-persist/.ssh/`)
- Auto-generated `ed25519` key pair for Node-RED and other remote connections

---

## Recommendations

### Immediate (add to `ttyd/run` startup)

1. **Add Memory MCP server** to `mcp.json` — enables persistent knowledge across sessions. Use `@modelcontextprotocol/server-memory` with storage at `/data/copilot-persist/memory/`.

2. **Add path-specific instruction files** — create at least `automations.instructions.md` and `debugging.instructions.md` in `/homeassistant/.github/instructions/`.

3. **Add `AGENTS.md`** at `/homeassistant/.github/AGENTS.md` with the agent modes described in Tier 5.

### Short-term (next version)

4. **Evaluate `tevonsb/homeassistant-mcp`** for admin tasks — the add-on/HACS management tools fill a gap the official MCP server doesn't cover. Could run as a sidecar service.

5. **Add Git MCP server** — initialize and maintain a git repo of `/homeassistant` config for change tracking and rollback.

### Medium-term (architecture phase)

6. **Sequential Thinking server** for complex multi-step debugging workflows.

7. **Fetch server** for looking up integration documentation on the fly.

### Not recommended

- Adding device-specific MCP servers (Yeelight, ThinQ, Fibaro, etc.) — HA already integrates these. Adding separate MCP servers creates redundancy and confusion about which path to use.
- Adding Playwright MCP in the container — browser automation is heavy and the add-on runs in a constrained environment. Better to use HA's native APIs.

---

## Summary Matrix

| MCP Server / Tool | Category | Priority | Already Have? | Gap Filled |
|---|---|---|---|---|
| HA MCP Server (official) | Core | Critical | ✅ Yes | Entity control, services, history |
| copilot-instructions.md | Skill | Critical | ✅ Yes | Context, path mapping, rules |
| Filesystem access | Core | Critical | ✅ Yes (direct) | File editing |
| Memory (knowledge graph) | Reference | High | ❌ No | Persistent learning, user facts |
| Git | Reference | High | ❌ No | Config versioning, rollback |
| tevonsb/homeassistant-mcp | Community | High | ❌ No | Admin: add-ons, HACS, automations |
| Path-specific instructions | Skill | High | ❌ No | Targeted context per task type |
| AGENTS.md | Skill | Medium | ❌ No | Specialized agent modes |
| Sequential Thinking | Reference | Medium | ❌ No | Complex multi-step reasoning |
| Fetch | Reference | Medium | ❌ No | External docs lookup |
| voska/hass-mcp | Community | Medium | ❌ No | Guided prompts library |
| Time | Reference | Low | ❌ No | Timezone handling |
| Playwright | Official | Low | ❌ No | Browser automation |
| Docker | Community | Low | ❌ No | Container debugging |
| Azure | Official | Future | ❌ No | Azure routing integration |
