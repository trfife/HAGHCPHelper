"""Config flow for GitHub Copilot Conversation integration."""

from __future__ import annotations

import logging
import os
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

from .acp_client import ACPClient, ACPError
from .api import APIError, async_fetch_github_models, build_azure_client, build_github_client
from .const import (
    ACP_DEFAULT_PORT,
    ADDON_SLUG,
    AUTH_METHOD_BROWSER,
    AUTH_METHOD_PAT,
    BACKEND_AZURE,
    BACKEND_COPILOT_CLI,
    BACKEND_GITHUB,
    BACKEND_HYBRID,
    CONF_ACP_HOST,
    CONF_ACP_PORT,
    CONF_AUTH_METHOD,
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
    FALLBACK_MODELS,
    GITHUB_OAUTH_CLIENT_ID,
    SUBENTRY_TYPE_CONVERSATION,
)
from .github_auth import (
    AuthorizationPending,
    DeviceFlowError,
    async_exchange_device_code,
    async_request_device_code,
)

_LOGGER = logging.getLogger(__name__)

BACKEND_OPTIONS = [
    {"value": BACKEND_HYBRID, "label": "Hybrid — Azure fast + CLI expert (recommended)"},
    {"value": BACKEND_COPILOT_CLI, "label": "Copilot CLI Add-on only"},
    {"value": BACKEND_GITHUB, "label": "GitHub Models (direct API)"},
    {"value": BACKEND_AZURE, "label": "Azure AI Endpoint"},
]

AUTH_OPTIONS = [
    {"value": AUTH_METHOD_BROWSER, "label": "Sign in with GitHub (browser)"},
    {"value": AUTH_METHOD_PAT, "label": "Personal Access Token"},
]


class GHCPConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GitHub Copilot Conversation."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._device_data: dict[str, Any] | None = None
        self._model_options: list[dict[str, str]] | None = None

    async def _async_get_model_options(self, token: str) -> list[dict[str, str]]:
        """Fetch model catalog and return selector options."""
        if self._model_options is not None:
            return self._model_options

        async with aiohttp.ClientSession() as session:
            models = await async_fetch_github_models(session, token)

        if models:
            self._model_options = [
                {"value": m["id"], "label": f"{m['name']} ({m['id']})"}
                for m in models
            ]
        else:
            # Fallback if catalog is unavailable
            self._model_options = [
                {"value": m, "label": m} for m in FALLBACK_MODELS
            ]
        return self._model_options

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle backend selection step."""
        if user_input is not None:
            self._data[CONF_BACKEND] = user_input[CONF_BACKEND]
            if self._data[CONF_BACKEND] == BACKEND_HYBRID:
                return await self.async_step_hybrid()
            if self._data[CONF_BACKEND] == BACKEND_COPILOT_CLI:
                return await self.async_step_copilot_cli()
            if self._data[CONF_BACKEND] == BACKEND_GITHUB:
                return await self.async_step_github()
            return await self.async_step_azure()

        # Auto-detect the add-on to pick the best default
        default_backend = BACKEND_HYBRID
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BACKEND, default=default_backend): SelectSelector(
                        SelectSelectorConfig(
                            options=BACKEND_OPTIONS,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_copilot_cli(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the Copilot CLI add-on ACP connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get(CONF_ACP_HOST, "localhost")
            port = int(user_input.get(CONF_ACP_PORT, ACP_DEFAULT_PORT))

            client = ACPClient(host, port)
            try:
                ok = await client.async_validate(timeout=10)
                if not ok:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("ACP validation error")
                errors["base"] = "cannot_connect"
            finally:
                await client.async_close()

            if not errors:
                self._data[CONF_ACP_HOST] = host
                self._data[CONF_ACP_PORT] = port
                return self.async_create_entry(
                    title="GitHub Copilot CLI",
                    data=self._data,
                )

        # Try to auto-detect the add-on IP via Supervisor API
        default_host = await self._async_discover_addon_host()

        return self.async_show_form(
            step_id="copilot_cli",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACP_HOST, default=default_host
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_ACP_PORT, default=ACP_DEFAULT_PORT
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=65535, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_hybrid(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure Hybrid backend — Azure fast router + CLI expert fallback."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate ACP connection first
            host = user_input.get(CONF_ACP_HOST, "localhost")
            port = int(user_input.get(CONF_ACP_PORT, ACP_DEFAULT_PORT))

            client = ACPClient(host, port)
            try:
                ok = await client.async_validate(timeout=10)
                if not ok:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.warning("ACP validation failed for hybrid setup")
                errors["base"] = "cannot_connect"
            finally:
                await client.async_close()

            # Validate Azure endpoint if provided
            azure_endpoint = user_input.get(CONF_AZURE_ROUTER_ENDPOINT, "")
            azure_key = user_input.get(CONF_AZURE_ROUTER_KEY, "")
            if azure_endpoint and azure_key and not errors:
                router_model = user_input.get(
                    CONF_AZURE_ROUTER_MODEL, DEFAULT_AZURE_ROUTER_MODEL
                )
                try:
                    async with aiohttp.ClientSession() as session:
                        az_client = build_azure_client(
                            session, azure_endpoint, azure_key,
                            model=router_model,
                        )
                        await az_client.async_validate(router_model)
                except APIError as err:
                    _LOGGER.error("Azure router validation failed: %s", err)
                    if err.status in (401, 403):
                        errors["base"] = "invalid_auth"
                    else:
                        errors["base"] = "azure_cannot_connect"
                except Exception:
                    _LOGGER.exception("Azure validation unexpected error")
                    errors["base"] = "azure_cannot_connect"

            if not errors:
                self._data[CONF_ACP_HOST] = host
                self._data[CONF_ACP_PORT] = port
                if azure_endpoint:
                    self._data[CONF_AZURE_ROUTER_ENDPOINT] = azure_endpoint
                    self._data[CONF_AZURE_ROUTER_KEY] = azure_key
                    self._data[CONF_AZURE_ROUTER_MODEL] = user_input.get(
                        CONF_AZURE_ROUTER_MODEL, DEFAULT_AZURE_ROUTER_MODEL
                    )
                return self.async_create_entry(
                    title="GitHub Copilot Hybrid",
                    data=self._data,
                )

        default_host = await self._async_discover_addon_host()

        return self.async_show_form(
            step_id="hybrid",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACP_HOST, default=default_host
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_ACP_PORT, default=ACP_DEFAULT_PORT
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=65535, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(CONF_AZURE_ROUTER_ENDPOINT): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                    vol.Optional(CONF_AZURE_ROUTER_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_AZURE_ROUTER_MODEL,
                        default=DEFAULT_AZURE_ROUTER_MODEL,
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_discover_addon_host(self) -> str:
        """Discover the Copilot CLI add-on IP via the Supervisor API.

        Queries the Supervisor for installed add-ons, finds the one
        with a slug ending in '_copilot_cli' or 'copilot_cli', and
        returns its IP address.  Falls back to 'localhost'.
        """
        supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
        if not supervisor_token:
            _LOGGER.debug("No SUPERVISOR_TOKEN — cannot auto-discover add-on")
            return "localhost"

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                # List all installed add-ons
                async with session.get(
                    "http://supervisor/addons",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.debug("Supervisor /addons returned %s", resp.status)
                        return "localhost"
                    result = await resp.json()

                addons = result.get("data", {}).get("addons", [])
                addon_slug = None
                for addon in addons:
                    slug = addon.get("slug", "")
                    if slug == ADDON_SLUG or slug.endswith(f"_{ADDON_SLUG}"):
                        addon_slug = slug
                        break

                if not addon_slug:
                    _LOGGER.debug("Copilot CLI add-on not found in installed add-ons")
                    return "localhost"

                # Get detailed info including IP address
                async with session.get(
                    f"http://supervisor/addons/{addon_slug}/info",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.debug("Supervisor addon info returned %s", resp.status)
                        return "localhost"
                    info = await resp.json()

                data = info.get("data", {})
                ip_addr = data.get("ip_address")
                if ip_addr:
                    _LOGGER.info(
                        "Auto-discovered Copilot CLI add-on at %s (slug=%s)",
                        ip_addr,
                        addon_slug,
                    )
                    return ip_addr

                hostname = data.get("hostname")
                if hostname:
                    return hostname

        except Exception:
            _LOGGER.debug("Failed to auto-discover add-on", exc_info=True)

        return "localhost"

    async def async_step_github(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose GitHub auth method — browser (OAuth) or PAT."""
        # If no OAuth App client_id is configured, skip straight to PAT
        if not GITHUB_OAUTH_CLIENT_ID:
            return await self.async_step_github_pat()

        if user_input is not None:
            if user_input[CONF_AUTH_METHOD] == AUTH_METHOD_BROWSER:
                return await self.async_step_github_device()
            return await self.async_step_github_pat()

        return self.async_show_form(
            step_id="github",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTH_METHOD, default=AUTH_METHOD_BROWSER
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=AUTH_OPTIONS,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_github_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """OAuth device flow — show code and URL, user clicks Submit after authorizing."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # User clicked Submit — attempt to exchange the device code
            try:
                async with aiohttp.ClientSession() as session:
                    token = await async_exchange_device_code(
                        session,
                        GITHUB_OAUTH_CLIENT_ID,
                        self._device_data["device_code"],
                    )
                self._data[CONF_GITHUB_TOKEN] = token
                return await self.async_step_github_model()
            except AuthorizationPending:
                errors["base"] = "not_yet_authorized"
            except DeviceFlowError as err:
                _LOGGER.error("GitHub device flow failed: %s", err)
                return self.async_abort(reason="device_flow_failed")

        if not self._device_data:
            # First visit — request a fresh device code
            try:
                async with aiohttp.ClientSession() as session:
                    self._device_data = await async_request_device_code(
                        session, GITHUB_OAUTH_CLIENT_ID
                    )
            except DeviceFlowError as err:
                _LOGGER.error("Failed to start device flow: %s", err)
                return self.async_abort(reason="device_flow_failed")

        return self.async_show_form(
            step_id="github_device",
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self._device_data["verification_uri"],
                "code": self._device_data["user_code"],
            },
            errors=errors,
        )

    async def async_step_github_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a model after browser-based auth."""
        errors: dict[str, str] = {}
        token = self._data[CONF_GITHUB_TOKEN]

        if user_input is not None:
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
                self._data[CONF_MODEL] = model
                expert = user_input.get(CONF_EXPERT_MODEL, "")
                if expert:
                    self._data[CONF_EXPERT_MODEL] = expert
                return self.async_create_entry(
                    title="GitHub Copilot Conversation",
                    data=self._data,
                )

        model_options = await self._async_get_model_options(token)

        return self.async_show_form(
            step_id="github_model",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=model_options,
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_EXPERT_MODEL, default=""): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": "", "label": "None (disabled)"}]
                            + model_options,
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
                expert = user_input.get(CONF_EXPERT_MODEL, "")
                if expert:
                    self._data[CONF_EXPERT_MODEL] = expert
                return self.async_create_entry(
                    title="GitHub Copilot Conversation",
                    data=self._data,
                )

        # For PAT step, we can only fetch models if we have a token from a previous attempt
        if errors and user_input:
            model_options = await self._async_get_model_options(user_input[CONF_GITHUB_TOKEN])
        else:
            model_options = [{"value": m, "label": m} for m in FALLBACK_MODELS]

        return self.async_show_form(
            step_id="github_pat",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GITHUB_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=model_options,
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_EXPERT_MODEL, default=""): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": "", "label": "None (disabled)"}]
                            + model_options,
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

        # Merge data + options for correct defaults when reopening
        merged = dict(self.config_entry.data)
        merged.update(self.config_entry.options)
        backend = merged.get(CONF_BACKEND, BACKEND_GITHUB)

        schema_dict: dict[Any, Any] = {}
        if backend == BACKEND_GITHUB:
            token = merged.get(CONF_GITHUB_TOKEN, "")
            # Fetch live model list
            model_options: list[dict[str, str]] = []
            if token:
                async with aiohttp.ClientSession() as session:
                    models = await async_fetch_github_models(session, token)
                if models:
                    model_options = [
                        {"value": m["id"], "label": f"{m['name']} ({m['id']})"}
                        for m in models
                    ]
            if not model_options:
                model_options = [{"value": m, "label": m} for m in FALLBACK_MODELS]

            schema_dict[
                vol.Required(
                    CONF_GITHUB_TOKEN,
                    default=token,
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
            schema_dict[
                vol.Optional(
                    CONF_MODEL,
                    default=merged.get(CONF_MODEL, DEFAULT_MODEL),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=model_options,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            schema_dict[
                vol.Optional(
                    CONF_EXPERT_MODEL,
                    default=merged.get(CONF_EXPERT_MODEL, ""),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": "", "label": "None (disabled)"}]
                    + model_options,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            schema_dict[
                vol.Required(
                    CONF_AZURE_ENDPOINT,
                    default=merged.get(CONF_AZURE_ENDPOINT, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
            schema_dict[
                vol.Required(
                    CONF_AZURE_API_KEY,
                    default=merged.get(CONF_AZURE_API_KEY, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
            schema_dict[
                vol.Required(
                    CONF_MODEL,
                    default=merged.get(CONF_MODEL, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))

        # Email notification settings (available for all backends)
        schema_dict[
            vol.Optional(
                CONF_EMAIL_NOTIFY_SERVICE,
                default=merged.get(CONF_EMAIL_NOTIFY_SERVICE, ""),
            )
        ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        schema_dict[
            vol.Optional(
                CONF_EMAIL_MODE,
                default=merged.get(CONF_EMAIL_MODE, DEFAULT_EMAIL_MODE),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": EMAIL_MODE_OFF, "label": "Off"},
                    {"value": EMAIL_MODE_ALWAYS, "label": "Always"},
                    {"value": EMAIL_MODE_LONG_ONLY, "label": "Long responses only"},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        schema_dict[
            vol.Optional(
                CONF_EMAIL_THRESHOLD,
                default=merged.get(CONF_EMAIL_THRESHOLD, DEFAULT_EMAIL_THRESHOLD),
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=100, max=10000, step=100, mode=NumberSelectorMode.BOX,
            )
        )

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
                    vol.Optional(CONF_EXPERT_MODEL, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
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
