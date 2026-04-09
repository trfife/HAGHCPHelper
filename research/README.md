# Research Folder

Created: **2026-04-08**

This folder consolidates the research performed for the `ghcp_conversation` Home Assistant integration and the bundled `copilot-cli` add-on. It is intentionally broken out by topic so future work can find the right answers quickly instead of re-doing discovery.

---

## Quick Conclusions

- **Home Assistant Assist currently uses a one-shot request/response pipeline.** One turn comes in, one `ConversationResult` goes back out.
- In `copilot_cli` mode, Home Assistant talks to `copilot --acp` over a **local ACP socket** (default `localhost:3000`), not by spawning a shell command for each request.
- The cleanest place to insert **Azure-first routing** is in `custom_components/ghcp_conversation/entity.py`, before `_async_handle_acp()`.
- The best overall speed architecture is:
  - `HA local handling`
  - then `deterministic fast intent/rule engine + Azure in parallel`
  - then `Copilot CLI expert fallback`
- The best UX for slow work is **quick acknowledgement + background follow-up**, not trying to force two synchronous answers through the current Assist API path.
- The strongest verified Copilot CLI optimization levers are:
  - short repo-wide instructions
  - path-specific instruction files
  - `AGENTS.md`
  - MCP-first workflows
  - Copilot Memory
  - persistent session reuse

---

## Folder Contents

| File | Purpose |
|---|---|
| `01-assist-to-cli-flow.md` | End-to-end request flow from Assist to ACP to Copilot CLI |
| `02-copilot-cli-speed-research.md` | Research on making Copilot CLI faster using instructions, tools, MCP, memory, and session reuse |
| `03-hybrid-routing-and-learning-engine.md` | Recommended `HA local -> rule engine + Azure -> CLI` architecture and the learning loop |
| `04-staged-responses-and-followups.md` | Findings on multi-part answers, streaming/progress, and recommended follow-up UX |
| `05-implementation-roadmap.md` | Practical phased implementation plan, file targets, risks, and validation steps |
| `06-mcp-tools-extensions.md` | Comprehensive catalog of MCP servers, tools, skills, extensions for HA + CLI |

---

## Key Repo Files Referenced Repeatedly

### Home Assistant integration
- `custom_components/ghcp_conversation/entity.py`
- `custom_components/ghcp_conversation/acp_client.py`
- `custom_components/ghcp_conversation/api.py`
- `custom_components/ghcp_conversation/knowledge.py`
- `custom_components/ghcp_conversation/config_flow.py`
- `custom_components/ghcp_conversation/__init__.py`

### Copilot CLI add-on
- `copilot-cli/rootfs/etc/services.d/copilot-acp/run`
- `copilot-cli/rootfs/etc/services.d/ttyd/run`
- `copilot-cli/config.yaml`
- `copilot-cli/ghcp_conversation/conversation.py`

---

## Main Research Questions Answered

1. **How does Assist actually reach GitHub Copilot CLI?**
   - Answered in `01-assist-to-cli-flow.md`.

2. **Where could Azure be inserted before or alongside CLI?**
   - The best insertion point is the backend-routing layer in `entity.py`.

3. **Can the system answer quickly for common requests and only escalate when needed?**
   - Yes. The strongest recommendation is the layered router described in `03-hybrid-routing-and-learning-engine.md`.

4. **Can the system give an immediate “working on it” response and then a final answer later?**
   - Not natively in the current one-shot Assist path, but a good approximation is possible with a quick acknowledgement plus asynchronous follow-up.

5. **How can Copilot CLI be made faster?**
   - Mainly by reducing repeated exploration and repeated reasoning rather than simply changing models.

---

## Research Sources Used

### Repository source reading
The findings in this folder were based on direct inspection of the repo, especially:
- conversation entity flow in `entity.py`
- ACP protocol handling in `acp_client.py`
- add-on startup scripts in `copilot-acp/run` and `ttyd/run`
- the knowledge-store and expert escalation work already added to the repo

### GitHub documentation topics reviewed
The research also incorporated the official GitHub docs around:
- repository custom instructions
- path-specific instructions
- `AGENTS.md`
- Copilot CLI custom instruction support
- MCP support
- Copilot Memory
- customization patterns and support matrices

These docs were used to verify what Copilot CLI actually supports and which customization surfaces are most likely to produce real speed improvements.

---

## Top Recommendation

If this work moves from research into implementation, the best first milestone is:

1. add structured routing logs
2. add a minimal deterministic fast intent engine
3. insert Azure as a classifier/router before CLI fallback
4. measure hit rate and latency before adding automated rule promotion

That path provides the most value with the least risk.
