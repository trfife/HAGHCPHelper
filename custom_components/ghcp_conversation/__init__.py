"""GitHub Copilot Conversation integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .knowledge import KnowledgeStore

try:
    from .analytics import AnalyticsStore
except ImportError:
    AnalyticsStore = None  # type: ignore[assignment,misc]

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GitHub Copilot Conversation from a config entry."""
    # Initialize shared stores (once per integration)
    if DOMAIN not in hass.data:
        knowledge = KnowledgeStore(hass)
        await knowledge.async_load()

        analytics = None
        if AnalyticsStore is not None:
            try:
                analytics = AnalyticsStore(hass)
                await analytics.async_setup()

                # Migrate legacy JSON knowledge → SQLite on first load
                if knowledge.entry_count > 0:
                    migrated = await analytics.async_migrate_from_json(
                        knowledge._entries  # noqa: SLF001
                    )
                    if migrated:
                        _LOGGER.info(
                            "Migrated %d knowledge entries to SQLite", migrated
                        )
            except Exception:
                _LOGGER.exception("Failed to initialize analytics — continuing without it")
                analytics = None
        else:
            _LOGGER.warning(
                "aiosqlite not available — analytics disabled. "
                "Install with: pip install aiosqlite"
            )

        hass.data[DOMAIN] = {"knowledge": knowledge, "analytics": analytics}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Clean up hass.data if this is the last config entry for our domain
    if result:
        remaining = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining:
            domain_data = hass.data.pop(DOMAIN, {})
            analytics = domain_data.get("analytics")
            if analytics:
                await analytics.async_close()

    return result


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
