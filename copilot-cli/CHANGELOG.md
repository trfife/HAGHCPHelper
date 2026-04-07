# Changelog

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
