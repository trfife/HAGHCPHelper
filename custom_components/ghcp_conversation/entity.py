"""Conversation entity for GitHub Copilot Conversation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

import aiohttp

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    AssistantContent,
    ChatLog,
    ConversationEntity,
    ConversationEntityFeature,
    ConversationInput,
    ConversationResult,
    ToolResultContent,
    UserContent,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent, llm
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

try:
    from voluptuous_openapi import convert as vol_to_openapi
except ImportError:
    vol_to_openapi = None  # type: ignore[assignment]

from .acp_client import ACPClient, ACPError, ACPResponse

try:
    from .analytics import AnalyticsStore, RequestMetrics, TraceLog
except ImportError:
    AnalyticsStore = None  # type: ignore[assignment,misc]
    RequestMetrics = None  # type: ignore[assignment,misc]
    TraceLog = None  # type: ignore[assignment,misc]

from .api import APIError, ChatCompletionClient, build_azure_client, build_github_client
from .const import (
    ACP_DEFAULT_PORT,
    BACKEND_AZURE,
    BACKEND_COPILOT_CLI,
    BACKEND_GITHUB,
    BACKEND_HYBRID,
    BARNABEE_PROMPT,
    CONF_ACP_HOST,
    CONF_ACP_PORT,
    CONF_AUTO_FIX_ENABLED,
    CONF_AZURE_API_KEY,
    CONF_AZURE_ENDPOINT,
    CONF_AZURE_ROUTER_ENDPOINT,
    CONF_AZURE_ROUTER_KEY,
    CONF_AZURE_ROUTER_MODEL,
    CONF_BACKEND,
    CONF_EMAIL_MODE,
    CONF_EMAIL_NOTIFY_SERVICE,
    CONF_EMAIL_THRESHOLD,
    CONF_EXPERT_MODEL,
    CONF_FAILURE_NOTIFY_ENABLED,
    CONF_FAILURE_NOTIFY_SERVICE,
    CONF_GITHUB_TOKEN,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_NOTION_DB_ID,
    CONF_NOTION_LOG_MODE,
    CONF_NOTION_TOKEN,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_AUTO_FIX_ENABLED,
    DEFAULT_AZURE_ROUTER_MODEL,
    DEFAULT_EMAIL_MODE,
    DEFAULT_EMAIL_THRESHOLD,
    DEFAULT_FAILURE_NOTIFY_ENABLED,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_NOTION_LOG_MODE,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    EMAIL_MODE_ALWAYS,
    EMAIL_MODE_LONG_ONLY,
    EMAIL_MODE_OFF,
    EXPERT_TOOL_NAME,
    JOKE_HISTORY_LIMIT,
    JOKE_INJECT_LIMIT,
    JOKE_REQUEST_KEYWORDS,
    KNOWLEDGE_TOOL_NAME,
    MAX_EMAIL_THINKING_CHARS,
    NOTION_API_URL,
    NOTION_API_VERSION,
    NOTION_LOG_MODE_ALWAYS,
    NOTION_LOG_MODE_FAILURES,
    NOTION_LOG_MODE_LONG_ONLY,
    NOTION_LOG_MODE_OFF,
    NOTION_MAX_TEXT_CHARS,
    ORCHESTRATOR_PROMPT_SUFFIX,
    SATELLITE_CONTEXT_TEMPLATE,
    SHOPPING_LIST_GUIDANCE,
    SUBENTRY_TYPE_CONVERSATION,
    VOICE_DETAIL_SEPARATOR,
    FAMILY_FRIENDLY_SUFFIX,
)
from .router import Route, classify_intent

_LOGGER = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10

# Max sentences to use as spoken portion when no separator is present
_VOICE_MAX_SENTENCES = 2

# Voice instructions prepended to ACP prompts so CLI knows to be concise
_ACP_VOICE_PREFIX = (
    "[VOICE MODE] This response will be spoken aloud via ElevenLabs TTS. Rules:\n"
    "- Keep your response to 1–2 sentences MAX. Be brief and conversational.\n"
    "- No emojis. You may use these ElevenLabs audio tags inline with text: "
    "[sighs], [laughs], [clears throat], [gasps], [grunt], [exhales], "
    "[giggles], [crying].\n"
    "- Audio tags must appear inline with spoken text, never alone on a line.\n"
    "- If the answer needs detail, give a short spoken summary first, then "
    "put [[DETAIL]] on its own line, followed by the full answer.\n\n"
    "User said: "
)

# Regex to match emojis and other symbols that ElevenLabs strips to empty text
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U000020E3"             # combining enclosing keycap
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "]+",
    flags=re.UNICODE,
)


# Patterns that indicate Azure is deflecting / can't handle the request
_DEFLECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:i (?:can't|cannot|don't have (?:the ability|access)|am (?:not able|unable)|lack the ability))\b", re.IGNORECASE),
    re.compile(r"\b(?:i'm (?:not able|unable|sorry.{0,20}(?:can't|cannot|don't have)))\b", re.IGNORECASE),
    re.compile(r"\b(?:beyond (?:my|what i can)|outside (?:my|the scope of))\b", re.IGNORECASE),
    re.compile(r"\b(?:you (?:would need to|should|might want to|could try|may need to) (?:ask|use|contact|check|consult))\b", re.IGNORECASE),
    re.compile(r"\b(?:(?:not|don't) have (?:direct )?access to (?:your|the|that))\b", re.IGNORECASE),
    re.compile(r"\b(?:requires? (?:direct|file|ssh|terminal|shell|cli) access)\b", re.IGNORECASE),
    re.compile(r"\b(?:(?:can't|cannot) (?:directly )?(?:edit|modify|create|write|read|access|manage|configure|clear|delete|remove) (?:files?|config|yaml|dashboard|your|the|that|a))\b", re.IGNORECASE),
    re.compile(r"\b(?:(?:don't|do not) have (?:the )?(?:tools?|capability|means|ability) to)\b", re.IGNORECASE),
    # Additional deflection phrases
    re.compile(r"\b(?:that'?s not something i (?:can|am able to))\b", re.IGNORECASE),
    re.compile(r"\b(?:i (?:don't|do not) (?:currently )?have (?:the ability|a way) to)\b", re.IGNORECASE),
    re.compile(r"\b(?:(?:unfortunately|i'?m afraid),? i (?:can't|cannot|don't|am unable))\b", re.IGNORECASE),
    re.compile(r"\b(?:this (?:requires|needs|would need) (?:access to|a|the))\b.+\b(?:which i (?:don't|do not) have)\b", re.IGNORECASE),
    re.compile(r"\b(?:i (?:don't|do not) have (?:the )?(?:necessary|required|appropriate) (?:access|tools?|permissions?))\b", re.IGNORECASE),
]


def _is_deflection(response_text: str) -> bool:
    """Return True if the Azure response indicates it can't handle the request."""
    if not response_text or len(response_text) < 15:
        return False
    for pattern in _DEFLECTION_PATTERNS:
        if pattern.search(response_text):
            return True
    return False


def _sanitize_for_tts(text: str) -> str:
    """Remove emojis and ensure text isn't empty after ElevenLabs tag stripping."""
    # Strip emojis
    text = _EMOJI_RE.sub("", text)
    # Clean up extra whitespace left behind
    text = re.sub(r"  +", " ", text).strip()
    return text


