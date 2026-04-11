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
    CONF_ACP_HOST,
    CONF_ACP_PORT,
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
    CONF_GITHUB_TOKEN,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_AZURE_ROUTER_MODEL,
    DEFAULT_EMAIL_MODE,
    DEFAULT_EMAIL_THRESHOLD,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    EMAIL_MODE_ALWAYS,
    EMAIL_MODE_LONG_ONLY,
    EMAIL_MODE_OFF,
    EXPERT_TOOL_NAME,
    KNOWLEDGE_TOOL_NAME,
    MAX_EMAIL_THINKING_CHARS,
    ORCHESTRATOR_PROMPT_SUFFIX,
    SUBENTRY_TYPE_CONVERSATION,
    VOICE_DETAIL_SEPARATOR,
)
from .router import Route, classify_intent

_LOGGER = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10

# Max sentences to use as spoken portion when no separator is present
_VOICE_MAX_SENTENCES = 2

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

        _LOGGER.info(
            "Incoming message: backend=%s agent=%s prompt='%s'",
            backend,
            self._attr_name,
            user_input.text[:100],
        )

        # Reset thinking for this turn
        self._last_thinking = ""
        self._last_full_response = ""

        # ACP mode — forward prompt to Copilot CLI
        if backend == BACKEND_COPILOT_CLI:
            result = await self._async_handle_acp(user_input, chat_log, data)
        # Hybrid mode — router decides: local → azure → cli fallback
        elif backend == BACKEND_HYBRID:
            result = await self._async_handle_hybrid(user_input, chat_log, data)
        else:
            result = await self._async_handle_direct_api(user_input, chat_log, data)

        # Send email notification if configured
        await self._async_maybe_send_email(user_input.text, result, data)

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
            self._acp_session_id = session_id

            acp_response = await client.async_prompt(user_input.text)
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
        """Send an email with the response and thinking log if configured."""
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

        _LOGGER.info(
            "Hybrid router: route=%s pattern=%s prompt='%s'",
            decision.route.value,
            decision.matched_pattern,
            user_input.text[:80],
        )

        try:
            if decision.route == Route.LOCAL:
                # ── Fast local path: use Azure for tool-calling ──────────
                router_endpoint = data.get(CONF_AZURE_ROUTER_ENDPOINT)
                router_key = data.get(CONF_AZURE_ROUTER_KEY)

                if router_endpoint and router_key:
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
                    return result
                else:
                    # No Azure — fall through to CLI for LOCAL too
                    _LOGGER.debug("No Azure router, sending LOCAL to CLI")
                    if metrics:
                        metrics.route = Route.CLI.value
                        metrics.model = "copilot-cli"
                    if trace:
                        trace.step("No Azure creds — falling back to CLI")
                        trace.route = Route.CLI.value
                        trace.model = "copilot-cli"
                    return await self._async_handle_acp(
                        user_input, chat_log, data
                    )

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
                        return result
                    except Exception as err:
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
            if metrics:
                metrics.route = Route.CLI.value
                metrics.model = "copilot-cli"
            if trace:
                trace.step("CLI: sending to Copilot CLI via ACP")
                trace.model = "copilot-cli"
            result = await self._async_handle_acp(user_input, chat_log, data)
            if trace:
                trace.step("CLI response received")
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
            if analytics and metrics:
                await analytics.async_log(user_input.text, metrics)
            if analytics and trace:
                await analytics.async_log_trace(trace)

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
        system_prompt = data.get(CONF_PROMPT, DEFAULT_PROMPT)

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
            system_prompt = chat_log.llm_api.api_prompt

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
        system_prompt = data.get(CONF_PROMPT, DEFAULT_PROMPT)
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
            system_prompt = chat_log.llm_api.api_prompt

        # Append orchestrator instructions when expert model is configured
        if expert_model:
            system_prompt += ORCHESTRATOR_PROMPT_SUFFIX

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
                        {"role": "assistant", "content": entry.content}
                    )
            elif isinstance(entry, ToolResultContent):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": entry.tool_call_id,
                        "content": entry.tool_result,
                    }
                )

        return messages

    def _build_tools(
        self, chat_log: ChatLog, expert_model: str = ""
    ) -> list[dict[str, Any]] | None:
        """Build tool definitions from the LLM API + synthetic orchestrator tools."""
        tools: list[dict[str, Any]] = []

        if chat_log.llm_api and chat_log.llm_api.tools:
            for tool in chat_log.llm_api.tools:
                tool_def: dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                    },
                }
                if tool.parameters:
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