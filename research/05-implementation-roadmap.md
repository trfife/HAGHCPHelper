# Implementation Roadmap

This document turns the research into a practical phased plan for future implementation.

---

## Goal

Build a faster, safer, more adaptable Home Assistant conversation stack for this repo with the following behavior:

```text
HA local handling
  -> deterministic fast intent engine
  -> Azure classifier/simple-answer layer
  -> Copilot CLI expert fallback
  -> background QA and candidate-rule promotion
```

This plan is designed to improve:
- latency
- perceived responsiveness
- correctness
- maintainability
- long-term learning

---

## Phase 0 — Baseline Measurement

Before changing behavior, measure the current system.

### Test categories
Use a representative set of prompts:
- simple control requests
- simple state queries
- moderate design requests
- debugging requests
- file-edit / repo investigation requests

### Metrics to capture
- time to first visible response
- total time to final answer
- whether HA local handled it
- whether the request reached CLI unnecessarily
- whether the answer was correct

### Why this matters
Without a baseline it will be hard to tell whether Azure-first or rule-based routing is actually helping.

---

## Phase 1 — Structured Logging and Normalization

### Objective
Create a durable log of what users asked, how the system routed it, and what answer/action resulted.

### Recommended output fields
- raw prompt
- normalized prompt
- detected intent (if any)
- route chosen (`local`, `rule`, `azure`, `cli`)
- confidence score
- answer or action summary
- timestamp
- success/failure flag if available
- review status

### Best target files
- extend `custom_components/ghcp_conversation/knowledge.py`
- or add a new routing-history helper next to it

### Why this phase comes first
The later learning loop and rule-promotion system depend on having good data.

---

## Phase 2 — Deterministic Fast Intent Engine

### Objective
Catch the most common repeated requests without paying LLM latency.

### Scope
Start with high-confidence intents only:
- light on/off
- lock state checks
- simple temperature or sensor state queries
- common room/device aliases

### Design notes
This should be more than regex alone. It should include:
- normalized phrase patterns
- alias table
- slot extraction
- repeated prompt cache

### Safety note
Start with low-risk and read-mostly intents first.

### Best target files
- likely a new module such as `router.py` or `rules.py`
- integrated from `custom_components/ghcp_conversation/entity.py`

---

## Phase 3 — Azure Classifier / Simple-Answer Layer

### Objective
Use a fast Azure model to classify or answer medium-complexity prompts before escalating to CLI.

### Recommended outputs
- `answer_now`
- `route_to_cli`
- `needs_confirmation`
- `no_confident_match`

### Important constraint
Azure should not be called in front of every request unless it is able to short-circuit enough of them to justify the latency cost.

### Best insertion point
- `custom_components/ghcp_conversation/entity.py`
- before `_async_handle_acp()`

### Supporting file
- `custom_components/ghcp_conversation/api.py`

---

## Phase 4 — Copilot CLI Expert Fallback

### Objective
Preserve the strong CLI path for the cases that truly need:
- deep reasoning
- repo work
- multi-step debugging
- file editing
- automation design

### Current state
This path already exists.

### Likely work here
- better routing into this path
- possible session reuse improvements
- clearer “long-running” detection
- better follow-up behavior

### Best target files
- `custom_components/ghcp_conversation/entity.py`
- `custom_components/ghcp_conversation/acp_client.py`

---

## Phase 5 — Staged Response UX

### Objective
Improve perceived speed for long-running tasks.

### Recommended first approach
- quick acknowledgement immediately
- background completion
- final result via notification / TTS / follow-up channel

### Why this order
This is easier and safer than trying to retrofit true streaming into the Assist pipeline as the first step.

### Best target files
- `custom_components/ghcp_conversation/entity.py`
- possibly a new helper/service for follow-up delivery

---

## Phase 6 — Background QA and Candidate Promotion

### Objective
Teach the system from its own history without letting it rewrite the fast path unsafely.

### Recommended behavior
- review batches of recent logs
- find bad or weak answers
- propose candidate rules
- promote only when confidence and validation are strong

### Promotion policy
Auto-promote only:
- low-risk patterns
- repeated high-confidence matches
- prompts with consistent successful outcomes

Use human review or higher thresholds for:
- security-sensitive actions
- destructive actions
- file modifications
- restarts

### Best storage target
- extend the current knowledge or log store with:
  - `candidate_rules`
  - `approved_rules`
  - `rejected_rules`
  - provenance / source notes

---

## Recommended File Map for Implementation

### Existing files likely to change
- `custom_components/ghcp_conversation/entity.py`
- `custom_components/ghcp_conversation/acp_client.py`
- `custom_components/ghcp_conversation/api.py`
- `custom_components/ghcp_conversation/knowledge.py`
- `custom_components/ghcp_conversation/config_flow.py`
- `custom_components/ghcp_conversation/const.py`

### Existing add-on startup files likely to change later
- `copilot-cli/rootfs/etc/services.d/ttyd/run`
- `copilot-cli/rootfs/etc/services.d/copilot-acp/run`

### Likely new files
- `custom_components/ghcp_conversation/router.py`
- `custom_components/ghcp_conversation/rules.py`
- `custom_components/ghcp_conversation/review_log.py`
- optional background review / notification helper

---

## Risk Register

| Risk | Why it matters | Mitigation |
|---|---|---|
| False positives in the fast rule engine | Wrong action on the wrong device is worse than a slow answer | start with safe intents and high thresholds |
| Azure adds latency without enough short-circuit wins | hybrid routing could become slower if poorly designed | benchmark before and after; keep router lightweight |
| Self-learning rules reinforce mistakes | unsafe if bad patterns are auto-promoted | use candidate rules, review status, thresholds |
| Long-running tasks feel slow in voice UI | poor UX if there is no acknowledgement | add quick ack + follow-up pattern |
| Too much instruction text slows CLI down | always-on context can become baggage | keep repo-wide instructions short and scoped |

---

## Validation Checklist

Before calling the architecture successful, verify:

1. median latency for common prompts is lower
2. common prompts no longer reach CLI unnecessarily
3. CLI is still used for the complex prompts that need it
4. the new fast layer has low false-positive rates
5. rule promotion improves speed without harming correctness
6. long-running requests feel better from a user perspective

---

## Recommended First Milestone

If implementation starts, the strongest first milestone is:

1. add structured logs
2. add a minimal deterministic fast path
3. add Azure routing for classification / simple answers
4. keep CLI as expert fallback

That gives the largest benefit with the least architectural risk.

---

## Final Takeaway

The roadmap should prioritize:
- **observability first**
- **deterministic speed-ups second**
- **AI routing third**
- **self-improving automation last**

That order gives the best chance of producing a system that is both fast and trustworthy.
