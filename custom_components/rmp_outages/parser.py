"""Pure parsing/distance helpers for the RMP/PacifiCorp outage feed.

Deliberately stdlib-only and Home Assistant free, so the feed handling can be
unit-tested against the live endpoint without a running HA instance.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, tzinfo


@dataclass(frozen=True, slots=True)
class Outage:
    """One outage record from the map feed."""

    key: str
    latitude: float
    longitude: float
    zip: str
    customers_out: int
    outage_count: int
    cause: str
    crew_status: str
    etr: str
    reported: str
    kind: str

    @property
    def is_planned(self) -> bool:
        """Return True for planned maintenance."""
        return self.kind == "planned"


def outage_key(latitude: float, longitude: float, zip_code: str, reported: str) -> str:
    """Build a stable id for an outage.

    The feed carries no id, and both lat/lon and the reported time are stable
    while an outage lasts, so they make a usable identity across polls (which
    keeps entity ids and history continuous).
    """
    raw = f"{latitude:.3f}|{longitude:.3f}|{zip_code}|{reported}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def haversine_km(
    home: tuple[float, float], point: tuple[float, float]
) -> float:
    """Great-circle distance in km between (lat, lon) pairs."""
    lat1, lon1 = math.radians(home[0]), math.radians(home[1])
    lat2, lon2 = math.radians(point[0]), math.radians(point[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


def parse_feed(payload: dict) -> list[Outage]:
    """Turn a mapXX.json payload into Outage records, skipping malformed rows."""
    outages: list[Outage] = []
    for raw in payload.get("outages") or []:
        try:
            latitude = float(raw["latitude"])
            longitude = float(raw["longitude"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        zip_code = str(raw.get("zip", "") or "")
        reported = str(raw.get("reported", "") or "")
        try:
            customers_out = int(raw.get("custOut", 0) or 0)
        except (TypeError, ValueError):
            customers_out = 0
        try:
            outage_count = int(raw.get("outCount", 0) or 0)
        except (TypeError, ValueError):
            outage_count = 0
        outages.append(
            Outage(
                key=outage_key(latitude, longitude, zip_code, reported),
                latitude=latitude,
                longitude=longitude,
                zip=zip_code,
                customers_out=customers_out,
                outage_count=outage_count,
                cause=str(raw.get("cause", "") or ""),
                crew_status=str(raw.get("crewStatus", "") or ""),
                etr=str(raw.get("etr", "") or ""),
                reported=reported,
                kind=str(raw.get("icon", "standard") or "standard"),
            )
        )
    return outages


def within_radius(
    outages: list[Outage],
    home: tuple[float, float],
    radius_km: float,
    include_planned: bool = True,
) -> list[tuple[float, Outage]]:
    """Return (distance_km, outage) pairs inside radius_km, nearest first."""
    rows = [
        (haversine_km(home, (o.latitude, o.longitude)), o)
        for o in outages
        if include_planned or not o.is_planned
    ]
    rows = [row for row in rows if row[0] <= radius_km]
    rows.sort(key=lambda row: row[0])
    return rows


def parse_last_upd(value: str | None, tz: tzinfo | None = None) -> datetime | None:
    """Parse the feed's own timestamp, e.g. 'Tuesday, October 13 09:45 PM, 2026'.

    The origin stamps local time with no UTC offset, so the caller supplies the
    timezone. Parsing this (rather than watching for changes) means feed age is
    correct immediately after a Home Assistant restart.
    """
    if not value:
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%A, %B %d %I:%M %p, %Y")
    except (AttributeError, ValueError):
        return None
    return parsed.replace(tzinfo=tz) if tz is not None else parsed


def zip_counts(payload: dict, zip_code: str) -> dict[str, int]:
    """Pull one ZIP's planned/unplanned rollup out of listXX.json."""
    empty = {
        "customers_out_planned": 0,
        "customers_out_unplanned": 0,
        "outages_planned": 0,
        "outages_unplanned": 0,
    }
    for row in payload.get("zips") or []:
        if str(row.get("zipCode", "")) != str(zip_code):
            continue
        for key, src in (
            ("customers_out_planned", "custOutPlan"),
            ("customers_out_unplanned", "custOutUnplan"),
            ("outages_planned", "outCountPlan"),
            ("outages_unplanned", "outCountUnplan"),
        ):
            try:
                empty[key] = int(row.get(src, 0) or 0)
            except (TypeError, ValueError):
                pass
    return empty