def split_response_for_voice(content: str) -> tuple[str, str]:
    """Split a response into (spoken, full) parts.

    If ``[[DETAIL]]`` is present, the text before it is spoken and the entire
    content (with the marker stripped) is the full version for email.

    When the marker is absent, the first 1–2 sentences become the spoken part
    and the full text is used for email.  If the response is already short
    (≤2 sentences), both values are identical.
    """
    if not content:
        return ("", "")

    sep = VOICE_DETAIL_SEPARATOR
    if sep in content:
        parts = content.split(sep, 1)
        spoken = parts[0].strip()
        detail = parts[1].strip() if len(parts) > 1 else ""
        # Full email version = spoken + detail, marker removed
        full = f"{spoken}\n\n{detail}".strip() if detail else spoken
        # Sanitize spoken part for TTS
        spoken = _sanitize_for_tts(spoken)
        return (spoken, full)

    # Fallback: split on sentence boundaries (., !, ?)
    sentence_ends = re.finditer(r'[.!?](?:\s|$)', content)
    positions = [m.end() for m in sentence_ends]

    if len(positions) >= _VOICE_MAX_SENTENCES and positions[_VOICE_MAX_SENTENCES - 1] < len(content) - 5:
        cut = positions[_VOICE_MAX_SENTENCES - 1]
        spoken = _sanitize_for_tts(content[:cut].strip())
        return (spoken, content.strip())

    # Short enough — use as-is for both
    spoken = _sanitize_for_tts(content.strip())
    return (spoken, content.strip())


