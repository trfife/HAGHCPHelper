# GitHub Copilot CLI — Home Assistant Add-on

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Run [GitHub Copilot CLI](https://github.com/github/copilot-cli) — GitHub's agentic AI coding assistant — directly in your Home Assistant sidebar with a persistent web terminal.

## Features

- **Conversation Agent** — Use GitHub Copilot models as an Assist conversation agent to control devices and query states via voice or text
- **Web Terminal** — Access Copilot CLI through your browser via the HA sidebar (ingress)
- **Config Access** — Read and write Home Assistant configuration files (YAML, automations, scripts)
- **HA MCP Integration** — Copilot can query entities, call services, and control your smart home
- **Session Persistence** — tmux keeps your session alive across page refreshes and disconnects
- **Multiple Models** — Choose between Claude Sonnet 4.5, Claude Sonnet 4, GPT-5, or let Copilot decide
- **GitHub Integration** — Create PRs, manage issues, commit changes — all from your HA dashboard
- **Lightweight** — Standalone binary, no Node.js runtime required
- **Node-RED Integration** — SSH into a remote Node-RED server to edit flows and settings
- **Multi-Architecture** — Supports amd64 and aarch64 (Raspberry Pi 4/5)

## Installation

[![Add Repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ftrfife%2FHAGHCPHelper)

Or manually:

1. Go to **Settings → Add-ons → Add-on Store**
2. Click the **⋮** menu (top right) → **Repositories**
3. Add: `https://github.com/trfife/HAGHCPHelper`
4. Find **GitHub Copilot CLI** in the store and click **Install**
5. Start the add-on
6. Click **Open Web UI** or find **Copilot CLI** in your sidebar

## First-Time Setup

1. Open Copilot CLI from the sidebar
2. You'll be prompted to authenticate — type `/login` and follow the URL
3. Complete GitHub authentication in your browser
4. Paste the auth code back into the terminal
5. Your credentials are stored persistently and survive restarts

**Alternative:** Set a GitHub Personal Access Token (PAT) with the "Copilot Requests" permission in the add-on configuration.

## Requirements

- Home Assistant OS or Supervised installation
- amd64 or aarch64 architecture
- Active [GitHub Copilot subscription](https://github.com/features/copilot/plans)

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `github_token` | *(empty)* | Optional PAT. Leave empty to use `/login` |
| `model` | `default` | AI model: `default`, `claude-sonnet-4.5`, `claude-sonnet-4`, `gpt-5` |
| `session_name` | `copilot` | tmux session name |
| `tmux_history_limit` | `50000` | Lines of scrollback history |
| `auto_approve` | `false` | Auto-approve all tool use (use with caution) |
| `enable_ha_mcp` | `true` | Enable Home Assistant MCP integration |
| `terminal_font_size` | `14` | Font size (10–24) |
| `session_persistence` | `true` | Use tmux for persistent sessions |
| `auto_update` | `true` | Auto-update Copilot CLI on startup |
| `nodered_host` | *(empty)* | Node-RED server IP/hostname (enables SSH integration) |
| `nodered_port` | `22` | Node-RED SSH port |
| `nodered_user` | `root` | Node-RED SSH user |
| `nodered_path` | `/data` | Node-RED data directory path |
| `enable_conversation_agent` | `true` | Auto-install conversation agent integration |

## How It Works

```
Browser → HA Ingress → ttyd (web terminal) → tmux session → Copilot CLI
```

- **ttyd** serves a web terminal over WebSocket with auto-reconnect
- **tmux** keeps the session alive even when you navigate away
- **s6-overlay** manages service lifecycle
- **/data** volume persists auth and config across container restarts

## Example Usage

```bash
# Start interactive session (happens automatically)
copilot

# Edit HA config
"Add a new automation that turns on the porch light at sunset"

# Debug issues
"Check my configuration.yaml for errors"

# Query entities (with MCP enabled)
"What's the temperature in the living room?"

# Control devices
"Turn off all lights in the bedroom"

# Create GitHub PRs from config changes
"Commit these automation changes and create a PR"
```

## License

MIT
