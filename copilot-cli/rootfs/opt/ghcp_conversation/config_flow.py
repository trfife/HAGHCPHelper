"""Config flow for GitHub Copilot Conversation integration."""

from __future__ import annotations

import asyncio
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
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_PAT,
    BACKEND_AZURE,
    BACKEND_GITHUB,
    CONF_AUTH_METHOD,
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
    GITHUB_OAUTH_CLIENT_ID,
    RECOMMENDED_MODELS,
    SUBENTRY_TYPE_CONVERSATION,
)
from .github_auth import (
    DeviceFlowDenied,
    DeviceFlowError,
    DeviceFlowExpired,
    async_poll_for_token,
    async_request_device_code,
)

_LOGGER = logging.getLogger(__name__)

BACKEND_OPTIONS = [
    {"value": BACKEND_GITHUB, "label": "GitHub Models"},
    {"value": BACKEND_AZURE, "label": "Azure AI Endpoint"},
]

AUTH_METHOD_OPTIONS = [
    {"value": AUTH_METHOD_OAUTH, "label": "Sign in with GitHub (recommended)"},
    {"value": AUTH_METHOD_PAT, "label": "Personal Access Token"},
]

MODEL_OPTIONS = [{"value": m, "label": m} for m in RECOMMENDED_MODELS]


class GHCPConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GitHub Copilot Conversation."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._device_code_data: dict[str, Any] | None = None
        self._oauth_token: str | None = None
        self._poll_task: asyncio.Task | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle backend selection step."""
        if user_input is not None:
            self._data[CONF_BACKEND] = user_input[CONF_BACKEND]
            if self._data[CONF_BACKEND] == BACKEND_GITHUB:
                return await self.async_step_github_auth()
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

    async def async_step_github_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose GitHub authentication method."""
        if user_input is not None:
            method = user_input[CONF_AUTH_METHOD]
            if method == AUTH_METHOD_OAUTH:
                return await self.async_step_github_device()
            return await self.async_step_github_pat()

        return self.async_show_form(
            step_id="github_auth",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTH_METHOD, default=AUTH_METHOD_OAUTH
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=AUTH_METHOD_OPTIONS,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_github_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initiate GitHub OAuth device flow."""
        if self._device_code_data is None:
            try:
                async with aiohttp.ClientSession() as session:
                    self._device_code_data = await async_request_device_code(
                        session, GITHUB_OAUTH_CLIENT_ID
                    )
            except DeviceFlowError as err:
                _LOGGER.error("Failed to start device flow: %s", err)
                return self.async_abort(reason="device_flow_failed")

        if self._poll_task is None or self._poll_task.done():
            self._poll_task = self.hass.async_create_task(
                self._async_poll_device_flow()
            )

        if not self._poll_task.done():
            return self.async_show_progress(
                step_id="github_device",
                progress_action="wait_for_auth",
                description_placeholders={
                    "url": self._device_code_data.get(
                        "verification_uri", "https://github.com/login/device"
                    ),
                    "code": self._device_code_data.get("user_code", ""),
                },
            )

        try:
            self._oauth_token = self._poll_task.result()
        except (DeviceFlowExpired, DeviceFlowDenied, DeviceFlowError) as err:
            _LOGGER.error("Device flow failed: %s", err)
            self._device_code_data = None
            self._poll_task = None
            return self.async_show_progress_done(next_step_id="github_device_error")

        return self.async_show_progress_done(next_step_id="github_model")

    async def _async_poll_device_flow(self) -> str:
        """Background task: poll GitHub until auth completes."""
        assert self._device_code_data is not None
        try:
            async with aiohttp.ClientSession() as session:
                token = await async_poll_for_token(
                    session,
                    GITHUB_OAUTH_CLIENT_ID,
                    self._device_code_data["device_code"],
                    interval=self._device_code_data.get("interval", 5),
                    expires_in=self._device_code_data.get("expires_in", 900),
                )
        finally:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
            )
        return token

    async def async_step_github_device_error(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device flow error — let user retry."""
        return self.async_abort(reason="device_flow_failed")

    async def async_step_github_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select model after successful OAuth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            model = user_input.get(CONF_MODEL, DEFAULT_MODEL)
            token = self._oauth_token or ""
            try:
                async with aiohttp.ClientSession() as session:
                    client = build_github_client(session, token)
                    await client.async_validate(model)
            except APIError as err:
                _LOGGER.error("Model validation failed: %s", err)
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
                self._data[CONF_AUTH_METHOD] = AUTH_METHOD_OAUTH
                return self.async_create_entry(
                    title="GitHub Copilot Conversation",
                    data=self._data,
                )

        return self.async_show_form(
            step_id="github_model",
            data_schema=vol.Schema(
                {
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

    async def async_step_github_pat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure GitHub Models with a Personal Access Token."""
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
                self._data[CONF_AUTH_METHOD] = AUTH_METHOD_PAT
                return self.async_create_entry(
                    title="GitHub Copilot Conversation",
                    data=self._data,
                )

        return self.async_show_form(
            step_id="github_pat",
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
