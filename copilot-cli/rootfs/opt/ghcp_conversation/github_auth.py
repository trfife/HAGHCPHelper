"""GitHub OAuth Device Flow authentication."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


class DeviceFlowError(Exception):
    """Error during device flow."""


class DeviceFlowExpired(DeviceFlowError):
    """Device code has expired."""


class DeviceFlowDenied(DeviceFlowError):
    """User denied the authorization."""


async def async_request_device_code(
    session: aiohttp.ClientSession,
    client_id: str,
    scope: str = "",
) -> dict[str, Any]:
    """Request a device code from GitHub.

    Returns dict with: device_code, user_code, verification_uri, expires_in, interval
    """
    async with session.post(
        DEVICE_CODE_URL,
        headers={"Accept": "application/json"},
        data={"client_id": client_id, "scope": scope},
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise DeviceFlowError(f"Failed to request device code: {resp.status} {body}")
        return await resp.json()


async def async_poll_for_token(
    session: aiohttp.ClientSession,
    client_id: str,
    device_code: str,
    interval: int = 5,
    expires_in: int = 900,
) -> str:
    """Poll GitHub until the user authorizes or the code expires.

    Returns the access_token string on success.
    Raises DeviceFlowExpired or DeviceFlowDenied on failure.
    """
    poll_interval = interval
    elapsed = 0

    while elapsed < expires_in:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        async with session.post(
            ACCESS_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        ) as resp:
            data = await resp.json()

        error = data.get("error")
        if error is None and "access_token" in data:
            return data["access_token"]

        if error == "authorization_pending":
            continue
        if error == "slow_down":
            poll_interval = data.get("interval", poll_interval + 5)
            continue
        if error == "expired_token":
            raise DeviceFlowExpired("Device code expired — please try again")
        if error == "access_denied":
            raise DeviceFlowDenied("Authorization was denied by the user")

        raise DeviceFlowError(f"Unexpected error: {error} — {data.get('error_description', '')}")

    raise DeviceFlowExpired("Device code expired — please try again")
