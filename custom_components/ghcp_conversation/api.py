"""API client for GitHub Models and Azure AI chat completions."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import GITHUB_API_VERSION, GITHUB_CATALOG_URL, GITHUB_MODELS_URL

_LOGGER = logging.getLogger(__name__)


AZURE_API_VERSION = "2025-01-01-preview"


class APIError(Exception):
    """API error with status code."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class ChatCompletionClient:
    """Client for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = GITHUB_MODELS_URL,
        api_key: str = "",
        is_github: bool = True,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._api_key = api_key
        self._is_github = is_github

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._is_github:
            headers["Authorization"] = f"Bearer {self._api_key}"
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = GITHUB_API_VERSION
        else:
            headers["api-key"] = self._api_key
        return headers

    async def async_chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request and return the full response."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        headers = self._build_headers()

        try:
            async with self._session.post(
                self._base_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 401:
                    raise APIError("Authentication failed — check your API key/token", 401)
                if resp.status == 403:
                    raise APIError(
                        "Access denied — ensure your token has the models:read permission", 403
                    )
                if resp.status == 429:
                    raise APIError("Rate limited — please wait before trying again", 429)
                if resp.status >= 400:
                    body = await resp.text()
                    raise APIError(f"API error {resp.status}: {body}", resp.status)

                return await resp.json()

        except aiohttp.ClientError as err:
            raise APIError(f"Connection error: {err}") from err

    async def async_validate(self, model: str) -> bool:
        """Validate credentials by sending a minimal test request."""
        result = await self.async_chat_completion(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
            temperature=0,
        )
        return bool(result.get("choices"))


def build_github_client(
    session: aiohttp.ClientSession, token: str
) -> ChatCompletionClient:
    """Create a client for GitHub Models API."""
    return ChatCompletionClient(
        session, base_url=GITHUB_MODELS_URL, api_key=token, is_github=True
    )


def build_azure_client(
    session: aiohttp.ClientSession, endpoint: str, api_key: str,
    model: str = "",
) -> ChatCompletionClient:
    """Create a client for Azure OpenAI endpoint.

    Accepts either:
      - Full URL: https://X.openai.azure.com/openai/deployments/D/chat/completions?api-version=...
      - Base URL: https://X.openai.azure.com  (model/deployment name passed separately)
      - Base + path: https://X.openai.azure.com/openai/deployments/D
    """
    url = endpoint.rstrip("/")

    if "/chat/completions" in url:
        # Full URL provided — use as-is
        pass
    elif "/openai/deployments/" in url:
        # Has deployment path but no chat/completions suffix
        url = f"{url}/chat/completions?api-version={AZURE_API_VERSION}"
    elif model:
        # Base URL + model name → construct full Azure OpenAI path
        url = (
            f"{url}/openai/deployments/{model}"
            f"/chat/completions?api-version={AZURE_API_VERSION}"
        )
    else:
        # Bare base URL, no model — append generic chat/completions
        url = f"{url}/chat/completions"

    return ChatCompletionClient(
        session, base_url=url, api_key=api_key, is_github=False
    )


async def async_fetch_github_models(
    session: aiohttp.ClientSession, token: str
) -> list[dict[str, Any]]:
    """Fetch available models from the GitHub Models catalog.

    Returns a list of model dicts with id, name, publisher, capabilities, etc.
    Only returns models that support tool-calling (chat models).
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    try:
        async with session.get(
            GITHUB_CATALOG_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                _LOGGER.warning("Failed to fetch model catalog: %s", resp.status)
                return []
            models = await resp.json()
    except (aiohttp.ClientError, Exception):
        _LOGGER.exception("Error fetching model catalog")
        return []

    # Exclude embedding-only models (no chat capability)
    EMBEDDING_PREFIXES = ("openai/text-embedding",)
    chat_models = [
        m for m in models
        if isinstance(m, dict)
        and not m.get("id", "").startswith(EMBEDDING_PREFIXES)
    ]
    # Sort by publisher then name
    chat_models.sort(key=lambda m: (m.get("publisher", ""), m.get("id", "")))
    return chat_models
