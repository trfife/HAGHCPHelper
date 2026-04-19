"""Intent classifier and routing engine for hybrid conversation handling."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class Route(str, Enum):
    """Routing destinations for conversation requests."""

    BUILTIN = "builtin"  # HA native intents (shopping list, todo, etc.)
    LOCAL = "local"    # Direct HA tool call, no LLM needed
    AZURE = "azure"    # Fast Azure model for moderate queries
    CLI = "cli"        # Copilot CLI expert for complex tasks


@dataclass
class RouteDecision:
    """Result of intent classification."""

    route: Route
    confidence: float          # 0.0–1.0
    matched_pattern: str = ""  # which pattern triggered the decision


# ── Pattern definitions ──────────────────────────────────────────────────
#
# Patterns are checked top-to-bottom.  First match wins.
# Groups:
#   1. LOCAL patterns  – deterministic HA control, no API call needed
#   2. CLI patterns    – complex tasks that need the full Copilot agent
#   3. Everything else – moderate queries routed to Azure fast model

# Display/navigation patterns — need LLM interpretation, route to AZURE.
# Checked BEFORE LOCAL to prevent false matches on "show me" state queries.
# ── Built-in HA intent patterns (shopping list, todo lists) ──────────
# These match phrases that HA's native conversation agent handles via
# intents (HassShoppingListAddItem, HassListAddItem, etc.).
# Routed to the default agent — no LLM needed.
_BUILTIN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "add X to my shopping list" / "put X on the list"
    (re.compile(
        r"\b(add|put)\b.+\b(shopping\s*list|grocery\s*list|the\s+list)\b",
        re.IGNORECASE,
    ), "shopping_list_add"),

    # "remove/delete/check off X from my shopping list"
    (re.compile(
        r"\b(remove|delete|check\s+off|cross\s+off|complete)\b.+"
        r"\b(shopping\s*list|grocery\s*list)\b",
        re.IGNORECASE,
    ), "shopping_list_complete"),

    # "clear/empty my shopping list"
    (re.compile(
        r"\b(clear|empty)\b.+\b(shopping\s*list|grocery\s*list)\b",
        re.IGNORECASE,
    ), "shopping_list_clear"),

    # "what's on my shopping list?" / "show my shopping list"
    (re.compile(
        r"\b(what'?s|show|list|read|what\s+is)\b.+\b(shopping\s*list|grocery\s*list)\b",
        re.IGNORECASE,
    ), "shopping_list_query"),

    # Reversed: "shopping list: add X"
    (re.compile(
        r"\b(shopping\s*list|grocery\s*list)\b.+"
        r"\b(add|remove|clear|complete|delete|empty|what'?s\s+on|put)\b",
        re.IGNORECASE,
    ), "shopping_list_reversed"),
]

_AZURE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Camera / video feed display
    (re.compile(
        r"\b(show|display|pull up|bring up|view|stream|watch)\b.+"
        r"\b(camera|cam|feed|video|stream|doorbell|ring)\b",
        re.IGNORECASE,
    ), "display_camera"),

    # Dashboard / page navigation
    (re.compile(
        r"\b(go\s+to|navigate\s+to|open|show|switch\s+to|display)\b.+"
        r"\b(dashboard|page|view|screen|panel|tab|home\s*screen|main\s*screen)\b",
        re.IGNORECASE,
    ), "navigate_dashboard"),

    # Screen control
    (re.compile(
        r"\b(go\s+back|go\s+home|show\s+(?:the\s+)?(?:home|main|default)\s+"
        r"(?:screen|page|dashboard|view))\b",
        re.IGNORECASE,
    ), "screen_control"),

    # Media playback on display
    (re.compile(
        r"\b(play|show|display|cast|put on)\b.+"
        r"\b(photo|picture|image|album|slideshow|music|song|playlist|video|movie|"
        r"tv|youtube|spotify)\b",
        re.IGNORECASE,
    ), "media_display"),

    # Announcement / intercom (needs LLM to compose message)
    (re.compile(
        r"\b(announce|announcement|broadcast|intercom|tell\s+(?:the|everyone)|"
        r"drop\s+in)\b",
        re.IGNORECASE,
    ), "announcement"),
]

_LOCAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Direct device control
    (re.compile(
        r"\b(turn\s+(?:on|off)|switch\s+(?:on|off)|toggle|activate|deactivate)"
        r"\b.*",
        re.IGNORECASE,
    ), "device_control"),

    # Set value commands
    (re.compile(
        r"\b(set|change|adjust|dim|brighten)\b.+\b(to|at|level)\b",
        re.IGNORECASE,
    ), "set_value"),

    # Lock/unlock
    (re.compile(
        r"\b(lock|unlock|arm|disarm)\b",
        re.IGNORECASE,
    ), "lock_control"),

    # Open/close
    (re.compile(
        r"\b(open|close)\s+(the\s+)?(garage|door|blind|curtain|cover|shade|gate|valve)",
        re.IGNORECASE,
    ), "cover_control"),

    # Simple state queries
    (re.compile(
        r"\b(what(?:'s| is| are)|what's|show me|tell me|get)\b.+"
        r"\b(temperature|humidity|state|status|brightness|battery|power|energy|"
        r"motion|occupancy|door|window|sensor|level|percent)\b",
        re.IGNORECASE,
    ), "state_query"),

    # "Is the X on/off/open/closed/locked?"
    (re.compile(
        r"\bis\s+(?:the\s+|my\s+)?\w+.+\b(on|off|open|closed|locked|unlocked|"
        r"home|away|armed|disarmed|running|idle)\b\s*\??\s*$",
        re.IGNORECASE,
    ), "state_check"),
]

_CLI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Explicit expert/debug/complex requests
    (re.compile(
        r"\b(debug|troubleshoot|diagnose|investigate|analyze|explain why|"
        r"figure out|deep dive)\b",
        re.IGNORECASE,
    ), "debug_request"),

    # Configuration / file editing
    (re.compile(
        r"\b(edit|modify|create|write|update|add|remove|delete)\b.+"
        r"\b(config|configuration|yaml|automation|script|scene|file|"
        r"dashboard|lovelace)\b",
        re.IGNORECASE,
    ), "config_edit"),

    # Planning / multi-step
    (re.compile(
        r"\b(plan|design|architect|build|set up|implement|migrate|refactor|"
        r"reorganize|optimize)\b",
        re.IGNORECASE,
    ), "planning"),

    # Node-RED / advanced integrations
    (re.compile(
        r"\b(node-?red|flow|blueprint|appdaemon|pyscript|hacs|custom\s+component)\b",
        re.IGNORECASE,
    ), "advanced_integration"),

    # Code / template work
    (re.compile(
        r"\b(template|jinja|code|script|python|shell|bash|command)\b.+"
        r"\b(write|create|help|fix|generate|make)\b",
        re.IGNORECASE,
    ), "code_work"),

    # Explicit expert invocation
    (re.compile(
        r"\b(think harder|use expert|be thorough|expert mode|"
        r"copilot|cli mode)\b",
        re.IGNORECASE,
    ), "explicit_expert"),

    # Log analysis
    (re.compile(
        r"\b(log|logs|error|warning|traceback|stack trace|exception)\b",
        re.IGNORECASE,
    ), "log_analysis"),
]


def classify_intent(prompt: str) -> RouteDecision:
    """Classify a user prompt and return a routing decision.

    Check order: BUILTIN → AZURE display → LOCAL → CLI → default to AZURE.
    """
    text = prompt.strip()
    if not text:
        return RouteDecision(route=Route.AZURE, confidence=0.0)

    # 1. Check BUILTIN patterns first — HA native intents (shopping list, todo)
    for pattern, label in _BUILTIN_PATTERNS:
        if pattern.search(text):
            _LOGGER.debug("Router: BUILTIN match '%s' for: %s", label, text[:80])
            return RouteDecision(
                route=Route.BUILTIN, confidence=0.95, matched_pattern=label
            )

    # 2. Check AZURE display/navigation patterns — prevent LOCAL false matches
    for pattern, label in _AZURE_PATTERNS:
        if pattern.search(text):
            _LOGGER.debug("Router: AZURE match '%s' for: %s", label, text[:80])
            return RouteDecision(
                route=Route.AZURE, confidence=0.9, matched_pattern=label
            )

    # 2. Check LOCAL patterns — deterministic device control
    for pattern, label in _LOCAL_PATTERNS:
        if pattern.search(text):
            _LOGGER.debug("Router: LOCAL match '%s' for: %s", label, text[:80])
            return RouteDecision(
                route=Route.LOCAL, confidence=0.9, matched_pattern=label
            )

    # 3. Check CLI patterns — complex tasks
    for pattern, label in _CLI_PATTERNS:
        if pattern.search(text):
            _LOGGER.debug("Router: CLI match '%s' for: %s", label, text[:80])
            return RouteDecision(
                route=Route.CLI, confidence=0.85, matched_pattern=label
            )

    # 4. Default — Azure fast model for everything else
    _LOGGER.debug("Router: AZURE (default) for: %s", text[:80])
    return RouteDecision(
        route=Route.AZURE, confidence=0.5, matched_pattern="default"
    )
