# GitHub Copilot CLI — Documentation

## Authentication

### Interactive Login (Recommended)

On first launch, Copilot CLI will prompt you to authenticate:

1. Open the terminal from the HA sidebar
2. The `copilot` command starts automatically
3. Type `/login` and press Enter
4. A URL and device code will appear
5. Open the URL in your browser (you may need to zoom out if it wraps)
6. Enter the device code and authorize
7. Your credentials are saved in persistent storage

**Tip:** If the URL wraps across lines, hold `Ctrl+Shift` while selecting with your mouse to copy it.

### Personal Access Token (PAT)

1. Visit https://github.com/settings/personal-access-tokens/new
2. Under "Permissions," add **Copilot Requests**
3. Generate your token
4. Paste it into the `github_token` field in the add-on configuration
5. Restart the add-on

## Home Assistant MCP Integration

When `enable_ha_mcp` is enabled (default), Copilot can interact with your Home Assistant instance:

- **Query entities:** "What's the temperature in the living room?"
- **Control devices:** "Turn off all lights in the bedroom"
- **List services:** "What services are available for climate control?"
- **Debug automations:** "Why didn't my morning routine trigger?"

The MCP server is automatically configured using the Supervisor API token.

## Terminal Shortcuts

| Shortcut | Action |
|----------|--------|
| `c` | Alias for `copilot` |
| `cc` | Alias for `copilot --continue` |
| `ha-config` | Navigate to `/homeassistant` config directory |
| `ha-logs` | View Home Assistant logs |
| `nodered` | SSH into Node-RED server |
| `nr-flows` | Fetch Node-RED flows as JSON |
| `ssh-key` | Show the add-on's SSH public key |

## Session Persistence (tmux)

When `session_persistence` is enabled (default), the add-on uses tmux:

- Your session survives browser refreshes and disconnects
- Long-running Copilot tasks continue in the background
- Mouse wheel scrolling works (auto-enters copy mode)

### tmux Commands

| Shortcut | Action |
|----------|--------|
| `Ctrl+b d` | Detach from session (keeps it running) |
| `Ctrl+b [` | Enter scroll/copy mode |
| Mouse wheel | Scroll up/down |
| `q` | Exit scroll/copy mode |

### Copy and Paste in tmux

Since tmux captures mouse events:

| Action | Shortcut |
|--------|----------|
| Copy | Hold `Ctrl+Shift` while selecting text |
| Paste | `Shift+Insert` or `Ctrl+Shift+V` |

## File Locations

| Path | Description | Access |
|------|-------------|--------|
| `/homeassistant` | HA configuration directory | read-write |
| `/share` | Shared folder | read-write |
| `/media` | Media files | read-only |
| `/ssl` | SSL certificates | read-only |

## Copilot CLI Commands

Inside the Copilot CLI interactive session:

| Command | Description |
|---------|-------------|
| `/login` | Authenticate with GitHub |
| `/model` | Change the AI model |
| `/mcp` | View configured MCP servers |
| `/compact` | Compress conversation context |
| `/context` | Show token usage breakdown |
| `/feedback` | Submit feedback to GitHub |
| `/experimental` | Enable experimental features |

## Node-RED Integration

Copilot can connect to a remote Node-RED server via SSH to view and edit flows.

### Setup

1. Configure the Node-RED connection in the add-on settings:
   - **Host:** IP address or hostname of your Node-RED server
   - **Port:** SSH port (default: 22)
   - **User:** SSH user (default: root)
   - **Data Path:** Node-RED data directory (default: /data)
2. Start (or restart) the add-on
3. Check the add-on logs — if SSH isn't authorized yet, you'll see the public key to add
4. Copy the public key and add it to your Node-RED server:
   ```bash
   # On the Node-RED server:
   echo '<paste-public-key-here>' >> ~/.ssh/authorized_keys
   ```
5. Restart the add-on — the SSH connection should now verify successfully

### Aliases

| Alias | Action |
|-------|--------|
| `nodered` | SSH into the Node-RED server |
| `nr-flows` | Fetch and display all Node-RED flows (JSON) |
| `ssh-key` | Display the add-on's SSH public key |

### What Copilot Can Do

Once connected, Copilot can:

- View and modify Node-RED flows via the Admin API
- Edit `settings.js` and `package.json`
- Install npm packages on the Node-RED server
- Restart Node-RED after changes
- Back up and restore flows

## Auto-Approve Mode

When `auto_approve` is enabled, Copilot executes commands without asking. This is convenient but risky — Copilot has full access to your HA configuration files.

**Recommended:** Leave disabled and approve commands individually, especially when first getting started.

## Troubleshooting

### Authentication issues

1. Type `/login` to restart the auth flow
2. Ensure your GitHub account has an active Copilot subscription
3. If using a PAT, verify it has the "Copilot Requests" permission

### Terminal not loading

1. Check that the add-on is running (green indicator)
2. Try refreshing the page
3. Check add-on logs for ttyd errors

### Session not persisting

1. Ensure `session_persistence` is true
2. The session auto-attaches on reconnect

### MCP not working

1. Verify `enable_ha_mcp` is true
2. Check add-on logs for MCP configuration messages
3. Restart the add-on after configuration changes
