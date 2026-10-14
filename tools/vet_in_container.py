"""Vet the rmp_outages integration inside a real HA container, without restarting HA.

Run with:  docker cp <this> homeassistant:/config/vet_rmp.py
           docker exec homeassistant python3 /config/vet_rmp.py

Uses HA's own interpreter and classes, so it catches wrong import paths, wrong
base-class contracts and API drift, which are the failures you would otherwise
only see after a restart. It does not restart or reload Home Assistant.

One scope limit worth stating: `homeassistant.helpers.aiohttp_client.async_get_clientsession`
is swapped for a plain aiohttp session, because it requires the `network`
integration (always loaded in a live instance, absent in a bare HomeAssistant).
Everything belonging to this integration is exercised against the live endpoint.
"""
import asyncio
import dataclasses
import importlib
import json
import sys
import traceback
from types import MappingProxyType

sys.path.insert(0, "/config")
DOMAIN = "custom_components.rmp_outages"
MAP_URL = "https://www.rockymountainpower.net/etc/pcorp/datafiles/outagemap/mapUT.json"

# A neutral reference point (downtown Salt Lake City) so no real install's
# location ships with the tool. Pass your own if you want your own numbers.
REFERENCE_LAT, REFERENCE_LON = 40.7608, -111.8910
REFERENCE_ZIP = "84101"
failures = []


def step(label):
    print(f"\n--- {label}")


