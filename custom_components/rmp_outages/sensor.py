"""Sensors describing the outage feed as a whole."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CAUSE,
    ATTR_CREW_STATUS,
    ATTR_CUSTOMERS_OUT,
    ATTR_ETR,
    ATTR_REPORTED,
    ATTR_ZIP,
    ATTRIBUTION,
    DEVICE_NAME,
    DOMAIN,
)
from .coordinator import RmpOutagesCoordinator
from .parser import home_outage, parse_last_upd, within_radius

_LOGGER = logging.getLogger(__name__)

MAP_PAGE = "https://www.rockymountainpower.net/outages-safety.html"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the feed sensors."""
    coordinator: RmpOutagesCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        RmpEstimatedRestoration(coordinator, entry),
        RmpStatewideCustomersOut(coordinator, entry),
        RmpOutageRecords(coordinator, entry),
        RmpOutagesWithinRadius(coordinator, entry),
        RmpFeedAge(coordinator, entry),
        RmpFeedLastUpdate(coordinator, entry),
    ]
    if coordinator.zip_code:
        entities.append(RmpHomeZipCustomersOut(coordinator, entry))
    async_add_entities(entities)


def _origin_time_zone(hass) -> object:
    """The timezone the origin's timestamp is written in.

    RMP stamps local time with no offset, and the instance timezone is the
    authority on what "local" means here. Using the global default instead is
    wrong whenever it has not been initialised (it falls back to UTC, which
    makes a fresh feed look hours stale).
    """
    return dt_util.get_time_zone(hass.config.time_zone)


class RmpBaseSensor(CoordinatorEntity[RmpOutagesCoordinator], SensorEntity):
    """Shared plumbing for the feed sensors."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: RmpOutagesCoordinator, entry: ConfigEntry, key: str) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer="PacifiCorp",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=MAP_PAGE,
        )


class RmpStatewideCustomersOut(RmpBaseSensor):
    """Customers out across the whole state."""

    _attr_native_unit_of_measurement = "customers"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:transmission-tower-off"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "statewide_customers_out")

    @property
    def native_value(self) -> int | None:
        """Return the statewide customer count."""
        return self.coordinator.data.statewide_customers_out if self.coordinator.data else None


class RmpOutageRecords(RmpBaseSensor):
    """How many records the origin publishes, and how it splits."""

    _attr_native_unit_of_measurement = "records"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:format-list-numbered"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "outage_records")

    @property
    def native_value(self) -> int | None:
        """Return the origin's own record count."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.server_record_count if data.server_record_count is not None else len(data.outages)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the count-vs-array gap and the planned split."""
        data = self.coordinator.data
        if data is None:
            return {}
        unplanned = len(data.unplanned)
        return {
            "array_len": len(data.outages),
            "planned": len(data.outages) - unplanned,
            "unplanned": unplanned,
            # The origin's own count runs ~1 ahead of its array; a *change* in
            # this gap is the signal, not the gap itself.
            "count_minus_array": (data.server_record_count or 0) - len(data.outages),
            "feed_last_upd": data.feed_last_upd,
        }


class RmpOutagesWithinRadius(RmpBaseSensor):
    """Outages close enough to matter, plus the nearest one's detail."""

    _attr_native_unit_of_measurement = "outages"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "outages_within_radius")

    def _rows(self):
        """Return (distance, outage) pairs inside the configured radius."""
        data = self.coordinator.data
        if data is None:
            return []
        return within_radius(
            data.outages,
            (self.hass.config.latitude, self.hass.config.longitude),
            self.coordinator.radius,
            include_planned=self.coordinator.include_planned,
        )

    @property
    def native_value(self) -> int:
        """Return how many outages are inside the radius."""
        return len(self._rows())

    @property
    def extra_state_attributes(self) -> dict:
        """Expose radius, totals and the nearest outage."""
        rows = self._rows()
        attrs = {
            "radius_km": self.coordinator.radius,
            "include_planned": self.coordinator.include_planned,
            "customers_out_within_radius": sum(o.customers_out for _, o in rows),
            "nearest_km": None,
        }
        if rows:
            distance, nearest = rows[0]
            attrs.update(
                {
                    "nearest_km": round(distance, 1),
                    ATTR_ZIP: nearest.zip,
                    ATTR_CUSTOMERS_OUT: nearest.customers_out,
                    ATTR_CAUSE: nearest.cause,
                    ATTR_CREW_STATUS: nearest.crew_status,
                    ATTR_ETR: nearest.etr,
                    ATTR_REPORTED: nearest.reported,
                }
            )
        return attrs


class RmpFeedAge(RmpBaseSensor):
    """Minutes since the origin last refreshed its own feed."""

    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "feed_age")

    @property
    def _stamp(self):
        """Return the parsed origin timestamp."""
        data = self.coordinator.data
        if data is None:
            return None
        return parse_last_upd(data.feed_last_upd, _origin_time_zone(self.hass))

    @property
    def native_value(self) -> float | None:
        """Return feed age in minutes."""
        stamp = self._stamp
        if stamp is None:
            return None
        return round((dt_util.utcnow() - stamp).total_seconds() / 60, 1)


class RmpFeedLastUpdate(RmpBaseSensor):
    """The origin's own 'last updated' timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "feed_last_update")

    @property
    def native_value(self):
        """Return the parsed timestamp."""
        data = self.coordinator.data
        if data is None:
            return None
        return parse_last_upd(data.feed_last_upd, _origin_time_zone(self.hass))


class RmpEstimatedRestoration(RmpBaseSensor):
    """When the utility expects to have your power back."""

    _attr_icon = "mdi:timer-sand-complete"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "estimated_restoration")

    def _match(self):
        """Return (reason, distance, outage) for the outage most likely to be yours."""
        data = self.coordinator.data
        if data is None:
            return None
        return home_outage(
            data.outages,
            (self.hass.config.latitude, self.hass.config.longitude),
            self.coordinator.zip_code,
            self.coordinator.alert_radius or 10,
        )

    @property
    def native_value(self) -> str:
        """The utility's own wording, or a plain statement that there is nothing nearby."""
        match = self._match()
        if match is None:
            return "No outage nearby"
        return match[2].etr or "not stated"

    @property
    def extra_state_attributes(self) -> dict:
        """Everything needed to judge how much that estimate really applies to you."""
        match = self._match()
        if match is None:
            return {}
        reason, distance, outage = match
        return {
            "matched": "your ZIP" if reason == "zip" else "outage nearest home",
            "distance_km": round(distance, 1),
            ATTR_ZIP: outage.zip,
            ATTR_CUSTOMERS_OUT: outage.customers_out,
            ATTR_CREW_STATUS: outage.crew_status,
            ATTR_REPORTED: outage.reported,
        }


class RmpHomeZipCustomersOut(RmpBaseSensor):
    """Customers out in the configured ZIP (from the list feed)."""

    _attr_native_unit_of_measurement = "customers"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-alert-outline"

    def __init__(self, coordinator, entry):
        """Initialise."""
        super().__init__(coordinator, entry, "home_zip_customers_out")

    @property
    def native_value(self) -> int | None:
        """Return the ZIP's total customers out."""
        data = self.coordinator.data
        if data is None or not data.zip_rollup:
            return None
        return data.zip_rollup.get("customers_out_planned", 0) + data.zip_rollup.get(
            "customers_out_unplanned", 0
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the planned/unplanned split."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {"zip": self.coordinator.zip_code, **data.zip_rollup}
