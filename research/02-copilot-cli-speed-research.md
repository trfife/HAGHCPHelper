# Copilot CLI Speed Research

This document captures the research on how to make GitHub Copilot CLI faster in the context of this Home Assistant add-on.

---

## Executive Summary

The biggest speed wins do **not** come from just switching models. They come from reducing repeated exploration and repeated reasoning.

For this repo, the highest-value optimization levers are:

1. **short repo-wide instructions**
2. **path-specific instruction files**
3. **`AGENTS.md` guidance**
4. **MCP-first workflows**
5. **Copilot Memory**
6. **persistent session reuse**

The repo already has a good start because the add-on writes instruction files and configures MCP on startup. The next improvement is to make the context more selective and to avoid unnecessary routing to the heavy CLI path.

---

## What Was Verified from GitHub Docs

Research into GitHub’s documentation confirmed that **Copilot CLI** supports these customization mechanisms:

- `.github/copilot-instructions.md`
- `.github/instructions/**/*.instructions.md`
- `AGENTS.md`
- MCP servers
- Copilot Memory

That means the main, verified route to speeding up Copilot CLI is to give it:
- better scoped instructions
- the right tools preconfigured
- persistent knowledge about the repo

Notably, the strongest documented support for the CLI path is around **instructions, agent instructions, MCP, and memory**.

---

## What the Repo Already Does Well

### 1. Startup already preloads repo context
The add-on startup script in:
- `copilot-cli/rootfs/etc/services.d/ttyd/run`

already writes:
- `/homeassistant/.github/copilot-instructions.md`

This gives the CLI immediate repo/context guidance without needing the user to repeat it every turn.

### 2. Startup already preloads MCP
The same script writes `mcp.json` for the Home Assistant MCP server using the Supervisor token.

That means the CLI can already access live Home Assistant tools instead of relying only on prompt text or file inspection.

### 3. The ACP service now respects the configured model
The ACP startup script in:
- `copilot-cli/rootfs/etc/services.d/copilot-acp/run`

now reads the add-on model setting and passes `--model` to `copilot --acp`.

### 4. The integration already preserves some session continuity
The ACP client in `acp_client.py` supports:
- `session/load`
- `session/new`
- `async_ensure_session()`

This reduces re-onboarding within a running session.

---

## Main Ways to Make Copilot CLI Faster

## 1. Keep repo-wide instructions short and high-signal
Repo-wide instructions are always in scope, so if they get too long they add friction to every request.

Good content for the always-on file:
- what this repo is
- key path mappings
- a handful of known-good commands
- safety rules
- when to use MCP

Bad content for the always-on file:
- long prose
- too many examples
- niche workflows that only apply occasionally
- duplicated explanations

**Recommendation:** keep `copilot-instructions.md` short and move specialized content into path-specific files.

---

## 2. Split instructions by task or path
A large monolithic instruction file makes the model carry too much context all the time.

Better structure:
- `.github/copilot-instructions.md` for general rules
- `.github/instructions/ha-yaml.instructions.md`
- `.github/instructions/integration-python.instructions.md`
- `.github/instructions/addon-shell.instructions.md`
- `.github/instructions/nodered.instructions.md`

This reduces irrelevant context loading and helps the agent move faster with less searching.

---

## 3. Add an `AGENTS.md` decision tree
An `AGENTS.md` file can reduce tool-selection churn by making the decision rules explicit.

Examples of high-value rules:
- for live Home Assistant state or control, use the `homeassistant` MCP server first
- avoid broad repo search when the path map is already known
- prefer reload APIs before restart when possible
- never expose secrets or tokens

This speeds up action selection and reduces wasted exploration.

---

## 4. Use MCP as the primary runtime data path
For Home Assistant work, MCP is usually faster and more accurate than trying to infer runtime state from files.

Examples:
- “What’s the temperature in the living room?” → MCP query
- “Turn off all lights” → MCP service call
- “List unavailable entities” → MCP listing/filter

This is already configured by the add-on. The main guidance improvement is to make the agent prefer MCP more consistently.

---

## 5. Enable Copilot Memory if available
GitHub’s documentation confirms that Copilot Memory can be used by Copilot CLI.

This is one of the best long-term ways to reduce repeated rediscovery of the repo.

Benefits:
- reduces repeated prompting
- reduces repeated explanation of repo conventions
- helps the agent remember validated patterns over time

For enterprise-managed environments, this may need to be enabled in the organization or enterprise settings.

---

## 6. Reuse the ACP session and connection where practical
The current design already resumes the ACP session across turns. That is good.

A further speed improvement would be to reduce repeated connect/init overhead by keeping more state alive where practical.

Potential improvement areas:
- less reconnect churn
- better reuse of initialized session state
- possibly reusing shared transport/session infrastructure in `hass.data`

---

## 7. Use the right default model strategy
The research found that the CLI is using CLI-style model names such as:
- `gpt-5-mini`
- `gpt-4.1`
- `claude-haiku-4.5`
- `claude-sonnet-4.6`
- `claude-opus-4.6`

The repo previously had API-style names like `openai/gpt-5-nano`, which did not match the actual CLI model list.

**Recommendation:**
- keep a small fast default such as `gpt-5-mini`
- reserve the expensive strong models for explicit escalation

---

## What Does *Not* Usually Help

### 1. Putting Azure in front of every request
If Azure does not short-circuit a request, it becomes an extra hop and adds latency.

### 2. Overly verbose instructions
Long instructions can make the model slower and less decisive.

### 3. Too many overlapping tools
If the agent has multiple ways to solve the same task and the routing is unclear, it may spend extra time deciding.

### 4. Asking for deep reasoning by default
For routine home control or status questions, extra deliberation is the opposite of what you want.

---

## Best Architecture for Speed

The strongest design discovered in the research was:

```text
HA local handling
  -> deterministic fast intent/rule engine
  -> Azure classifier/simple-answer layer
  -> Copilot CLI expert fallback
```

This keeps the strongest but slowest model out of the hot path for common requests.

---

## Repo-Specific Next Improvements

### High priority
- split the existing generated `copilot-instructions.md` into smaller scoped instruction files
- add `AGENTS.md`
- build a routing layer so simple requests do not always reach the heavy CLI path

### Medium priority
- improve session reuse
- add structured logging for repeated prompt/action patterns
- add a lightweight learning or rule-promotion pipeline

### Lower priority
- more advanced memory tuning and candidate review workflows

---

## Final Takeaway

If the goal is to make Copilot CLI feel faster, the biggest gains come from:
- reducing repeated search
- reducing repeated reasoning
- making routing and tool use obvious
- keeping the strong CLI path for the requests that actually need it

That is more valuable than simply picking a different model alone.
