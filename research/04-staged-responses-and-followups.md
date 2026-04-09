# Staged Responses and Follow-Ups

This document captures the research on whether the Home Assistant Assist flow in this repo can return more than one answer for a single user prompt, for example:

1. “That’s going to take a minute…”
2. followed by the final answer later

---

## Executive Summary

### Current state
The integration currently behaves as a **one-shot response pipeline**.

For each Assist turn:
- one request comes in
- one `ConversationResult` is returned
- one `IntentResponse.async_set_speech(content)` is used

That means the current implementation does **not** natively return two user-visible answers within the same Assist turn.

### However
The ACP layer already receives partial streamed chunks from Copilot CLI internally. The integration simply buffers them today instead of surfacing progress to the user.

So there are two realistic options:

1. **Quick acknowledgement + asynchronous follow-up** (recommended near-term)
2. **Investigate true streaming/progress support in HA conversation surfaces** (possible longer-term)

---

## What the Code Confirms

### One final response object per turn
In `custom_components/ghcp_conversation/entity.py` both major runtime paths end by:
- creating an `IntentResponse`
- setting speech once with `async_set_speech(content)`
- returning a `ConversationResult`

This is the key reason the current UX is single-final-answer.

### Partial chunks already exist internally
In `custom_components/ghcp_conversation/acp_client.py` the ACP client already processes:
- `agent_message_chunk`
- `agent_thought_chunk`
- tool activity and permission updates

Specifically:
- `agent_message_chunk` text is appended to a list
- the full list is joined only after the turn completes

So the system already knows about partial output; it just does not expose it to Assist yet.

---

## Recommended Near-Term Pattern

## Quick acknowledgement + background completion
This is the most practical and product-friendly way to support long-running tasks now.

### Flow
1. User asks something likely to be slow.
2. The router decides it is a long-running request.
3. The integration immediately returns something like:
   - “That may take a minute; I’m working on it now.”
4. The real CLI/Azure work continues in a background task.
5. The final result is delivered through a follow-up channel.

### Good follow-up channels
- `persistent_notification`
- mobile push notification (`notify.mobile_app_*`)
- TTS announcement to a chosen speaker
- a status entity or job result entity
- a later follow-up conversation if the HA surface supports it

### Why this is good
- fast perceived response
- preserves the current one-shot Assist contract
- avoids blocking voice UI for too long
- easier to implement safely than true streaming

---

## Possible Longer-Term Path: True Progress / Partial Streaming

If Home Assistant’s conversation stack can consume streaming or progress events, then the place to tap into that is already visible in the ACP code.

### Existing hook point
- `ACPClient._handle_notification()`

This is where `agent_message_chunk` notifications arrive.

### What would need to happen
- the integration would need a way to forward those partial chunks upstream instead of only buffering them locally
- the Home Assistant Assist surface would need to support progress or partial updates in a user-visible way

### Status of this idea from the research
It is technically plausible, but it is **not** something the current repo implementation does out of the box.

---

## UX Recommendations for Slow Tasks

### Best default behavior
For complex requests:
- send a short acknowledgement quickly
- then complete in the background
- then notify the user with the final answer or result

### Example wording
- “That may take a minute; I’m working on it now.”
- “I’m checking that for you — I’ll send the result shortly.”
- “This is a more involved request; I’ll follow up when it’s done.”

### Good use cases
- automation debugging
- file edits
- repo investigation
- large reasoning tasks
- anything escalated to a strong CLI expert model

---

## What Not to Do First

### Do not depend on multi-part synchronous replies as the primary plan
The current Assist integration model in this repo is built around one `ConversationResult` per turn. Trying to force two synchronous user-visible messages into that path is likely to be more brittle than helpful as a first implementation.

### Do not block too long with no acknowledgement
If the heavy CLI path takes a while and the user hears nothing, the experience will feel slow even if the answer is good.

---

## Best Product Recommendation

For this repo, the best staged-response strategy is:

1. detect likely long-running or CLI-heavy prompts
2. return a quick acknowledgement immediately
3. continue the actual work asynchronously
4. deliver the final result through a follow-up channel

This gives nearly all the UX benefit of streaming without needing to rewrite the full conversation pipeline first.

---

## File Targets If This Is Implemented Later

### Routing / long-running detection
- `custom_components/ghcp_conversation/entity.py`

### Stream/progress hook point
- `custom_components/ghcp_conversation/acp_client.py`

### Optional notification and background job support
- likely a new helper or service module in `custom_components/ghcp_conversation/`

---

## Final Takeaway

The system already has the raw ingredients for staged output because ACP streams internally. But the current Home Assistant integration returns only one final message.

So the best near-term solution is:
- **quick acknowledgement now**
- **final answer later through follow-up notification or TTS**

That is the safest and most practical design for long or complex requests.
