"""Data update coordinator for the Rocky Mountain Power outage feed."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ALERT_RADIUS,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    CONF_STATE,
    CONF_ZIP,
    DEFAULT_ALERT_RADIUS,
    DEFAULT_INCLUDE_PLANNED,
    DEFAULT_RADIUS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATE,
    DOMAIN,
    LIST_URL,
    MAP_URL,
)
from .parser import Outage, parse_feed, zip_counts

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RmpData:
    """Everything one poll produced."""

    outages: list[Outage] = field(default_factory=list)
    statewide_customers_out: int = 0
    feed_last_upd: str | None = None
    server_record_count: int | None = None
    zip_rollup: dict[str, int] = field(default_factory=dict)

    @property
    def unplanned(self) -> list[Outage]:
        """Return only unplanned outages."""
        return [o for o in self.outages if not o.is_planned]


class RmpOutagesCoordinator(DataUpdateCoordinator[RmpData]):
    """Poll mapXX.json (and listXX.json) on the RMP outage map."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator from a config entry."""
        options = entry.options
        self.state: str = options.get(CONF_STATE, entry.data.get(CONF_STATE, DEFAULT_STATE))
        self.radius: float = float(options.get(CONF_RADIUS, entry.data.get(CONF_RADIUS, DEFAULT_RADIUS)))
        self.zip_code: str = str(options.get(CONF_ZIP, entry.data.get(CONF_ZIP, "")) or "")
        self.include_planned: bool = bool(
            options.get(CONF_INCLUDE_PLANNED, entry.data.get(CONF_INCLUDE_PLANNED, DEFAULT_INCLUDE_PLANNED))
        )
        # Alerting radius is separate from the map radius on purpose.
        self.alert_radius: float = float(
            options.get(CONF_ALERT_RADIUS, entry.data.get(CONF_ALERT_RADIUS, DEFAULT_ALERT_RADIUS)) or 0
        )
        interval = options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Pass the entry explicitly: without it the base class falls back to a
            # ContextVar that is only correct while async_setup_entry is on the
            # stack. Every shipped integration passes it (HA 2026.10).
            config_entry=entry,
            update_interval=DEFAULT_SCAN_INTERVAL if not interval else interval,
        )

    async def _async_update_data(self) -> RmpData:
        """Fetch and parse the feeds."""
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=25)
        url = MAP_URL.format(state=self.state)
        try:
            async with session.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching {url}: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Malformed JSON from {url}: {err}") from err

        data = RmpData()
        data.outages = parse_feed(payload)
        try:
            data.statewide_customers_out = int(payload.get("totalState", 0) or 0)
        except (TypeError, ValueError):
            data.statewide_customers_out = 0
        try:
            data.server_record_count = int(payload["count"]) if payload.get("count") is not None else None
        except (TypeError, ValueError):
            data.server_record_count = None
        data.feed_last_upd = payload.get("last_upd")

        if self.zip_code:
            list_url = LIST_URL.format(state=self.state)
            try:
                async with session.get(list_url, timeout=timeout) as resp:
                    resp.raise_for_status()
                    data.zip_rollup = zip_counts(await resp.json(content_type=None), self.zip_code)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.debug("ZIP rollup fetch failed (%s): %s", list_url, err)

        _LOGGER.debug(
            "RMP %s: %d records, %d customers out, %s",
            self.state,
            len(data.outages),
            data.statewide_customers_out,
            data.feed_last_upd,
        )
        return data
