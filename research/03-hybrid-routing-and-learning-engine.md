# Hybrid Routing and Learning Engine

This document describes the recommended architecture for a layered request engine that uses Home Assistant local handling first, then a deterministic fast path, then Azure, and only finally the Copilot CLI expert path.

---

## Executive Recommendation

The best architecture discovered during research is:

```text
HA local handling
  -> deterministic fast intent/rule engine + Azure in parallel
  -> Copilot CLI expert fallback
  -> background QA / learning loop
```

This is the strongest balance of:
- speed
- correctness
- controllability
- long-term learning

---

## Why This Architecture Fits the Problem

### Problem to solve
- Some requests are simple and repetitive.
- Some requests need moderate interpretation.
- Some requests need heavy reasoning, repo edits, or debugging.
- The slowest path should not be used for every prompt.

### Key insight
The heavy CLI expert should be treated as the **recovery and expert tier**, not the default answerer for everything.

---

## Proposed Routing Flow

## Layer 0 — Home Assistant local handling
This is already in front when the system is configured to prefer local command handling.

Examples caught here:
- basic built-in home control
- common Assist-native intents

This should stay first because it is the fastest and safest path.

---

## Layer 1 — Deterministic fast path
This is the “super regex” idea, but it should be broader and more structured than regex alone.

### Recommended components
- regex and phrase templates
- normalized prompt forms
- slot extraction for room/device/action
- alias table for entities and common nicknames
- synonym mapping
- repeated-prompt cache

### Good example matches
- “turn off kitchen lights”
- “what’s the temperature in the office”
- “open the garage”
- “is the front door locked”

### Design goal
This layer should be:
- extremely fast
- deterministic
- safe
- easy to inspect and tune

---

## Layer 2 — Azure in parallel
Azure should run in parallel with the deterministic layer, not necessarily after it.

### Azure’s role
Azure should be a:
- classifier
- router
- simple-answer tier

### Recommended outputs
It should return one of:
- `answer_now`
- `route_to_cli`
- `needs_confirmation`
- `no_confident_match`

### Important rule
Azure should only short-circuit the request when it is confident.
If it is uncertain, it should escalate rather than guess.

---

## Layer 3 — Copilot CLI expert fallback
This is the heavy but powerful tier.

Use it for:
- multi-step debugging
- editing files or configs
- repo investigation
- long reasoning chains
- ambiguous prompts
- cases the fast layers cannot answer with high confidence

This path can use a stronger model such as:
- `claude-opus-4.6`
- `claude-sonnet-4.6`

---

## Layer 4 — Learning and QA loop
All turns should be logged and reviewed over time.

### What to log
For each request store:
- raw prompt
- normalized prompt
- routing result (`local`, `rule`, `azure`, `cli`)
- returned answer/action
- confidence score
- timestamp
- success/failure or user correction if known

### Goal of the QA loop
Use the expert tier to periodically review:
- which answers were correct
- which answers were low quality
- which repeated patterns deserve promotion into the fast path

---

## Critical Safety Refinement

The expert should generate **candidate rules**, not directly rewrite the fast rule set with no oversight.

### Why this matters
A self-improving system can reinforce bad behavior if it promotes weak or incorrect matches directly into the deterministic layer.

### Better promotion policy
- auto-promote only low-risk, high-confidence, repeated patterns first
- require stricter thresholds or review for risky actions
- keep a record of where each promoted rule came from

---

## Suggested Safety Categories

### Safe for auto-promotion first
- sensor state questions
- status checks
- repeated, read-only queries
- simple light/media queries that are already common and verified

### Require review or stricter thresholds
- unlocking doors
- garage door actions
- alarm actions
- restart flows
- any operation that edits files or changes automation logic

---

## Why “Super Regex” Should Not Be Regex Alone

A regex-only system becomes brittle quickly.

The better approach is a small **intent engine** with:
- normalization
- extracted slots
- aliasing
- success-weighted patterns
- a fallback to Azure when ambiguous

This preserves the speed of deterministic matching without making the system fragile.

---

## Example Routing Table

| Request Type | Likely Route | Why |
|---|---|---|
| “Turn off the kitchen lights” | HA local or deterministic engine | simple, repetitive control |
| “What’s the temp in the office?” | HA local / deterministic / Azure | simple state query |
| “Create an automation to notify me when the washer finishes” | Azure or CLI | moderate design task |
| “Why didn’t my automation trigger last night?” | CLI expert | multi-step reasoning + debugging |
| “Fix this YAML and reload HA safely” | CLI expert | file edits + validation |

---

## Best Insertion Point in This Repo

The right place to add the layered router is:
- `custom_components/ghcp_conversation/entity.py`

Why:
- that file already merges config
- already selects the backend
- already has both direct API and ACP routes
- is the cleanest place to decide which tier should handle the request

The thin platform shim in:
- `copilot-cli/ghcp_conversation/conversation.py`

is not the main logic location.

---

## Recommended Learning Loop Design

### Background, not foreground
Do not have CLI constantly re-review history during user-facing turns.

Better options:
- nightly background batch
- every N requests
- manual “review recent logs” command

### What the review pass should do
- find wrong or weak answers
- find near-duplicate prompts
- generate candidate intent patterns
- improve alias tables
- suggest new safe fast-path rules

This keeps the user-facing path fast.

---

## Final Recommendation

If this architecture is implemented, the best order is:

1. logging + normalization
2. deterministic fast engine
3. Azure router/simple-answer tier
4. CLI fallback
5. reviewed rule promotion pipeline

That delivers the speed gains early while keeping the self-improving behavior safe and auditable.
