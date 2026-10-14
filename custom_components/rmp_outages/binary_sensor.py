"""Binary sensors: is something actually wrong near home?"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
from .parser import within_radius

MAP_PAGE = "https://www.rockymountainpower.net/outages-safety.html"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the near-home sensor, unless the alert radius is switched off."""
    coordinator: RmpOutagesCoordinator = entry.runtime_data
    if coordinator.alert_radius <= 0:
        return
    async_add_entities([RmpOutageNearHome(coordinator, entry)])


class RmpOutageNearHome(CoordinatorEntity[RmpOutagesCoordinator], BinarySensorEntity):
    """On while an unplanned outage sits inside the alert radius.

    Deliberately uncoupled from the map radius: a map can usefully show outages
    80 km away, but an alert about them is noise. Planned maintenance is ignored
    either way, so scheduled work never looks like a fault.
    """

    _attr_attribution = ATTRIBUTION
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_icon = "mdi:home-alert"
    _attr_should_poll = False
    _attr_translation_key = "outage_near_home"

    def __init__(self, coordinator: RmpOutagesCoordinator, entry: ConfigEntry) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_outage_near_home"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer="PacifiCorp",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=MAP_PAGE,
        )

    def _rows(self) -> list:
        """Unplanned outages inside the alert radius, nearest first."""
        data = self.coordinator.data
        if data is None:
            return []
        return within_radius(
            data.outages,
            (self.hass.config.latitude, self.hass.config.longitude),
            self.coordinator.alert_radius,
            include_planned=False,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True while an unplanned outage is close enough to care about."""
        return bool(self._rows()) if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the nearest outage so alerts can quote it without more templates."""
        rows = self._rows()
        attrs: dict = {
            "alert_radius_km": self.coordinator.alert_radius,
            "count": len(rows),
            ATTR_ZIP: None,
            ATTR_CUSTOMERS_OUT: None,
            "nearest_km": None,
            "customers_out_nearby": sum(o.customers_out for _, o in rows),
        }
        if rows:
            distance, nearest = rows[0]
            attrs.update(
                {
                    ATTR_ZIP: nearest.zip,
                    "nearest_km": round(distance, 1),
                    ATTR_CUSTOMERS_OUT: nearest.customers_out,
                    ATTR_CAUSE: nearest.cause,
                    ATTR_CREW_STATUS: nearest.crew_status,
                    ATTR_ETR: nearest.etr,
                    ATTR_REPORTED: nearest.reported,
                    # kept for the wording already used in the Discord alerts
                    "nearest_zip": nearest.zip,
                    "nearest_cause": nearest.cause,
                    "nearest_crew_status": nearest.crew_status,
                    "nearest_etr": nearest.etr,
                }
            )
        return attrs
