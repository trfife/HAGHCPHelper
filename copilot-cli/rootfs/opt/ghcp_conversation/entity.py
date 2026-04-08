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

from .api import APIError, ChatCompletionClient, build_azure_client, build_github_client
from .const import (
    BACKEND_AZURE,
    BACKEND_GITHUB,
    CONF_AZURE_API_KEY,
    CONF_AZURE_ENDPOINT,
    CONF_BACKEND,
    CONF_GITHUB_TOKEN,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    SUBENTRY_TYPE_CONVERSATION,
)

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
        model = data.get(CONF_MODEL, DEFAULT_MODEL)
        temperature = data.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        max_tokens = int(data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        system_prompt = data.get(CONF_PROMPT, DEFAULT_PROMPT)

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

        # Build messages from chat log
        messages = self._build_messages(system_prompt, chat_log)

        # Build tools from LLM API
        tools = self._build_tools(chat_log)

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
                            chat_log, tool_name, tool_args, user_input
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

    def _build_tools(self, chat_log: ChatLog) -> list[dict[str, Any]] | None:
        """Build tool definitions from the LLM API."""
        if not chat_log.llm_api or not chat_log.llm_api.tools:
            return None

        tools: list[dict[str, Any]] = []
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

        return tools if tools else None

    async def _execute_tool(
        self,
        chat_log: ChatLog,
        tool_name: str,
        tool_args: dict[str, Any],
        user_input: ConversationInput,
    ) -> str:
        """Execute a single tool call via the HA LLM API."""
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
