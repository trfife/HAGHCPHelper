# Assist to Copilot CLI Flow

This document traces the actual request path for this repository when a user opens **Home Assistant Assist** and sends a prompt to the `ghcp_conversation` integration.

---

## Executive Summary

When the `ghcp_conversation` conversation agent is selected and configured for the `copilot_cli` backend, the flow is:

```text
User prompt in Assist
  -> Home Assistant conversation pipeline
  -> GHCPConversationEntity._async_handle_message()
  -> _async_handle_acp()
  -> ACPClient over TCP to localhost:3000
  -> copilot --acp inside the add-on container
  -> streamed chunks buffered by the integration
  -> one final ConversationResult returned to Assist
```

Important detail:
> Home Assistant is acting as an **ACP client**. The Copilot CLI add-on is running the **ACP server**.

It is **not** spawning the `copilot` binary fresh for every prompt.

---

## Relevant Files

### Main conversation entrypoint
- `custom_components/ghcp_conversation/entity.py`

### ACP protocol client
- `custom_components/ghcp_conversation/acp_client.py`

### Add-on ACP service startup
- `copilot-cli/rootfs/etc/services.d/copilot-acp/run`

### Conversation platform shim
- `copilot-cli/ghcp_conversation/conversation.py`
- This file is only a small pass-through to the real entity setup logic.

---

## Step-by-Step Request Flow

## 1. User sends a request in Assist
A user speaks or types a request in Home Assistant Assist, for example:
- “Turn off the kitchen lights”
- “Why didn’t my automation run?”
- “Fix this YAML file”

Home Assistant routes the turn to the configured conversation agent.

---

## 2. The conversation entity receives the turn
In this repo, the main runtime entrypoint is:
- `GHCPConversationEntity._async_handle_message()` in `custom_components/ghcp_conversation/entity.py`

What it does:
- merges config from the config entry, options, and any subentry
- checks which backend is configured
- routes the request to one of two major paths:
  - **Copilot CLI ACP path**
  - **Direct GitHub Models / Azure API path**

High-level logic:

```python
if backend == BACKEND_COPILOT_CLI:
    return await self._async_handle_acp(user_input, chat_log, data)
return await self._async_handle_direct_api(user_input, chat_log, data)
```

---

## 3. If backend is `copilot_cli`, the ACP path starts
The entity calls:
- `_async_handle_acp()`

That method:
- reads the configured ACP host and port
- constructs an `ACPClient`
- opens a TCP connection to the ACP server
- initializes the ACP protocol
- resumes or creates a session
- sends the prompt
- waits for the final result

Default connection settings come from `const.py`:
- host: typically `localhost`
- port: `3000`

---

## 4. ACP connection and handshake
In `custom_components/ghcp_conversation/acp_client.py`:

### `async_connect()`
- opens a raw TCP connection
- uses `asyncio.open_connection(self._host, self._port)`

### `async_initialize()`
- sends the ACP `initialize` request
- includes client info and capabilities
- receives back agent capabilities from the Copilot CLI side

This is the point where the Home Assistant integration establishes the protocol session with the running Copilot CLI process.

---

## 5. Session resume or creation
Still in the ACP path, the entity calls:
- `ACPClient.async_ensure_session()`

That method:
- tries `session/load` if a prior `_acp_session_id` exists and the agent supports it
- otherwise falls back to `session/new`

This is how the integration preserves shared context across turns.

Important current behavior:
- session IDs are kept on the entity instance in memory
- they persist across turns while the entity stays alive
- they are not yet a full durable cross-restart session store unless explicitly persisted further

---

## 6. The actual prompt is sent to Copilot CLI
The entity then calls:
- `ACPClient.async_prompt(user_input.text)`

That sends a JSON-RPC request with:
- `method = "session/prompt"`
- the current `sessionId`
- the prompt content as text

At this point the Copilot CLI ACP server starts working on the request.

---

## 7. The CLI streams progress internally
The ACP server sends back streamed notifications such as:
- `agent_message_chunk`
- `agent_thought_chunk`
- `tool_call`
- `tool_call_update`
- permission requests

The integration currently handles these in `ACPClient._handle_notification()` and `_handle_agent_request()`.

### What is used now
- `agent_message_chunk`: appended to the response text buffer
- `agent_thought_chunk`: ignored for the final user output
- `session/request_permission`: auto-approved
- `fs/read_text_file` and `fs/write_text_file`: handled by the integration when requested by the agent

This means the CLI is already streaming partial output internally, but the integration does **not** surface those partials back to Assist yet.

---

## 8. The entity returns one final response
Once ACP signals that the turn is complete, the buffered text is joined into one final string.

Then `entity.py` does roughly this:
- add assistant content to the chat log
- create `intent.IntentResponse`
- call `response_obj.async_set_speech(content)`
- return `ConversationResult`

This is why the current user-facing behavior is a **single final answer**.

---

## Add-on Startup Chain

The Copilot CLI side is started by:
- `copilot-cli/rootfs/etc/services.d/copilot-acp/run`

That script:
- waits for the `copilot` binary to exist
- reads the configured model from `config.yaml`
- sources the environment file if present
- launches the ACP server with:

```bash
copilot --acp --port 3000 --allow-all-tools [--model ...]
```

The working directory is:
- `/homeassistant`

That matters because the CLI then sees the Home Assistant config and `.github` instruction files in the expected place.

---

## Related Startup Context: Instructions and MCP

Another key startup script is:
- `copilot-cli/rootfs/etc/services.d/ttyd/run`

This script already does useful preload work:
- writes `/homeassistant/.github/copilot-instructions.md`
- writes `mcp.json` for the Home Assistant MCP server
- sets up persistent shell context and convenience behavior

So the ACP path already benefits from:
- repo instructions
- MCP tooling
- a stable working directory

---

## The Direct API Path (for comparison)

When backend is not `copilot_cli`, the entity instead uses `_async_handle_direct_api()`.

That path:
- builds a system prompt
- provides HA LLM tool definitions
- constructs the message list from `chat_log`
- calls a `ChatCompletionClient`
- loops through tool calls if returned by the model

This is where GitHub Models / Azure direct completion happens.

This path is also the most natural place to build a hybrid router, because it already has direct API support and clean model-routing logic.

---

## Cleanest Insertion Point for Azure Before CLI

The best place to add Azure-first logic is:
- `custom_components/ghcp_conversation/entity.py`
- specifically around `_async_handle_message()` before `_async_handle_acp()` is invoked

Recommended pattern:

```text
Assist
  -> entity.py decides route
  -> fast classifier / router runs
  -> if simple and confident: answer without CLI
  -> else: call _async_handle_acp()
```

This keeps the ACP protocol layer simple and avoids complicating low-level transport logic.

---

## Key Constraints Confirmed by Research

1. **Current response path is one-shot**
   - one `ConversationResult`
   - one final `async_set_speech()`

2. **Partial streaming exists internally but is not surfaced yet**
   - the ACP side already emits chunks
   - the integration buffers them instead of sending progress updates to Assist

3. **The platform shim is not the right place for routing logic**
   - `copilot-cli/ghcp_conversation/conversation.py` is only a thin setup wrapper
   - the real logic belongs in `entity.py`

---

## Main Takeaway

If the goal is to change how requests are routed or how long-running work is surfaced, the real control points are:
- `entity.py` for routing
- `acp_client.py` for progress/stream handling
- startup scripts for environment and context preload

That is the correct foundation for any future hybrid Azure + CLI architecture.
