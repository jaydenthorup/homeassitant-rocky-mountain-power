"""The Rocky Mountain Power Outages integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import RmpOutagesCoordinator

type RmpOutagesConfigEntry = ConfigEntry[RmpOutagesCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: RmpOutagesConfigEntry) -> bool:
    """Set up one configured outage feed."""
    coordinator = RmpOutagesCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RmpOutagesConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: RmpOutagesConfigEntry) -> None:
    """Reload when options change (radius, state, filters)."""
    await hass.config_entries.async_reload(entry.entry_id)
