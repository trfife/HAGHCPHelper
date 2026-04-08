"""GitHub OAuth device flow helpers."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


class DeviceFlowError(Exception):
    """Raised when the device flow fails."""


class AuthorizationPending(DeviceFlowError):
    """User hasn't authorized yet."""


async def async_request_device_code(
    session: aiohttp.ClientSession,
    client_id: str,
) -> dict:
    """Request a device code to start the OAuth device flow.

    Returns dict with: device_code, user_code, verification_uri, interval.
    """
    async with session.post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": ""},
        headers={"Accept": "application/json"},
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise DeviceFlowError(f"Failed to request device code: {resp.status} {text}")
        return await resp.json()


async def async_exchange_device_code(
    session: aiohttp.ClientSession,
    client_id: str,
    device_code: str,
) -> str:
    """Attempt a single token exchange.

    Returns the access_token on success.
    Raises AuthorizationPending if user hasn't authorized yet.
    Raises DeviceFlowError on terminal errors.
    """
    async with session.post(
        ACCESS_TOKEN_URL,
        data={
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        headers={"Accept": "application/json"},
    ) as resp:
        data = await resp.json()

    if "access_token" in data:
        return data["access_token"]

    error = data.get("error", "")
    if error in ("authorization_pending", "slow_down"):
        raise AuthorizationPending("User has not yet authorized")
    if error in ("expired_token", "access_denied", "incorrect_device_code"):
        raise DeviceFlowError(f"Device flow failed: {error}")

    raise DeviceFlowError(f"Unexpected response: {data}")

        _LOGGER.warning("Unexpected device flow response: %s", data)

    raise DeviceFlowError("Device flow timed out waiting for authorization")