def _extract_response_text(result: ConversationResult) -> str:
    """Extract the plain speech text from a ConversationResult."""
    if result.response and result.response.speech:
        plain = result.response.speech.get("plain", {})
        return plain.get("speech", "")
    return ""


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation entities from a config entry."""
    # Create a default conversation entity from the main config entry
    entities: list[GHCPConversationEntity] = [
        GHCPConversationEntity(config_entry, None)
    ]
    # Also create entities from subentries
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION:
            entities.append(GHCPConversationEntity(config_entry, subentry))

    async_add_entities(entities)


class GHCPConversationEntity(ConversationEntity):
    """GitHub Copilot conversation agent entity."""

    _attr_has_entity_name = True
    _attr_supported_features = ConversationEntityFeature.CONTROL

    def __init__(
        self,
        config_entry: ConfigEntry,
        subentry: ConfigSubentry | None,
    ) -> None:
        """Initialize the entity."""
        self._config_entry = config_entry
        self._subentry = subentry
        # Persistent ACP session ID — survives across conversation turns
        self._acp_session_id: str | None = None
        # Last thinking/reasoning content from ACP (for email)
        self._last_thinking: str = ""
        # Full response text for email (may include detail stripped from speech)
        self._last_full_response: str = ""

        if subentry:
            self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}"
            self._attr_name = subentry.title or "Copilot Agent"
        else:
            self._attr_unique_id = config_entry.entry_id
            self._attr_name = "GitHub Copilot"

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"

    @property
    def _entry_data(self) -> dict[str, Any]:
        """Return the merged config from entry + subentry."""
        data = dict(self._config_entry.data)
        data.update(self._config_entry.options)
        if self._subentry:
            data.update(self._subentry.data)
        return data

    def _resolve_system_prompt(self, data: dict[str, Any]) -> str:
        """Select the system prompt for conversation requests.

        Always uses BARNABEE_PROMPT as the base personality.
        Appends speaker context if Voice Match identified the speaker.
        """
        prompt = BARNABEE_PROMPT
        speaker = getattr(self, "_current_speaker", None)
        if speaker:
            prompt += (
                f"\n\nThe person speaking to you right now is {speaker.title()}. "
                f"Address them by name naturally when appropriate (e.g. greetings, confirmations)."
            )
        return prompt

    def _get_device_context(
        self,
        user_input: ConversationInput,
    ) -> str:
        """Build device context string when request comes from a satellite.

        Looks up the device in HA's device registry and returns the
        SATELLITE_CONTEXT_TEMPLATE with area info if the device is found.
        Returns empty string for non-satellite or unknown devices.
        """
        device_id = getattr(user_input, "device_id", None)
        if not device_id:
            return ""

        try:
            from homeassistant.helpers import device_registry as dr

            dev_reg = dr.async_get(self.hass)
            device = dev_reg.async_get(device_id)
            if not device:
                return ""

            # Check if it's a satellite-like device (VACA, ESPHome, Wyoming)
            is_satellite = False
            for identifier in device.identifiers:
                domain = identifier[0] if isinstance(identifier, tuple) else ""
                if domain in (
                    "vaca", "esphome", "wyoming", "assist_satellite",
                ):
                    is_satellite = True
                    break
            # Also treat it as satellite if the device has an
            # assist_satellite entity (covers any integration)
            if not is_satellite:
                from homeassistant.helpers import entity_registry as er

                ent_reg = er.async_get(self.hass)
                for entry in er.async_entries_for_device(ent_reg, device_id):
                    if entry.domain == "assist_satellite":
                        is_satellite = True
                        break

            if not is_satellite:
                return ""

            area_info = ""
            if device.area_id:
                from homeassistant.helpers import area_registry as ar

                area_reg = ar.async_get(self.hass)
                area = area_reg.async_get_area(device.area_id)
                if area:
                    area_info = f" in the {area.name}"

            return SATELLITE_CONTEXT_TEMPLATE.format(area_info=area_info)
        except Exception:
            _LOGGER.debug(
                "Failed to resolve device context for %s", device_id,
                exc_info=True,
            )
            return ""

    def _get_client(self, session: aiohttp.ClientSession) -> ChatCompletionClient:
        """Build the API client from current config."""
        data = self._entry_data
        backend = data.get(CONF_BACKEND, BACKEND_GITHUB)

        if backend in (BACKEND_AZURE, BACKEND_HYBRID):
            # For hybrid, use the Azure router creds if available, else Azure creds
            endpoint = data.get(CONF_AZURE_ROUTER_ENDPOINT) or data.get(
                CONF_AZURE_ENDPOINT, ""
            )
            api_key = data.get(CONF_AZURE_ROUTER_KEY) or data.get(
                CONF_AZURE_API_KEY, ""
            )
            model = (
                data.get(CONF_AZURE_ROUTER_MODEL)
                or data.get(CONF_MODEL, "")
            )
            if endpoint and api_key:
                return build_azure_client(
                    session, endpoint, api_key, model=model,
                )
        return build_github_client(session, data.get(CONF_GITHUB_TOKEN, ""))

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Process an incoming chat message."""
        data = self._entry_data
        backend = data.get(CONF_BACKEND, BACKEND_GITHUB)

        # Extract speaker name from Voice Match tag (e.g. "[thom] Turn on lights")
        self._current_speaker: str | None = None
        text = user_input.text
        if text.startswith("["):
            bracket_end = text.find("]")
            if bracket_end > 0:
                self._current_speaker = text[1:bracket_end].strip()
                # Strip the tag from the text in-place
                user_input.text = text[bracket_end + 1:].strip()

        _LOGGER.info(
            "Incoming message: backend=%s agent=%s speaker=%s prompt='%s'",
            backend,
            self._attr_name,
            self._current_speaker or "unknown",
            user_input.text[:100],
        )

        # Reset thinking for this turn
        self._last_thinking = ""
        self._last_full_response = ""
        self._last_route_trace: list[str] = []
        self._last_route_tag: str = ""

        # ACP mode — forward prompt to Copilot CLI
        if backend == BACKEND_COPILOT_CLI:
            self._last_route_trace = [f"Backend: {backend} (direct ACP)"]
            self._last_route_tag = "cli"
            result = await self._async_handle_acp(user_input, chat_log, data)
        # Hybrid mode — router decides: local → azure → cli fallback
        elif backend == BACKEND_HYBRID:
            result = await self._async_handle_hybrid(user_input, chat_log, data)
        else:
            self._last_route_trace = [f"Backend: {backend} (direct API)"]
            self._last_route_tag = "azure"
            result = await self._async_handle_direct_api(user_input, chat_log, data)

        # Send email notification if configured (legacy)
        await self._async_maybe_send_email(user_input.text, result, data)

        # Log to Notion if configured (preferred over email)
        await self._async_maybe_log_to_notion(user_input.text, result, data)

        # Track jokes for de-duplication
        if self._is_joke_request(user_input.text):
            response_text = self._last_full_response or ""
            if not response_text and result.response and result.response.speech:
                response_text = result.response.speech.get("plain", {}).get(
                    "speech", ""
                )
            if response_text:
                await self._async_maybe_log_joke(response_text)

        # Write to shared context for cross-interface memory
        await self._async_write_shared_context(
            user_input.text, result, chat_log.conversation_id
        )

        # Prefix the spoken response with a route tag for visibility
        if self._last_route_tag and result.response and result.response.speech:
            plain = result.response.speech.get("plain", {})
            speech_text = plain.get("speech", "")
            if speech_text:
                tag_map = {
                    "local": "[HA]",
                    "azure": "[AZ]",
                    "cli": "[CLI]",
                }
                tag = tag_map.get(self._last_route_tag, "")
                if tag:
                    result.response.async_set_speech(f"{tag} {speech_text}")

        # Check for [[LISTEN]] marker — keep mic open for follow-up
        if result.response and result.response.speech:
            plain = result.response.speech.get("plain", {})
            speech_text = plain.get("speech", "")
            if "[[LISTEN]]" in speech_text:
                speech_text = speech_text.replace("[[LISTEN]]", "").strip()
                result.response.async_set_speech(speech_text)
                result.continue_conversation = True

        return result

    async def _async_handle_acp(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        data: dict[str, Any],
    ) -> ConversationResult:
        """Route the prompt through the Copilot CLI ACP server."""
        host = data.get(CONF_ACP_HOST, "localhost")
        port = int(data.get(CONF_ACP_PORT, ACP_DEFAULT_PORT))

        _LOGGER.info("ACP request: host=%s port=%s", host, port)

        client = ACPClient(host, port)
        try:
            await client.async_connect()
            await client.async_initialize()

            # Resume or create session — keeps conversation history
            session_id = await client.async_ensure_session(
                session_id=self._acp_session_id,
                cwd="/homeassistant",
            )
            is_new_session = session_id != self._acp_session_id
            self._acp_session_id = session_id

            # Seed new ACP sessions with cross-interface context
            prompt_text = _ACP_VOICE_PREFIX + user_input.text
            if is_new_session:
                context_prefix = await self._async_get_shared_context_prefix()
                if context_prefix:
                    prompt_text = context_prefix + "\n\n" + prompt_text

            acp_response = await client.async_prompt(prompt_text)
            raw_content = acp_response.text
            self._last_thinking = acp_response.thinking

            # Split for voice: short spoken part vs full email content
            spoken, full = split_response_for_voice(raw_content)
            content = spoken
            self._last_full_response = full

            _LOGGER.info(
                "ACP response: %d chars (spoken=%d, full=%d), thinking=%d chars, session=%s",
                len(raw_content), len(spoken), len(full),
                len(self._last_thinking), self._acp_session_id,
            )
        except ACPError as err:
            _LOGGER.error("ACP error: %s", err)
            # Reset session on error so next attempt starts fresh
            self._acp_session_id = None
            content = f"Sorry, I couldn't reach the Copilot CLI: {err}"
        except Exception:
            _LOGGER.exception("Unexpected ACP error")
            self._acp_session_id = None
            content = "Sorry, an unexpected error occurred with the Copilot CLI."
        finally:
            await client.async_close()

        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=content)
        )
        response_obj = intent.IntentResponse(language=user_input.language)
        response_obj.async_set_speech(content)
        return ConversationResult(
            response=response_obj,
            conversation_id=chat_log.conversation_id,
        )

    async def _async_maybe_send_email(
        self,
        user_prompt: str,
        result: ConversationResult,
        data: dict[str, Any],
    ) -> None:
        """Send an email with the response and thinking log if configured.

        Legacy — kept for backward compat. Notion logging is preferred.
        """
        email_mode = data.get(CONF_EMAIL_MODE, DEFAULT_EMAIL_MODE)
        if email_mode == EMAIL_MODE_OFF:
            return

        service_name = data.get(CONF_EMAIL_NOTIFY_SERVICE, "")
        if not service_name:
            return

        # Normalize: accept "notify.foo" or just "foo"
        if service_name.startswith("notify."):
            service_name = service_name[len("notify."):]

        # Get the response text — prefer the full (unsplit) response for email
        response_text = self._last_full_response
        if not response_text:
            # Fallback: use spoken text from the result
            if result.response and result.response.speech:
                response_text = result.response.speech.get("plain", {}).get(
                    "speech", ""
                )

        if not response_text:
            return

        # Check threshold for long_only mode (measure full response, not spoken)
        if email_mode == EMAIL_MODE_LONG_ONLY:
            threshold = int(
                data.get(CONF_EMAIL_THRESHOLD, DEFAULT_EMAIL_THRESHOLD)
            )
            if len(response_text) < threshold:
                return

        # Build email body
        thinking = self._last_thinking
        if thinking and len(thinking) > MAX_EMAIL_THINKING_CHARS:
            thinking = (
                thinking[:MAX_EMAIL_THINKING_CHARS]
                + f"\n\n... [truncated — {len(self._last_thinking):,} chars total]"
            )

        parts: list[str] = []
        parts.append(f"## Your Message\n\n{user_prompt}")

        # Include routing trace so user can see the flow
        if self._last_route_trace:
            trace_lines = "\n".join(f"- {s}" for s in self._last_route_trace)
            parts.append(f"## Routing Flow\n\n{trace_lines}")

        if thinking:
            parts.append(f"## Thinking / Reasoning\n\n{thinking}")
        parts.append(f"## Response\n\n{response_text}")

        body = "\n\n---\n\n".join(parts)
        subject = f"Copilot: {user_prompt[:60]}"
        if len(user_prompt) > 60:
            subject += "…"

        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {"message": body, "title": subject},
                blocking=False,
            )
            _LOGGER.info(
                "Email sent via notify.%s (%d chars)",
                service_name,
                len(body),
            )
        except Exception:
            _LOGGER.warning(
                "Failed to send email via notify.%s", service_name,
                exc_info=True,
            )

    # ── Notion logging ───────────────────────────────────────────────────

    async def _async_maybe_log_to_notion(
        self,
        user_prompt: str,
        result: ConversationResult,
        data: dict[str, Any],
        *,
        is_failure: bool = False,
        error_msg: str = "",
    ) -> None:
        """Log conversation to Notion database if configured."""
        log_mode = data.get(CONF_NOTION_LOG_MODE, DEFAULT_NOTION_LOG_MODE)
        if log_mode == NOTION_LOG_MODE_OFF:
            return

        notion_token = data.get(CONF_NOTION_TOKEN, "")
        notion_db_id = data.get(CONF_NOTION_DB_ID, "")
        if not notion_token or not notion_db_id:
            return

        # Determine if we should log based on mode
        response_text = self._last_full_response or ""
        if not response_text and result and result.response and result.response.speech:
            response_text = result.response.speech.get("plain", {}).get("speech", "")

        if log_mode == NOTION_LOG_MODE_FAILURES and not is_failure:
            return
        if log_mode == NOTION_LOG_MODE_LONG_ONLY and not is_failure:
            threshold = int(data.get(CONF_EMAIL_THRESHOLD, DEFAULT_EMAIL_THRESHOLD))
            if len(response_text) < threshold:
                return

        # Build title
        title = user_prompt[:60]
        if len(user_prompt) > 60:
            title += "…"

        # Status
        if is_failure:
            status = "❌ Failed"
        elif self._last_route_tag == "cli" and self._last_route_trace:
            # Check if Azure deflected
            if any("DEFLECTED" in s for s in self._last_route_trace):
                status = "⚠️ Deflected"
            else:
                status = "✅ Success"
        else:
            status = "✅ Success"

        route = self._last_route_tag or "unknown"
        model = getattr(self, "_last_model", "") or ""

        # Fire and forget — don't block the response
        self.hass.async_create_task(
            self._async_notion_write(
                notion_token, notion_db_id, title, route, model,
                status, response_text, error_msg, user_prompt,
            ),
            "ghcp_notion_log",
        )

    async def _async_notion_write(
        self,
        token: str,
        db_id: str,
        title: str,
        route: str,
        model: str,
        status: str,
        response_text: str,
        error_msg: str,
        user_prompt: str,
    ) -> None:
        """Write a conversation log entry to Notion (background task)."""
        from datetime import date

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

        # Build properties (small metadata)
        properties: dict[str, Any] = {
            "Title": {"title": [{"text": {"content": title}}]},
            "Date": {"date": {"start": date.today().isoformat()}},
            "Route": {"select": {"name": route}},
            "Status": {"select": {"name": status}},
        }
        if model:
            properties["Model"] = {
                "rich_text": [{"text": {"content": model[:100]}}]
            }
        if response_text:
            properties["Response Length"] = {"number": len(response_text)}
        if error_msg:
            properties["Error"] = {
                "rich_text": [{"text": {"content": error_msg[:200]}}]
            }

        # Build page body blocks (full content)
        children: list[dict[str, Any]] = []

        # User prompt block
        children.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": [{"text": {"content": "User Message"}}]},
        })
        for chunk in self._chunk_text(user_prompt):
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": chunk}}]},
            })

        # Routing trace
        if self._last_route_trace:
            children.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": "Routing"}}]},
            })
            for step in self._last_route_trace[:20]:
                children.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"text": {"content": step[:NOTION_MAX_TEXT_CHARS]}}]
                    },
                })

        # Response block
        if response_text:
            children.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": "Response"}}]},
            })
            for chunk in self._chunk_text(response_text):
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": chunk}}]},
                })

        payload: dict[str, Any] = {
            "parent": {"database_id": db_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children[:100]  # Notion limit

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{NOTION_API_URL}/pages",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        _LOGGER.info("Notion log created for: %s", title)
                    else:
                        body = await resp.text()
                        _LOGGER.warning(
                            "Notion API error %d: %s", resp.status, body[:200]
                        )
        except Exception:
            _LOGGER.warning("Failed to log to Notion", exc_info=True)

    @staticmethod
    def _chunk_text(text: str, max_len: int = NOTION_MAX_TEXT_CHARS) -> list[str]:
        """Split text into chunks that fit Notion's rich_text limit."""
        if not text:
            return []
        chunks = []
        for i in range(0, len(text), max_len):
            chunks.append(text[i : i + max_len])
        return chunks

    # ── Joke tracking ────────────────────────────────────────────────────

    @staticmethod
    def _is_joke_request(user_prompt: str) -> bool:
        """Check if the user is asking for a joke."""
        text = user_prompt.lower().strip()
        return any(kw in text for kw in JOKE_REQUEST_KEYWORDS)

    async def _async_get_joke_exclusions(self) -> str:
        """Build prompt text listing recent jokes to avoid."""
        analytics: AnalyticsStore | None = self.hass.data.get(
            DOMAIN, {}
        ).get("analytics")
        if not analytics:
            return ""
        recent = await analytics.async_get_recent_jokes(JOKE_INJECT_LIMIT)
        if not recent:
            return ""
        lines = []
        for i, joke in enumerate(recent, 1):
            # Truncate to just punchline-length for prompt efficiency
            short = joke[:120].replace("\n", " ")
            lines.append(f"{i}. {short}")
        return (
            "\n\n## Recently Told Jokes (DO NOT repeat these)\n"
            + "\n".join(lines)
            + "\nTell a DIFFERENT joke you haven't told recently."
        )

    async def _async_maybe_log_joke(self, response_text: str) -> None:
        """If the response looks like a joke, log it."""
        analytics: AnalyticsStore | None = self.hass.data.get(
            DOMAIN, {}
        ).get("analytics")
        if not analytics or not response_text:
            return
        await analytics.async_log_joke(response_text)

    @staticmethod
    def _diagnose_failure(
        error_msg: str, route: str
    ) -> tuple[str, str | None]:
        """Pattern-match an error and return (diagnosis, auto_fix_action | None).

        Returns:
            A 2-tuple of (human-readable diagnosis, auto-fix key or None).
            auto-fix key is one of: "clear_conversation", "retry_fresh", "fallback_route", or None.
        """
        err = error_msg.lower()

        # Azure 400 — invalid message content / corrupt history
        if "400" in err or ("invalid" in err and ("message" in err or "content" in err)):
            return (
                "Azure returned 400 — likely invalid message format in "
                "conversation history.",
                "clear_conversation",
            )

        # Azure 401/403 — expired or invalid API key
        if "401" in err or "authentication failed" in err:
            return ("Azure authentication failed — API key may be expired.", None)
        if "403" in err or "access denied" in err:
            return ("Azure access denied — check API key permissions.", None)

        # Azure 429 — rate limited
        if "429" in err or "rate limit" in err:
            return ("Azure rate limited — too many requests.", None)

        # CLI / ACP errors
        if "acp" in err or "copilot cli" in err or "couldn't reach" in err:
            return (
                "Copilot CLI (ACP) is unreachable — server may be down or overloaded.",
                "retry_fresh",
            )
        if "timeout" in err or "timed out" in err:
            return (
                "Request timed out — the backend may be overloaded.",
                "retry_fresh",
            )

        # Tool execution errors
        if "entity not found" in err or "service not found" in err:
            return (
                "A tool execution failed — entity or service not found.",
                None,
            )

        # Generic fallback
        return (f"Unexpected error: {error_msg[:200]}", None)

    async def _async_diagnose_and_notify(
        self,
        error_msg: str,
        route: str,
        user_prompt: str,
        conversation_id: str,
        data: dict[str, Any],
    ) -> None:
        """Diagnose a failure, optionally auto-fix, and send a notification."""
        # Check if failure notifications are enabled
        enabled = data.get(CONF_FAILURE_NOTIFY_ENABLED, DEFAULT_FAILURE_NOTIFY_ENABLED)
        if isinstance(enabled, str):
            enabled = enabled.lower() == "true"
        if not enabled:
            return

        service_name = data.get(CONF_FAILURE_NOTIFY_SERVICE, "")
        if not service_name:
            return

        # Normalize: accept "notify.foo" or just "foo"
        if service_name.startswith("notify."):
            service_name = service_name[len("notify."):]

        diagnosis, auto_fix = self._diagnose_failure(
            error_msg, route
        )

        # Apply safe auto-fix if enabled
        auto_fix_raw = data.get(CONF_AUTO_FIX_ENABLED, DEFAULT_AUTO_FIX_ENABLED)
        if isinstance(auto_fix_raw, str):
            auto_fix_enabled = auto_fix_raw.lower() == "true"
        else:
            auto_fix_enabled = bool(auto_fix_raw)
        fix_status = ""
        if auto_fix and auto_fix_enabled:
            if auto_fix == "clear_conversation":
                self._acp_session_id = None
                fix_status = "Auto-fix: cleared conversation state. Applied \u2705"
            elif auto_fix == "retry_fresh":
                self._acp_session_id = None
                fix_status = "Auto-fix: reset session for fresh retry. Applied \u2705"
            elif auto_fix == "fallback_route":
                fix_status = "Auto-fix: will fallback to alternative route on next request. Applied \u2705"
        elif auto_fix:
            fix_status = f"Auto-fix available ({auto_fix}) but disabled in config."

        # Check for repeated failures on same conversation
        repeated_note = ""
        try:
            analytics: AnalyticsStore | None = self.hass.data.get(
                DOMAIN, {}
            ).get("analytics")
            if analytics and conversation_id:
                recent = await analytics.async_get_recent_failures(
                    conversation_id=conversation_id, limit=5, hours=1
                )
                if len(recent) >= 2:
                    repeated_note = (
                        f"\u26a0\ufe0f Repeated failures ({len(recent)} in the "
                        f"last hour) on this conversation — state may be corrupted."
                    )
                    if auto_fix_enabled:
                        self._acp_session_id = None
                        repeated_note += " Session reset applied."
        except Exception:
            _LOGGER.debug("Failed to check recent failures (non-fatal)")

        # Build route label
        route_label = {
            "local": "Local (HA)",
            "azure": "Azure API",
            "cli": "Copilot CLI",
        }.get(route, route or "Unknown")

        title = f"\U0001f916 Assistant Error: {route_label} failed"

        parts: list[str] = []
        prompt_preview = user_prompt[:80]
        if len(user_prompt) > 80:
            prompt_preview += "\u2026"
        parts.append(f'{diagnosis} on "{prompt_preview}"')
        if fix_status:
            parts.append(fix_status)
        if repeated_note:
            parts.append(repeated_note)

        message = "\n".join(parts)

        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {
                    "message": message,
                    "title": title,
                    "data": {
                        "url": "/config/logs",
                        "clickAction": "/config/logs",
                    },
                },
                blocking=False,
            )
            _LOGGER.info(
                "Failure notification sent via notify.%s for route=%s",
                service_name,
                route,
            )
        except Exception:
            _LOGGER.warning(
                "Failed to send failure notification via notify.%s",
                service_name,
                exc_info=True,
            )

    async def _async_write_shared_context(
        self,
        user_prompt: str,
        result: ConversationResult,
        conversation_id: str | None,
    ) -> None:
        """Write a conversation summary to shared context (fail-open)."""
        try:
            analytics: AnalyticsStore | None = self.hass.data.get(
                DOMAIN, {}
            ).get("analytics")
            if not analytics:
                return

            # Extract response text — prefer full response, fall back to speech
            response_text = self._last_full_response
            if not response_text and result.response and result.response.speech:
                response_text = result.response.speech.get("plain", {}).get(
                    "speech", ""
                )

            # Build tags from route info
            tag = self._last_route_tag or "unknown"

            await analytics.async_append_shared_context(
                source="assist",
                prompt_summary=user_prompt,
                response_summary=response_text or "",
                conversation_id=conversation_id or "",
                tags=tag,
            )
        except Exception:
            _LOGGER.debug("Shared context write failed (non-fatal)")

    def _build_cross_interface_context(self, entries: list[dict]) -> str:
        """Format shared context entries as background context string."""
        if not entries:
            return ""
        lines = [
            "Recent activity from other interface (for background context only):"
        ]
        for e in entries:
            src = e.get("source", "unknown")
            ts = e.get("timestamp", "")[:16]  # trim to minute
            prompt = e.get("prompt", "")
            resp = e.get("response", "")
            line = f"- [{ts}] ({src}) User: {prompt}"
            if resp:
                line += f" → {resp}"
            lines.append(line)
        return "\n".join(lines)

    async def _async_enrich_with_shared_context(
        self,
        system_prompt: str,
        exclude_source: str = "assist",
    ) -> str:
        """Append recent cross-interface context to the system prompt (fail-open)."""
        try:
            analytics: AnalyticsStore | None = self.hass.data.get(
                DOMAIN, {}
            ).get("analytics")
            if not analytics:
                return system_prompt
            entries = await analytics.async_read_shared_context(
                exclude_source=exclude_source, limit=10
            )
            context_block = self._build_cross_interface_context(entries)
            if context_block:
                return system_prompt + "\n\n" + context_block
        except Exception:
            _LOGGER.debug("Shared context read failed (non-fatal)")
        return system_prompt

    async def _async_get_shared_context_prefix(self) -> str:
        """Get shared context formatted as a prompt prefix for ACP sessions."""
        try:
            analytics: AnalyticsStore | None = self.hass.data.get(
                DOMAIN, {}
            ).get("analytics")
            if not analytics:
                return ""
            entries = await analytics.async_read_shared_context(
                exclude_source="assist", limit=10
            )
            return self._build_cross_interface_context(entries)
        except Exception:
            _LOGGER.debug("Shared context prefix failed (non-fatal)")
            return ""

    async def _async_handle_hybrid(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        data: dict[str, Any],
    ) -> ConversationResult:
        """Hybrid routing: local → Azure fast model → CLI expert fallback."""
        analytics = self.hass.data.get(DOMAIN, {}).get("analytics")
        metrics = RequestMetrics() if RequestMetrics else None
        trace = TraceLog(
            user_prompt=user_input.text[:500],
            conversation_id=chat_log.conversation_id or "",
        ) if TraceLog else None

        decision = classify_intent(user_input.text)
        if metrics:
            metrics.route = decision.route.value
        if trace:
            trace.route = decision.route.value
            trace.route_pattern = decision.matched_pattern
            trace.route_confidence = decision.confidence
            trace.step(f"Router: {decision.route.value} (pattern={decision.matched_pattern}, conf={decision.confidence})")

        self._last_route_tag = decision.route.value

        _LOGGER.info(
            "Hybrid router: route=%s pattern=%s prompt='%s'",
            decision.route.value,
            decision.matched_pattern,
            user_input.text[:80],
        )

        azure_failed = False

        try:
            if decision.route == Route.LOCAL:
                # ── Fast local path: use Azure for tool-calling ──────────
                router_endpoint = data.get(CONF_AZURE_ROUTER_ENDPOINT)
                router_key = data.get(CONF_AZURE_ROUTER_KEY)

                if router_endpoint and router_key:
                    try:
                        router_model = data.get(
                            CONF_AZURE_ROUTER_MODEL, DEFAULT_AZURE_ROUTER_MODEL
                        )
                        if metrics:
                            metrics.model = router_model
                        if trace:
                            trace.model = router_model
                            trace.step(f"LOCAL→Azure: using {router_model}")
                        result = await self._async_handle_azure_fast(
                            user_input, chat_log, data,
                            router_endpoint, router_key, router_model,
                        )
                        if trace:
                            trace.step("Azure response received")
                        # Check if Azure deflected
                        resp_text = _extract_response_text(result)
                        if _is_deflection(resp_text):
                            _LOGGER.info(
                                "Azure deflected on LOCAL route, escalating to CLI: %s",
                                resp_text[:120],
                            )
                            if trace:
                                trace.step(f"Azure DEFLECTED: '{resp_text[:80]}' — escalating to CLI")
                            # Fall through to CLI
                        else:
                            return result
                    except Exception as err:
                        azure_failed = True
                        _LOGGER.warning(
                            "Azure fast model failed on LOCAL route, falling back to CLI: %s",
                            err,
                        )
                        if trace:
                            trace.step(f"Azure FAILED on LOCAL: {err} — falling back to CLI")
                        # Fall through to CLI
                else:
                    # No Azure — fall through to CLI for LOCAL too
                    _LOGGER.debug("No Azure router, sending LOCAL to CLI")
                    self._last_route_tag = "cli"
                    if metrics:
                        metrics.route = Route.CLI.value
                        metrics.model = "copilot-cli"
                    if trace:
                        trace.step("No Azure creds — falling back to CLI")
                        trace.route = Route.CLI.value
                        trace.model = "copilot-cli"
                    result = await self._async_handle_acp(
                        user_input, chat_log, data
                    )
                    if trace:
                        resp = _extract_response_text(result)
                        if resp:
                            trace.response_summary = resp[:500]
                        trace.step("CLI response received")
                    return result

            if decision.route == Route.AZURE:
                # ── Azure fast model for moderate queries ─────────────────
                router_endpoint = data.get(CONF_AZURE_ROUTER_ENDPOINT)
                router_key = data.get(CONF_AZURE_ROUTER_KEY)

                if router_endpoint and router_key:
                    try:
                        router_model = data.get(
                            CONF_AZURE_ROUTER_MODEL, DEFAULT_AZURE_ROUTER_MODEL
                        )
                        if metrics:
                            metrics.model = router_model
                        if trace:
                            trace.model = router_model
                            trace.step(f"AZURE: using {router_model}")
                        result = await self._async_handle_azure_fast(
                            user_input, chat_log, data,
                            router_endpoint, router_key, router_model,
                        )
                        if trace:
                            trace.step("Azure response received")
                        # Check if Azure deflected
                        resp_text = _extract_response_text(result)
                        if _is_deflection(resp_text):
                            azure_failed = True
                            _LOGGER.info(
                                "Azure deflected, escalating to CLI: %s",
                                resp_text[:120],
                            )
                            if trace:
                                trace.step(f"Azure DEFLECTED: '{resp_text[:80]}' — escalating to CLI")
                            # Fall through to CLI
                        else:
                            return result
                    except Exception as err:
                        azure_failed = True
                        _LOGGER.warning(
                            "Azure fast model failed, falling back to CLI: %s",
                            err,
                        )
                        if trace:
                            trace.step(f"Azure FAILED: {err} — falling back to CLI")
                        # Fall through to CLI
                else:
                    _LOGGER.debug("No Azure router configured, using CLI")
                    if trace:
                        trace.step("No Azure creds — using CLI")

            # ── CLI expert fallback (Route.CLI or Azure failed) ──────────
            self._last_route_tag = "cli"
            if metrics:
                metrics.route = Route.CLI.value
                metrics.model = "copilot-cli"
            if trace:
                trace.step("CLI: sending to Copilot CLI via ACP")
                trace.model = "copilot-cli"
            result = await self._async_handle_acp(user_input, chat_log, data)
            resp = _extract_response_text(result)
            if trace:
                if resp:
                    trace.response_summary = resp[:500]
                trace.step("CLI response received")

            # Store CLI fallback answer in knowledge when Azure failed
            if azure_failed and analytics and resp and len(resp) > 10:
                await analytics.async_add_knowledge(
                    query=user_input.text[:500],
                    answer=resp[:1000],
                    tags=["cli_fallback"],
                    source="cli_fallback",
                )
                _LOGGER.info(
                    "Stored CLI fallback response in knowledge store "
                    "(prompt=%d chars, answer=%d chars)",
                    len(user_input.text),
                    len(resp),
                )

            return result

        except Exception as err:
            _LOGGER.exception("Hybrid routing error")
            if metrics:
                metrics.success = False
                metrics.error_msg = str(err)
            if trace:
                trace.success = False
                trace.error_msg = str(err)
                trace.step(f"FATAL ERROR: {err}")

            chat_log.async_add_assistant_content_without_tools(
                AssistantContent(
                    agent_id=user_input.agent_id,
                    content="Sorry, an error occurred processing your request.",
                )
            )
            response_obj = intent.IntentResponse(language=user_input.language)
            response_obj.async_set_speech(
                "Sorry, an error occurred processing your request."
            )
            return ConversationResult(
                response=response_obj,
                conversation_id=chat_log.conversation_id,
            )
        finally:
            if trace:
                self._last_route_trace = list(trace.steps)
            if analytics and metrics:
                await analytics.async_log(user_input.text, metrics)
            if analytics and trace:
                await analytics.async_log_trace(trace)
            # Diagnose and notify on hard failures
            if metrics and not metrics.success:
                await self._async_diagnose_and_notify(
                    error_msg=metrics.error_msg,
                    route=metrics.route,
                    user_prompt=user_input.text,
                    conversation_id=chat_log.conversation_id or "",
                    data=data,
                )
                # Also log failures to Notion
                error_result = ConversationResult(
                    response=intent.IntentResponse(language=user_input.language),
                    conversation_id=chat_log.conversation_id,
                )
                await self._async_maybe_log_to_notion(
                    user_input.text, error_result, data,
                    is_failure=True,
                    error_msg=metrics.error_msg or "Unknown error",
                )

    async def _async_handle_azure_fast(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        data: dict[str, Any],
        endpoint: str,
        api_key: str,
        model: str,
    ) -> ConversationResult:
        """Handle a request through the Azure AI Foundry fast model."""
        temperature = data.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        max_tokens = int(data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        system_prompt = self._resolve_system_prompt(data)

        _LOGGER.debug(
            "Azure fast: endpoint=%s model=%s prompt='%s'",
            endpoint, model, user_input.text[:80],
        )

        # Provide HA LLM tools
        llm_api_ids = data.get(CONF_LLM_HASS_API) or [llm.LLM_API_ASSIST]
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            llm_api_ids,
            system_prompt,
            user_input.extra_system_prompt,
        )
        if chat_log.llm_api:
            system_prompt = chat_log.llm_api.api_prompt + "\n\n" + system_prompt

        # Inject satellite device context (area awareness)
        device_context = self._get_device_context(user_input)
        if device_context:
            system_prompt += device_context
            _LOGGER.debug("Azure fast: injected device context")

        # Always append family-friendly rules (after HA override so they stick)
        system_prompt += FAMILY_FRIENDLY_SUFFIX

        # Add shopping list guidance so Azure knows the service calls
        system_prompt += SHOPPING_LIST_GUIDANCE

        # Inject joke exclusions when user asks for a joke
        if self._is_joke_request(user_input.text):
            joke_exclusions = await self._async_get_joke_exclusions()
            if joke_exclusions:
                system_prompt += joke_exclusions

        # Inject cross-interface context (CLI activity) into system prompt
        system_prompt = await self._async_enrich_with_shared_context(
            system_prompt, exclude_source="assist"
        )

        # Inject relevant knowledge from prior CLI fallback answers
        analytics = self.hass.data.get(DOMAIN, {}).get("analytics")
        if analytics:
            try:
                knowledge_entries = await analytics.async_search_knowledge(
                    user_input.text, limit=3
                )
                if knowledge_entries:
                    knowledge_lines = []
                    for entry in knowledge_entries:
                        knowledge_lines.append(
                            f"- Q: {entry['query']}\n  A: {entry['answer']}"
                        )
                    system_prompt += (
                        "\n\n## Relevant Knowledge\n"
                        "Previous answers for similar queries:\n"
                        + "\n".join(knowledge_lines)
                    )
                    _LOGGER.debug(
                        "Azure fast: injected %d knowledge entries",
                        len(knowledge_entries),
                    )
            except Exception:
                _LOGGER.debug(
                    "Failed to search knowledge for Azure prompt",
                    exc_info=True,
                )

        messages = self._build_messages(system_prompt, chat_log)
        tools = self._build_tools(chat_log)

        _LOGGER.debug(
            "Azure fast: %d messages, %d tools, system_prompt=%d chars",
            len(messages),
            len(tools) if tools else 0,
            len(system_prompt),
        )

        async with aiohttp.ClientSession() as session:
            client = build_azure_client(session, endpoint, api_key, model=model)

            for _iteration in range(MAX_TOOL_ITERATIONS):
                _LOGGER.debug("Azure fast: iteration %d", _iteration + 1)
                response = await client.async_chat_completion(
                    model=model,
                    messages=messages,
                    tools=tools or None,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                choice = response.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls")

                if not tool_calls:
                    _LOGGER.info(
                        "Azure fast: final response %d chars",
                        len(content),
                    )
                    break

                _LOGGER.debug(
                    "Azure fast: %d tool calls: %s",
                    len(tool_calls),
                    [tc.get("function", {}).get("name") for tc in tool_calls],
                )

                messages.append(message)
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "")
                    tool_args_str = func.get("arguments", "{}")
                    try:
                        tool_args = json.loads(tool_args_str)
                    except json.JSONDecodeError:
                        tool_args = {}

                    tool_result = await self._execute_tool(
                        chat_log, tool_name, tool_args, user_input,
                        session, data,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })
            else:
                content = (
                    "I'm sorry, I reached the maximum number of tool calls. "
                    "Please try a simpler request."
                )

        # Split for voice: short spoken part vs full email content
        spoken, full = split_response_for_voice(content)
        self._last_full_response = full

        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=spoken)
        )
        response_obj = intent.IntentResponse(language=user_input.language)
        response_obj.async_set_speech(spoken)
        return ConversationResult(
            response=response_obj,
            conversation_id=chat_log.conversation_id,
        )

    async def _async_handle_direct_api(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        data: dict[str, Any],
    ) -> ConversationResult:
        """Route the prompt through the direct GitHub Models / Azure API."""
        model = data.get(CONF_MODEL, DEFAULT_MODEL)
        temperature = data.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        max_tokens = int(data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        system_prompt = self._resolve_system_prompt(data)
        expert_model = data.get(CONF_EXPERT_MODEL, "")

        # Provide HA LLM tools to the chat log
        # Default to the Assist API so every agent can control HA out of the box
        llm_api_ids = data.get(CONF_LLM_HASS_API) or [llm.LLM_API_ASSIST]
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            llm_api_ids,
            system_prompt,
            user_input.extra_system_prompt,
        )
        # Use the chat_log's generated prompt if available
        if chat_log.llm_api:
            system_prompt = chat_log.llm_api.api_prompt + "\n\n" + system_prompt

        # Inject satellite device context (area awareness)
        device_context = self._get_device_context(user_input)
        if device_context:
            system_prompt += device_context

        # Always append family-friendly rules (after HA override so they stick)
        system_prompt += FAMILY_FRIENDLY_SUFFIX

        # Add shopping list guidance so the model knows the service calls
        system_prompt += SHOPPING_LIST_GUIDANCE

        # Inject joke exclusions when user asks for a joke
        if self._is_joke_request(user_input.text):
            joke_exclusions = await self._async_get_joke_exclusions()
            if joke_exclusions:
                system_prompt += joke_exclusions

        # Append orchestrator instructions when expert model is configured
        if expert_model:
            system_prompt += ORCHESTRATOR_PROMPT_SUFFIX

        # Inject cross-interface context (CLI activity) into system prompt
        system_prompt = await self._async_enrich_with_shared_context(
            system_prompt, exclude_source="assist"
        )

        # Build messages from chat log
        messages = self._build_messages(system_prompt, chat_log)

        # Build tools from LLM API (+ synthetic orchestrator tools)
        tools = self._build_tools(chat_log, expert_model)

        async with aiohttp.ClientSession() as session:
            client = self._get_client(session)

            try:
                for _iteration in range(MAX_TOOL_ITERATIONS):
                    response = await client.async_chat_completion(
                        model=model,
                        messages=messages,
                        tools=tools or None,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                    choice = response.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    content = message.get("content", "")
                    tool_calls = message.get("tool_calls")

                    if not tool_calls:
                        # Final response — no more tool calls
                        break

                    # Process tool calls
                    messages.append(message)
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        tool_name = func.get("name", "")
                        tool_args_str = func.get("arguments", "{}")

                        try:
                            tool_args = json.loads(tool_args_str)
                        except json.JSONDecodeError:
                            tool_args = {}

                        _LOGGER.debug(
                            "Tool call: %s(%s)", tool_name, tool_args
                        )

                        tool_result = await self._execute_tool(
                            chat_log, tool_name, tool_args, user_input,
                            session, data,
                        )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": tool_result,
                            }
                        )
                else:
                    content = "I'm sorry, I reached the maximum number of tool calls. Please try a simpler request."

            except APIError as err:
                _LOGGER.error("API error: %s", err)
                content = f"Sorry, I encountered an error: {err}"
            except Exception:
                _LOGGER.exception("Unexpected error in conversation")
                content = "Sorry, an unexpected error occurred."

        # Split for voice: short spoken part vs full email content
        spoken, full = split_response_for_voice(content)
        self._last_full_response = full

        # Add the short spoken version to the chat log
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=spoken)
        )

        response_obj = intent.IntentResponse(language=user_input.language)
        response_obj.async_set_speech(spoken)

        return ConversationResult(
            response=response_obj,
            conversation_id=chat_log.conversation_id,
        )

    def _build_messages(
        self, system_prompt: str, chat_log: ChatLog
    ) -> list[dict[str, Any]]:
        """Convert chat log content into API message format."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

        for entry in chat_log.content:
            if isinstance(entry, UserContent):
                messages.append({"role": "user", "content": entry.content})
            elif isinstance(entry, AssistantContent):
                if entry.content:
                    messages.append(
                        {"role": "assistant", "content": str(entry.content)}
                    )
            elif isinstance(entry, ToolResultContent):
                # HA 2026+ stores tool_result as JsonObjectType (dict);
                # Azure/OpenAI API requires content to be a string.
                result = entry.tool_result
                if not isinstance(result, str):
                    result = json.dumps(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": entry.tool_call_id,
                        "content": result,
                    }
                )

        return messages

    def _build_tools(
        self, chat_log: ChatLog, expert_model: str = ""
    ) -> list[dict[str, Any]] | None:
        """Build tool definitions from the LLM API + synthetic orchestrator tools."""
        tools: list[dict[str, Any]] = []

        if chat_log.llm_api and chat_log.llm_api.tools:
            custom_serializer = getattr(
                chat_log.llm_api, "custom_serializer", None
            )
            for tool in chat_log.llm_api.tools:
                tool_def: dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                    },
                }
                if tool.parameters:
                    # tool.parameters is a vol.Schema — convert to JSON dict
                    if vol_to_openapi is not None:
                        try:
                            tool_def["function"]["parameters"] = vol_to_openapi(
                                tool.parameters,
                                custom_serializer=custom_serializer,
                            )
                        except Exception:
                            _LOGGER.debug(
                                "Failed to convert schema for tool %s, skipping",
                                tool.name,
                            )
                            continue
                    else:
                        tool_def["function"]["parameters"] = tool.parameters
                tools.append(tool_def)

        # Inject orchestrator tools when expert model is configured
        if expert_model:
            tools.append({
                "type": "function",
                "function": {
                    "name": KNOWLEDGE_TOOL_NAME,
                    "description": (
                        "Search past expert answers for similar questions. "
                        "Use this BEFORE ask_expert to check if a good answer "
                        "already exists."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query.",
                            }
                        },
                        "required": ["query"],
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": EXPERT_TOOL_NAME,
                    "description": (
                        "Delegate a complex question to a more powerful AI "
                        "model for deeper reasoning, analysis, or planning. "
                        "Only use when search_knowledge found nothing relevant "
                        "AND the task requires deep reasoning, or when the user "
                        "explicitly asks for expert help."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "The full question or task to send to "
                                    "the expert model."
                                ),
                            }
                        },
                        "required": ["query"],
                    },
                },
            })

        return tools if tools else None

    async def _execute_tool(
        self,
        chat_log: ChatLog,
        tool_name: str,
        tool_args: dict[str, Any],
        user_input: ConversationInput,
        http_session: aiohttp.ClientSession | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Execute a single tool call via the HA LLM API or synthetic tools."""
        # --- Synthetic tool: search_knowledge ---
        if tool_name == KNOWLEDGE_TOOL_NAME:
            return await self._handle_search_knowledge(tool_args)

        # --- Synthetic tool: ask_expert ---
        if tool_name == EXPERT_TOOL_NAME:
            return await self._handle_ask_expert(
                tool_args, chat_log, user_input, http_session, data
            )

        # --- Standard HA LLM tool ---
        if not chat_log.llm_api:
            return json.dumps({"error": "No LLM API configured"})

        try:
            tool_input = llm.ToolInput(
                tool_name=tool_name,
                tool_args=tool_args,
            )
            result = await chat_log.llm_api.async_call_tool(tool_input)
            return json.dumps(result)
        except HomeAssistantError as err:
            _LOGGER.warning("Tool call %s failed: %s", tool_name, err)
            return json.dumps({"error": str(err)})
        except Exception:
            _LOGGER.exception("Unexpected error executing tool %s", tool_name)
            return json.dumps({"error": f"Failed to execute {tool_name}"})

    async def _handle_search_knowledge(
        self, tool_args: dict[str, Any]
    ) -> str:
        """Search the knowledge store for past expert answers."""
        query = tool_args.get("query", "")
        if not query:
            return json.dumps({"results": [], "message": "Empty query"})

        # Prefer SQLite analytics store, fall back to legacy JSON
        analytics: AnalyticsStore | None = self.hass.data.get(DOMAIN, {}).get(
            "analytics"
        )
        if analytics:
            results = await analytics.async_search_knowledge(query)
        else:
            knowledge = self.hass.data.get(DOMAIN, {}).get("knowledge")
            results = knowledge.search(query) if knowledge else []

        if results:
            _LOGGER.debug(
                "Knowledge search for '%s' returned %d results", query, len(results)
            )
            return json.dumps({
                "results": [
                    {"query": r["query"], "answer": r["answer"]}
                    for r in results
                ]
            })
        return json.dumps({"results": [], "message": "No relevant knowledge found"})

    async def _handle_ask_expert(
        self,
        tool_args: dict[str, Any],
        chat_log: ChatLog,
        user_input: ConversationInput,
        http_session: aiohttp.ClientSession | None,
        data: dict[str, Any] | None,
    ) -> str:
        """Escalate a question to the expert model and log the result."""
        query = tool_args.get("query", "")
        if not query:
            return json.dumps({"error": "Empty query"})

        data = data or self._entry_data
        expert_model = data.get(CONF_EXPERT_MODEL, "")
        if not expert_model:
            return json.dumps({"error": "No expert model configured"})

        # Build context for the expert: system prompt + conversation history + query
        system_prompt = data.get(CONF_PROMPT, DEFAULT_PROMPT)
        if chat_log.llm_api:
            system_prompt = chat_log.llm_api.api_prompt

        expert_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        try:
            # Use existing session or create a new one
            if http_session:
                client = self._get_client(http_session)
                response = await client.async_chat_completion(
                    model=expert_model,
                    messages=expert_messages,
                    temperature=data.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                    max_tokens=int(data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                )
            else:
                async with aiohttp.ClientSession() as session:
                    client = self._get_client(session)
                    response = await client.async_chat_completion(
                        model=expert_model,
                        messages=expert_messages,
                        temperature=data.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                        max_tokens=int(data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
                    )

            choice = response.get("choices", [{}])[0]
            expert_answer = choice.get("message", {}).get("content", "")

            if not expert_answer:
                return json.dumps({"error": "Expert model returned empty response"})

            _LOGGER.info(
                "Expert escalation: model=%s, query='%s'",
                expert_model,
                query[:80],
            )

            # Auto-log to knowledge store (prefer SQLite)
            analytics: AnalyticsStore | None = self.hass.data.get(
                DOMAIN, {}
            ).get("analytics")
            if analytics:
                await analytics.async_add_knowledge(query, expert_answer)
            else:
                knowledge = self.hass.data.get(DOMAIN, {}).get("knowledge")
                if knowledge:
                    await knowledge.async_add_entry(query, expert_answer)

            return json.dumps({"answer": expert_answer})

        except APIError as err:
            _LOGGER.error("Expert model API error: %s", err)
            return json.dumps({"error": f"Expert model error: {err}"})
        except Exception:
            _LOGGER.exception("Unexpected error calling expert model")
            return json.dumps({"error": "Failed to reach expert model"})