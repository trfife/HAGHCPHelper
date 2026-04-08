"""Config flow for GitHub Copilot Conversation integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import APIError, build_azure_client, build_github_client
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
    RECOMMENDED_MODELS,
    SUBENTRY_TYPE_CONVERSATION,
)

_LOGGER = logging.getLogger(__name__)

BACKEND_OPTIONS = [
    {"value": BACKEND_GITHUB, "label": "GitHub Models"},
    {"value": BACKEND_AZURE, "label": "Azure AI Endpoint"},
]

MODEL_OPTIONS = [{"value": m, "label": m} for m in RECOMMENDED_MODELS]


class GHCPConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GitHub Copilot Conversation."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle backend selection step."""
        if user_input is not None:
            self._data[CONF_BACKEND] = user_input[CONF_BACKEND]
            if self._data[CONF_BACKEND] == BACKEND_GITHUB:
                return await self.async_step_github()
            return await self.async_step_azure()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BACKEND, default=BACKEND_GITHUB): SelectSelector(
                        SelectSelectorConfig(
                            options=BACKEND_OPTIONS,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_github(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure GitHub Models — token and model on one page."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_GITHUB_TOKEN]
            model = user_input.get(CONF_MODEL, DEFAULT_MODEL)
            try:
                async with aiohttp.ClientSession() as session:
                    client = build_github_client(session, token)
                    await client.async_validate(model)
            except APIError as err:
                _LOGGER.error("GitHub Models validation failed: %s", err)
                if err.status in (401, 403):
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during validation")
                errors["base"] = "unknown"
            else:
                self._data[CONF_GITHUB_TOKEN] = token
                self._data[CONF_MODEL] = model
                return self.async_create_entry(
                    title="GitHub Copilot Conversation",
                    data=self._data,
                )

        return self.async_show_form(
            step_id="github",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GITHUB_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=MODEL_OPTIONS,
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_azure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure Azure AI backend."""
        errors: dict[str, str] = {}

        if user_input is not None:
            endpoint = user_input[CONF_AZURE_ENDPOINT]
            api_key = user_input[CONF_AZURE_API_KEY]
            model = user_input.get(CONF_MODEL, "")
            try:
                async with aiohttp.ClientSession() as session:
                    client = build_azure_client(session, endpoint, api_key)
                    await client.async_validate(model)
            except APIError as err:
                _LOGGER.error("Azure AI validation failed: %s", err)
                if err.status in (401, 403):
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during validation")
                errors["base"] = "unknown"
            else:
                self._data.update(user_input)
                return self.async_create_entry(
                    title="GitHub Copilot Conversation (Azure)",
                    data=self._data,
                )

        return self.async_show_form(
            step_id="azure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AZURE_ENDPOINT): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                    vol.Required(CONF_AZURE_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_MODEL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return GHCPOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type]:
        """Return subentry types."""
        return {SUBENTRY_TYPE_CONVERSATION: GHCPConversationSubentryFlow}


class GHCPOptionsFlow(OptionsFlow):
    """Handle options for GitHub Copilot Conversation."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration-level options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        entry_data = self.config_entry.data
        backend = entry_data.get(CONF_BACKEND, BACKEND_GITHUB)

        schema_dict: dict[Any, Any] = {}
        if backend == BACKEND_GITHUB:
            schema_dict[
                vol.Required(
                    CONF_GITHUB_TOKEN,
                    default=entry_data.get(CONF_GITHUB_TOKEN, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
            schema_dict[
                vol.Optional(
                    CONF_MODEL,
                    default=entry_data.get(CONF_MODEL, DEFAULT_MODEL),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=MODEL_OPTIONS,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            schema_dict[
                vol.Required(
                    CONF_AZURE_ENDPOINT,
                    default=entry_data.get(CONF_AZURE_ENDPOINT, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
            schema_dict[
                vol.Required(
                    CONF_AZURE_API_KEY,
                    default=entry_data.get(CONF_AZURE_API_KEY, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
            schema_dict[
                vol.Required(
                    CONF_MODEL,
                    default=entry_data.get(CONF_MODEL, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )


class GHCPConversationSubentryFlow:
    """Handle subentry flow for creating conversation agent entities."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new conversation agent subentry."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get("title", "Copilot Agent"),
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("title", default="Copilot Agent"): TextSelector(),
                    vol.Optional(
                        CONF_LLM_HASS_API,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": api.id, "label": api.name}
                                for api in llm.async_get_apis(self.hass)
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_PROMPT): TemplateSelector(),
                    vol.Optional(
                        CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Optional(
                        CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=128, max=16384, step=128, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
        )
