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

## Conversation Agent Integration

The add-on can automatically install a **GitHub Copilot Conversation** integration into Home Assistant. This registers a conversation entity that you can use with HA's **Assist** pipeline to control devices and query states through natural language — via voice or text.

### How It Works

```
User (voice/text via Assist)
  → HA Conversation Pipeline
    → GitHub Copilot Conversation entity
      → GitHub Models API (or Azure AI endpoint)
        ← LLM response + tool calls for entity control
    ← Speech response
  → TTS (optional voice output)
```

### Setup

1. Ensure `enable_conversation_agent` is **true** in the add-on configuration (default)
2. Start or restart the add-on — check the logs for "Conversation agent installed"
3. **Restart Home Assistant** (required on first install only)
4. Go to **Settings → Integrations → Add Integration**
5. Search for **GitHub Copilot Conversation**
6. Choose your backend:
   - **GitHub Models** — enter a GitHub PAT with the `models:read` permission
   - **Azure AI Endpoint** — enter your endpoint URL, API key, and model name
7. Select a model (or type a custom model ID)
8. The integration creates a conversation entity — assign it as your Assist agent

### Creating a GitHub PAT for GitHub Models

1. Visit https://github.com/settings/personal-access-tokens/new
2. Name it (e.g., "HA Conversation Agent")
3. Under **Permissions**, add **Models → Read**
4. Generate and copy the token

### Selecting as Assist Agent

1. Go to **Settings → Voice Assistants**
2. Edit your Assist pipeline (or create a new one)
3. Under **Conversation agent**, select **GitHub Copilot**
4. Save — you can now talk to Copilot through Assist

### Multiple Agents

You can create multiple conversation entities with different models or prompts:

1. Go to the integration's page in Settings → Integrations
2. Click **Add Subentry** → **Conversation**
3. Configure a custom name, system prompt, temperature, and HA API access
4. Each subentry creates a separate conversation entity you can assign to different pipelines

### Supported Models (GitHub Models)

| Model | Publisher | Notes |
|-------|-----------|-------|
| `openai/gpt-4.1` | OpenAI | High quality, balanced |
| `openai/gpt-4.1-mini` | OpenAI | Fast, cost-effective (default) |
| `openai/gpt-5` | OpenAI | Most capable |
| `openai/gpt-5-mini` | OpenAI | Fast next-gen |
| `meta/llama-4-scout` | Meta | Open-source |
| `meta/llama-4-maverick` | Meta | Open-source, larger |
| `mistral/mistral-large` | Mistral | Strong reasoning |
| `xai/grok-3` | xAI | Large context |
| `deepseek/deepseek-r1` | DeepSeek | Reasoning model |

You can also type any custom model ID in `publisher/model-name` format.

### Azure AI Backend

If you have an Azure AI deployment, you can use it instead of GitHub Models:

1. In the config flow, choose **Azure AI Endpoint**
2. Enter the full endpoint URL (e.g., `https://my-deployment.openai.azure.com/openai/deployments/gpt-4o`)
3. Enter your API key and model name
4. The integration uses the same OpenAI-compatible format

### Troubleshooting

#### Integration not appearing

1. Verify `enable_conversation_agent` is true in add-on config
2. Check add-on logs for "Conversation agent installed"
3. Restart Home Assistant after first install

#### Authentication errors

1. For GitHub Models: ensure your PAT has the `models:read` permission
2. For Azure AI: verify the endpoint URL and API key
3. Check the HA logs for detailed error messages

#### Agent not responding

1. Check that the conversation entity is selected as the Assist agent
2. Verify the model is available (some have restricted access)
3. Check rate limits — GitHub Models free tier allows 10-15 requests/minute