def check(cond, label, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def make_entry(coordinator_cls, hass, state, radius):
    """Build a genuine, correctly-stated config entry and coordinator."""
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState

    entry = ConfigEntry(
        data={"state": state, "radius": radius, "include_planned": False, "zip": REFERENCE_ZIP},
        discovery_keys=MappingProxyType({}),
        domain="rmp_outages",
        entry_id="vet_entry",
        minor_version=1,
        options={},
        source="user",
        state=ConfigEntryState.SETUP_IN_PROGRESS,
        subentries_data=(),
        title="vet",
        unique_id=None,
        version=1,
    )
    return coordinator_cls(hass, entry)


step("1. import every module with HA's interpreter")
for mod in ("const", "parser", "coordinator", "geo_location", "sensor", "config_flow", "__init__"):
    try:
        importlib.import_module(f"{DOMAIN}.{mod}")
        check(True, f"import {mod}")
    except Exception as err:  # noqa: BLE001
        check(False, f"import {mod}", f"{type(err).__name__}: {err}")
        traceback.print_exc()

step("2. config flow schema builds and validates")
try:
    from custom_components.rmp_outages.config_flow import _schema
    from custom_components.rmp_outages.const import DEFAULT_RADIUS

    schema = _schema({})
    keys = sorted(str(k) for k in schema.schema)
    check(keys == ["include_planned", "radius", "state", "zip"], "schema keys", str(keys))
    parsed = schema({"state": "UT"})
    check(parsed["state"] == "UT" and parsed["radius"] == DEFAULT_RADIUS,
          "defaults fill in", json.dumps(parsed, default=str))
    for bad, label in (({"state": "ZZ"}, "invalid state"), ({"state": "UT", "radius": 99999}, "radius over max")):
        try:
            schema(bad)
            check(False, f"{label} rejected")
        except Exception:  # noqa: BLE001
            check(True, f"{label} rejected")
except Exception as err:  # noqa: BLE001
    check(False, "config flow", f"{type(err).__name__}: {err}")
    traceback.print_exc()

step("3. geo_location entity honours the GeolocationEvent contract")
try:
    from homeassistant.const import MATCH_ALL

    from custom_components.rmp_outages.geo_location import RmpOutageEvent
    from custom_components.rmp_outages.parser import Outage, outage_key

    outage = Outage(
        key=outage_key(REFERENCE_LAT, REFERENCE_LON, REFERENCE_ZIP, "09:45 AM on 10/13"),
        latitude=REFERENCE_LAT,
        longitude=REFERENCE_LON,
        zip=REFERENCE_ZIP,
        customers_out=12,
        outage_count=1,
        cause="Equipment Failure",
        crew_status="Assigned",
        etr="Before 3:30 PM on 10/13",
        reported="09:45 AM on 10/13",
        kind="standard",
    )
    entity = RmpOutageEvent(outage, 41.9, "km")
    check(entity.state == 41.9, "state == distance (rounded)", repr(entity.state))
    check(entity.source == "rmp_outages", "source set (required by base)", repr(entity.source))
    check(entity.unit_of_measurement == "km", "unit", repr(entity.unit_of_measurement))
    check((entity.latitude, entity.longitude) == (REFERENCE_LAT, REFERENCE_LON), "lat/lon numeric",
          f"{entity.latitude!r},{entity.longitude!r}")
    check(entity.entity_id.startswith("geo_location.rmp_outage_"), "entity_id", entity.entity_id)
    check(len(entity.unique_id) < 255, "unique_id", entity.unique_id)
    check(entity._unrecorded_attributes == frozenset({MATCH_ALL}), "marked not-recorded")
    attrs = entity.extra_state_attributes
    check(attrs["customers_out"] == 12 and attrs["planned"] is False, "attributes", json.dumps(attrs))
    entity.update_from(dataclasses.replace(outage, customers_out=99, crew_status="On Site"), 12.5)
    check(entity.state == 12.5 and entity.extra_state_attributes["customers_out"] == 99,
          "same outage refreshes in place")

    # Labels must be distinguishable on the map and read the same way as the dashboard.
    check(entity.name.startswith("RMP Outage") and outage.zip in entity.name,
          "unplanned marker label", entity.name)
    check(entity.icon == "mdi:transmission-tower-off", "unplanned marker icon", entity.icon)
    planned = RmpOutageEvent(dataclasses.replace(outage, key="planned01", kind="planned"), 5.0, "km")
    check(planned.name.startswith("RMP Planned Outage"), "planned marker label", planned.name)
    check(planned.icon == "mdi:calendar-clock", "planned marker icon", planned.icon)
    check(entity.entity_id != planned.entity_id and entity.unique_id != planned.unique_id,
          "labels differ without colliding ids")
except Exception as err:  # noqa: BLE001
    check(False, "geo_location entity", f"{type(err).__name__}: {err}")
    traceback.print_exc()

step("4. real coordinator against the LIVE feed (real HTTP, real HA plumbing)")
try:
    import aiohttp
    from homeassistant.core import HomeAssistant

    from custom_components.rmp_outages import coordinator as coord_mod
    from custom_components.rmp_outages.parser import within_radius

    async def live(state, radius):
        hass = HomeAssistant("/tmp/vet_ha")
        # Match the real instance so local-time parsing is exercised truthfully.
        hass.config.time_zone = "America/Denver"
        coord = make_entry(coord_mod.RmpOutagesCoordinator, hass, state, radius)
        async with aiohttp.ClientSession() as session:
            coord_mod.async_get_clientsession = lambda hass, verify_ssl=True: session
            try:
                await coord.async_config_entry_first_refresh()
            except Exception as err:  # noqa: BLE001
                return coord, err, hass
        return coord, None, hass

    coord, err, hass = asyncio.run(live("UT", 80))
    if err:
        check(False, "live fetch UT", f"{type(err).__name__}: {err}")
    else:
        data = coord.data
        check(len(data.outages) > 0, "parsed live records", f"{len(data.outages)} records")
        check(data.statewide_customers_out >= 0, "statewide customers", str(data.statewide_customers_out))
        check(bool(data.feed_last_upd), "origin last_upd", repr(data.feed_last_upd))
        check(bool(data.zip_rollup), f"ZIP rollup {REFERENCE_ZIP}", json.dumps(data.zip_rollup))
        check(data.server_record_count is not None, "origin count", str(data.server_record_count))
        # feed age must parse from the origin's own stamp
        from homeassistant.util import dt as dt_util

        from custom_components.rmp_outages.parser import parse_last_upd

        from custom_components.rmp_outages.sensor import _origin_time_zone

        tz = _origin_time_zone(hass)
        check(str(tz) == "America/Denver", "instance timezone resolves", str(tz))
        stamp = parse_last_upd(data.feed_last_upd, tz)
        check(stamp is not None, "last_upd parses", repr(stamp))
        if stamp:
            age = (dt_util.utcnow() - stamp).total_seconds() / 60
            check(-5 <= age <= 30, "feed age sane (min)", f"{age:.1f} min")
        ref = (REFERENCE_LAT, REFERENCE_LON)
        unplanned_rows = within_radius(data.outages, ref, 20000, include_planned=False)
        check(len(unplanned_rows) == len(data.unplanned),
              "a radius covering everything returns every unplanned outage",
              f"{len(unplanned_rows)} of {len(data.unplanned)}")
        check(not within_radius(data.outages, ref, 0, include_planned=False),
              "radius 0 returns nothing")
        distances = [d for d, _ in unplanned_rows]
        check(distances == sorted(distances), "results come back nearest first")
        near = within_radius(data.outages, ref, 80, include_planned=False)
        if near:
            print(f"       nearest to the reference point: {near[0][0]:.1f} km, zip "
                  f"{near[0][1].zip}, {near[0][1].customers_out} customers, {near[0][1].cause}")
        unplanned = sum(1 for o in data.outages if not o.is_planned)
        print(f"       planned {len(data.outages) - unplanned} / unplanned {unplanned}")

    # an unknown state must fail loudly, not silently return nothing
    _, err_bad, _ = asyncio.run(live("ZZ", 80))
    check(err_bad is not None, "unknown state fails loudly", f"{type(err_bad).__name__}: {str(err_bad)[:80]}")
except Exception as err:  # noqa: BLE001
    check(False, "coordinator live run", f"{type(err).__name__}: {err}")
    traceback.print_exc()

step("5. the origin responds to a plain client (no HA involved)")
try:
    import urllib.request

    with urllib.request.urlopen(
        urllib.request.Request(MAP_URL, headers={"User-Agent": "curl/8.14.1"}), timeout=20
    ) as resp:
        payload = json.load(resp)
    check(resp.status == 200 and "outages" in payload, "mapUT.json reachable", f"{len(payload['outages'])} rows")
except Exception as err:  # noqa: BLE001
    check(False, "origin reachable", f"{type(err).__name__}: {err}")

print("\n=== RESULT ===")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
else:
    print("all checks passed")
sys.exit(1 if failures else 0)
