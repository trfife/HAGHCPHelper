---
description: "Use when modifying the Dockerfile, ttyd/run, copilot-acp/run, or config.yaml for the Copilot CLI add-on. Covers container architecture, s6 services, and MCP configuration."
applyTo: ["**/copilot-cli/Dockerfile", "**/services.d/**", "**/copilot-cli/config.yaml"]
---
# Copilot CLI Add-on Rules

## Container Architecture
- Base: Debian (hassio base image)
- s6 service supervisor manages ttyd + copilot-acp services
- ttyd: web terminal on ingress port 7681
- copilot-acp: `copilot --acp --port 3000` for conversation agent

## s6 Service Scripts
- Must start with `#!/usr/bin/with-contenv bashio`
- Use `bashio::config 'key'` to read add-on options
- Use `bashio::log.info/warning/error` for structured logging
- Services auto-restart on crash (s6 behavior)

## MCP Configuration
- Written to `/data/copilot-persist/mcp.json` at startup
- HA MCP: `http://supervisor/core/api/mcp` with `${SUPERVISOR_TOKEN}`
- Memory MCP: `@modelcontextprotocol/server-memory` via npx
- Config is regenerated on every startup (not persistent)

## File Generation in ttyd/run
- `copilot-instructions.md` → `/homeassistant/.github/`
- `automations.instructions.md` → `/homeassistant/.github/instructions/`
- `debugging.instructions.md` → `/homeassistant/.github/instructions/`
- `AGENTS.md` → `/homeassistant/.github/`
- `.gitignore` + git init → `/homeassistant/`
- All use heredocs (`<< 'EOF'`) — single-quoted to prevent variable expansion

## config.yaml Schema
- `schema` section defines option types for HA UI
- `options` section defines defaults
- Use `"password?"` for optional passwords, `"str?"` for optional strings
- Model list is hardcoded in schema — update when new models release
