# Rocky Mountain Power Outages for Home Assistant

Polls the outage data Rocky Mountain Power and Pacific Power publish (both are
PacifiCorp) and drops each outage onto your Home Assistant map as a
`geo_location` entity. Same trick [blitzortung](https://github.com/mrk-its/homeassistant-blitzortung)
does with lightning strikes, except it's your power.

I built it because my UPS kept beating me to the news that the grid was gone, and
I wanted Home Assistant to know about nearby outages first, along with a decent
guess at whether it was worth shutting things down. Markers show up as outages
enter the feed and vanish when they clear.

## What you get

Each outage inside your configured radius becomes a `geo_location` entity whose
state is the distance from home, in km or miles depending on your unit system.
The attributes carry the rest of what the feed knows: `zip`, `customers_out`,
`outage_count`, `cause`, `crew_status`, `etr`, `reported`, `kind`, `planned`.

A handful of sensors cover the feed as a whole: statewide customers out, record
counts, how many outages are inside your radius and where the nearest one is, how
old the feed is, and the timestamp from the origin. Give it a ZIP code and it adds
that ZIP's rollup as well.

The one that answers "how long is this going to take" is **Estimated restoration**:
the utility's own ETR for the outage most likely to be yours (an exact ZIP match
first, otherwise the nearest one inside the alert radius), with the matched ZIP,
distance and crew status as attributes so you can judge how much it really applies
to you. It reads `No outage nearby` when there is nothing close enough to claim.

Planned maintenance is excluded by default. You can turn it on, but scheduled work
shouldn't read like an emergency.

There is also an optional **alert radius**, separate from the map radius, which backs a
`binary_sensor.*_outage_near_home` entity (`device_class: problem`, unplanned outages only).
A map can usefully show outages 80 km away; an alert about them is just noise, so the two
radii are deliberately independent. Set the alert radius to `0` to switch it off.

## Where the numbers come from

The outage map at `rockymountainpower.net/outages-safety.html` is fed by two plain
JSON files, which the map's own DOM points at through
`data-endpoint="/etc/pcorp/datafiles/outagemap/"`:

```
https://www.rockymountainpower.net/etc/pcorp/datafiles/outagemap/mapUT.json    # per-outage records
https://www.rockymountainpower.net/etc/pcorp/datafiles/outagemap/listUT.json   # per-ZIP rollups
```

The state suffix covers the whole PacifiCorp footprint: `UT ID WY CA WA OR`. No API
key, no cookies, no Referer needed.

The server sends `cache-control: max-age=300` and only rewrites the data every five
minutes or so, which is why the integration polls every 300 seconds. Polling harder
won't get you fresher numbers.

This is unofficial and unaffiliated with PacifiCorp. It reads a public data file
that could change without warning.

## Install

Through HACS, add `https://github.com/jaydenthorup/homeassitant-rocky-mountain-power`
as a custom *Integration* repository, install it, and restart Home Assistant.

Manually, copy `custom_components/rmp_outages/` into your `config/custom_components/`
and restart.

Either way, then go to Settings → Devices & services → Add integration →
Rocky Mountain Power Outages and pick your state, radius, and whether to include
planned work.

## Testing changes without restarting Home Assistant

A custom integration only loads when Home Assistant starts, so tweaking one and
restarting to find out whether it works gets old fast. `tools/vet_in_container.py`
is what I use instead. It runs inside the HA container, imports the integration
with HA's own interpreter and classes, and covers everything that doesn't require
a full start:

```sh
docker cp tools/vet_in_container.py homeassistant:/config/vet_in_container.py
docker exec homeassistant python3 /config/vet_in_container.py
```

It checks that every module imports, that the config flow schema takes good input
and rejects bad, that the `geo_location` entity honours `GeolocationEvent`'s
contract and refreshes in place, and that the coordinator can fetch and parse the
live feed. It also confirms a bad state fails loudly instead of quietly returning
nothing.

Two things it turned up, in case you're writing something similar:

- `DataUpdateCoordinator` wants `config_entry=` passed explicitly. Leave it out and
  HA 2026.10 falls back to a ContextVar that is only correct while
  `async_setup_entry` is on the stack.
- The feed's timestamp is local time with no offset. Read it with the global default
  timezone and a freshly updated feed can look hours stale. This integration uses
  the instance's configured zone.

Neither is visible from reading the API (or the docs); both showed up the first
time the code actually ran.

## Quirks worth knowing

- The origin's `count` field usually sits one ahead of the `outages` array it ships.
  `sensor.*_outage_records` exposes both, with the difference as `count_minus_array`.
  A change in that gap means something; the gap itself is normal.
- Outages have no id in the feed, so identity here is a hash of `lat|lon|zip|reported`.
  That stays stable for as long as an outage lasts, which keeps entity ids and
  history in one piece.
- The downstream `listXX.json` only lists ZIPs with outages, so a ZIP that isn't on
  it reads as zero rather than missing.

## License

MIT, see LICENSE.
