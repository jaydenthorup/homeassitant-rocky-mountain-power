"""Geo location entities: one marker per outage on the map."""
from __future__ import annotations

import logging

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_conversion import DistanceConverter
from homeassistant.util.unit_system import IMPERIAL_SYSTEM

from .const import (
    ATTR_CAUSE,
    ATTR_CREW_STATUS,
    ATTR_CUSTOMERS_OUT,
    ATTR_ETR,
    ATTR_KIND,
    ATTR_OUTAGE_COUNT,
    ATTR_OUTAGE_ID,
    ATTR_PLANNED,
    ATTR_REPORTED,
    ATTR_ZIP,
    ATTRIBUTION,
    DOMAIN,
)
from .coordinator import RmpOutagesCoordinator
from .parser import Outage, within_radius

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a marker per outage, keeping them in step with the feed."""
    coordinator: RmpOutagesCoordinator = entry.runtime_data
    manager = RmpOutageManager(hass, async_add_entities, coordinator)
    entry.async_on_unload(coordinator.async_add_listener(manager.update))
    manager.update()


class RmpOutageManager:
    """Add, refresh and remove outage markers as the feed changes."""

    def __init__(self, hass: HomeAssistant, async_add_entities, coordinator) -> None:
        """Initialise the manager."""
        self._hass = hass
        self._async_add_entities = async_add_entities
        self._coordinator = coordinator
        self._entities: dict[str, RmpOutageEvent] = {}
        unit = (
            UnitOfLength.MILES
            if hass.config.units == IMPERIAL_SYSTEM
            else UnitOfLength.KILOMETERS
        )
        self._unit = unit

    def _distance(self, km: float) -> float:
        """Convert a km distance into the unit system in use."""
        if self._unit == UnitOfLength.MILES:
            return DistanceConverter.convert(km, UnitOfLength.KILOMETERS, UnitOfLength.MILES)
        return km

    @callback
    def update(self) -> None:
        """Reconcile entities with the current feed."""
        data = self._coordinator.data
        if data is None:
            return
        rows = within_radius(
            data.outages,
            (self._hass.config.latitude, self._hass.config.longitude),
            self._coordinator.radius,
            include_planned=self._coordinator.include_planned,
        )
        current = {o.key: (d, o) for d, o in rows}

        new_entities = []
        for key, (distance, outage) in current.items():
            entity = self._entities.get(key)
            if entity is None:
                entity = RmpOutageEvent(outage, self._distance(distance), self._unit)
                self._entities[key] = entity
                new_entities.append(entity)
            else:
                # Same outage, fresh numbers (customers/crew/ETR may have moved).
                entity.update_from(outage, self._distance(distance))
        if new_entities:
            self._async_add_entities(new_entities)

        for key in list(self._entities):
            if key in current:
                continue
            entity = self._entities.pop(key)
            _LOGGER.debug("Outage %s left the feed; removing marker", key)
            self._hass.async_create_task(entity.async_remove(force_remove=True))


class RmpOutageEvent(GeolocationEvent):
    """One power outage, as a marker on the map."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:transmission-tower-off"
    # Plain language on purpose: "RMP" is insider shorthand that means nothing to
    # someone glancing at the map. Set per outage in __init__ for planned work.
    _attr_name = "Power Outage"
    _attr_should_poll = False
    _attr_source = DOMAIN
    # These carry lat/lon plus volatile feed text; nothing here needs recording.
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, outage: Outage, distance: float, unit: str) -> None:
        """Initialise the marker from one outage record."""
        self._outage = outage
        self._attr_name = self._label(outage)
        if outage.is_planned:
            self._attr_icon = "mdi:calendar-clock"
        self._attr_unique_id = f"{DOMAIN}_{outage.key}"
        self.entity_id = f"geo_location.rmp_outage_{outage.key}"
        self._attr_distance = round(distance, 1)
        self._attr_unit_of_measurement = unit
        self._attr_latitude = outage.latitude
        self._attr_longitude = outage.longitude
        self._refresh_attributes()

    @staticmethod
    def _label(outage: Outage) -> str:
        """Plain wording plus the ZIP: 'Power Outage 84098'.

        The ZIP is what makes one marker telling apart from the next; the utility's
        acronym is not, which is why the wording stays plain and the ZIP stays on.
        """
        words = "Planned Power Outage" if outage.is_planned else "Power Outage"
        return f"{words} {outage.zip}".strip() if outage.zip else words

    def _refresh_attributes(self) -> None:
        """Rebuild the attribute payload from the outage record."""
        self._attr_extra_state_attributes = {
            ATTR_OUTAGE_ID: self._outage.key,
            ATTR_ZIP: self._outage.zip,
            ATTR_CUSTOMERS_OUT: self._outage.customers_out,
            ATTR_OUTAGE_COUNT: self._outage.outage_count,
            ATTR_CAUSE: self._outage.cause,
            ATTR_CREW_STATUS: self._outage.crew_status,
            ATTR_ETR: self._outage.etr,
            ATTR_REPORTED: self._outage.reported,
            ATTR_KIND: self._outage.kind,
            ATTR_PLANNED: self._outage.is_planned,
        }

    def update_from(self, outage: Outage, distance: float) -> None:
        """Apply fresh data for the same outage."""
        self._outage = outage
        self._attr_name = self._label(outage)
        self._attr_icon = "mdi:calendar-clock" if outage.is_planned else "mdi:transmission-tower-off"
        self._attr_distance = round(distance, 1)
        self._refresh_attributes()
        if self.hass is not None:
            self.async_write_ha_state()
