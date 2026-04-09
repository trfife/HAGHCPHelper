"""Conversation entity for GitHub Copilot Conversation."""

from __future__ import annotations

import json
import logging
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

from .acp_client import ACPClient, ACPError
from .analytics import AnalyticsStore, RequestMetrics
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
    CONF_EXPERT_MODEL,
    CONF_GITHUB_TOKEN,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_AZURE_ROUTER_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    EXPERT_TOOL_NAME,
    KNOWLEDGE_TOOL_NAME,
    ORCHESTRATOR_PROMPT_SUFFIX,
    SUBENTRY_TYPE_CONVERSATION,
)
from .router import Route, classify_intent

_LOGGER = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10


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

        if backend == BACKEND_AZURE:
            return build_azure_client(
                session,
                data[CONF_AZURE_ENDPOINT],
                data[CONF_AZURE_API_KEY],
            )
        return build_github_client(session, data[CONF_GITHUB_TOKEN])

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Process an incoming chat message."""
        data = self._entry_data
        backend = data.get(CONF_BACKEND, BACKEND_GITHUB)

        # ACP mode — forward prompt to Copilot CLI
        if backend == BACKEND_COPILOT_CLI:
            return await self._async_handle_acp(user_input, chat_log, data)

        # Hybrid mode — router decides: local → azure → cli fallback
        if backend == BACKEND_HYBRID:
            return await self._async_handle_hybrid(user_input, chat_log, data)

        return await self._async_handle_direct_api(user_input, chat_log, data)

    async def _async_handle_acp(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        data: dict[str, Any],
    ) -> ConversationResult:
        """Route the prompt through the Copilot CLI ACP server."""
        host = data.get(CONF_ACP_HOST, "localhost")
        port = int(data.get(CONF_ACP_PORT, ACP_DEFAULT_PORT))

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

            content = await client.async_prompt(user_input.text)
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

    async def _async_handle_hybrid(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        data: dict[str, Any],
    ) -> ConversationResult:
        """Hybrid routing: local → Azure fast model → CLI expert fallback."""
        analytics: AnalyticsStore | None = self.hass.data.get(DOMAIN, {}).get(
            "analytics"
        )
        metrics = RequestMetrics()

        decision = classify_intent(user_input.text)
        metrics.route = decision.route.value

        _LOGGER.info(
            "Hybrid router: route=%s pattern=%s prompt='%s'",
            decision.route.value,
            decision.matched_pattern,
            user_input.text[:80],
        )

        try:
            if decision.route == Route.LOCAL:
                # ── Fast local path: direct HA tool call via LLM API ─────
                result = await self._async_handle_direct_api(
                    user_input, chat_log, data
                )
                metrics.model = data.get(CONF_MODEL, DEFAULT_MODEL)
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
                        metrics.model = router_model
                        result = await self._async_handle_azure_fast(
                            user_input, chat_log, data,
                            router_endpoint, router_key, router_model,
                        )
                        return result
                    except (APIError, Exception) as err:
                        _LOGGER.warning(
                            "Azure fast model failed, falling back to CLI: %s",
                            err,
                        )
                        # Fall through to CLI
                else:
                    _LOGGER.debug(
                        "No Azure router configured, falling back to direct API"
                    )
                    result = await self._async_handle_direct_api(
                        user_input, chat_log, data
                    )
                    metrics.model = data.get(CONF_MODEL, DEFAULT_MODEL)
                    return result

            # ── CLI expert fallback (Route.CLI or Azure failed) ──────────
            metrics.route = Route.CLI.value
            metrics.model = "copilot-cli"
            return await self._async_handle_acp(user_input, chat_log, data)

        except Exception as err:
            _LOGGER.exception("Hybrid routing error")
            metrics.success = False
            metrics.error_msg = str(err)

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
            if analytics:
                await analytics.async_log(user_input.text, metrics)

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

        # Provide HA LLM tools
        llm_api_ids = data.get(CONF_LLM_HASS_API) or [llm.LLM_API_ASSIST]
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            llm_api_ids,
            system_prompt,
            user_input.extra_system_prompt,
        )
        if chat_log.llm_api:
            system_prompt = chat_log.llm_api.prompt

        messages = self._build_messages(system_prompt, chat_log)
        tools = self._build_tools(chat_log)

        async with aiohttp.ClientSession() as session:
            client = build_azure_client(session, endpoint, api_key)

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
                    break

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

        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=content)
        )
        response_obj = intent.IntentResponse(language=user_input.language)
        response_obj.async_set_speech(content)
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
            system_prompt = chat_log.llm_api.prompt

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

        # Add the final response to the chat log
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=content)
        )

        response_obj = intent.IntentResponse(language=user_input.language)
        response_obj.async_set_speech(content)

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
                        "content": entry.result,
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

        knowledge = self.hass.data.get(DOMAIN, {}).get("knowledge")
        if not knowledge:
            return json.dumps({"results": [], "message": "Knowledge store unavailable"})

        results = knowledge.search(query)
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
            system_prompt = chat_log.llm_api.prompt

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

            # Auto-log to knowledge store
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