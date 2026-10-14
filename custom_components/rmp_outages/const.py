"""Constants for the Rocky Mountain Power outage integration."""
from __future__ import annotations

import datetime

DOMAIN = "rmp_outages"
NAME = "Rocky Mountain Power Outages"
# Drives the derived entity_ids (sensor.<device>_<key>), so keep it short.
DEVICE_NAME = "Rocky Mountain Power"
ATTRIBUTION = "Data provided by rockymountainpower.net"

# The outage map is fed by these two static JSON files (verified 2026-10-13).
# {state} is the two-letter PacifiCorp footprint code: UT ID WY CA WA OR.
FEED_BASE = "https://www.rockymountainpower.net/etc/pcorp/datafiles/outagemap"
MAP_URL = FEED_BASE + "/map{state}.json"
LIST_URL = FEED_BASE + "/list{state}.json"

# The origin serves cache-control: max-age=300 and only refreshes ~every 5 min,
# so polling faster than this is pointless and impolite.
DEFAULT_SCAN_INTERVAL = datetime.timedelta(seconds=300)

STATES = ["UT", "ID", "WY", "CA", "WA", "OR"]
CONF_STATE = "state"
CONF_RADIUS = "radius"
CONF_INCLUDE_PLANNED = "include_planned"
CONF_ZIP = "zip"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_STATE = "UT"
DEFAULT_RADIUS = 80  # km
RADIUS_MIN = 1
RADIUS_MAX = 2000
DEFAULT_INCLUDE_PLANNED = False

ATTR_OUTAGE_ID = "outage_id"
ATTR_ZIP = "zip"
ATTR_CUSTOMERS_OUT = "customers_out"
ATTR_OUTAGE_COUNT = "outage_count"
ATTR_CAUSE = "cause"
ATTR_CREW_STATUS = "crew_status"
ATTR_ETR = "etr"
ATTR_REPORTED = "reported"
ATTR_KIND = "kind"
ATTR_PLANNED = "planned"

PLATFORMS = ["sensor", "geo_location"]
