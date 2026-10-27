# OBox Air

![OBox Air](brand/icon.png)

[Polski](README.md)

An unofficial **Home Assistant** integration for air quality measurements from **Allegro One Box parcel lockers in Poland**. Home Assistant fetches public data directly over HTTP. No separate container, MQTT broker, browser, Allegro account, or API key is required.

## Features

- Find lockers around any location in Poland, without a bundled city directory.
- Add a locker by its public code, numeric point ID, or Allegro map link.
- PM2.5, PM10, and source measurement timestamp sensors for each locker.
- Five-minute polling, source timestamp validation, and unavailable states on errors.
- Polish and English configuration and sensor names.

Requires **Home Assistant 2025.12.4 or newer** and internet access. Only One Box lockers are supported; staffed Allegro One Punkt locations are excluded. Measurements depend on availability at the selected locker and Allegro.

## Installation

### HACS

Once the repository is published, add `https://github.com/typ14mg/OBox-Air` under **HACS → Custom repositories**, category **Integration**. Install **OBox Air**, then restart Home Assistant. A custom repository is separate from inclusion in HACS's default catalogue.

### Manual

1. Download `obox-air-component-<version>.zip` from [Releases](https://github.com/typ14mg/OBox-Air/releases).
2. Extract it into the Home Assistant configuration directory. In HA Container, the resulting manifest must be `/config/custom_components/allegro_onebox_air/manifest.json`.
3. Restart HA. Home Assistant installs the required `curl-cffi` library automatically.

## Configuration

Open **Settings → Devices & services → Add integration → OBox Air**. Add each physical locker separately.

**Search on the map:** choose any location and a search distance, initially 2 km. The search covers a square extending by that distance in each direction. Select a locker by its code and distance; its address is fetched after selection. When Allegro returns grouped markers instead of a complete list, reduce the search area.

**Enter a code, ID, or link:** enter a code such as `AL012WE1`, a numeric `pointId`, or a link to a selected point on [Allegro's map](https://allegro.pl/kampania/one/znajdz-nas). Locker codes and numeric IDs are different. Code lookup covers Poland.

## Data

| Sensor | Unit / type |
|---|---|
| PM2.5 | µg/m³ |
| PM10 | µg/m³ |
| Measurement time | source timestamp |

All three sensors share one page fetch per locker every five minutes. Allegro's quality category is exposed as `allegro_quality`; it is not converted into AQI or the Polish GIOŚ index.

Measurements at least 30 minutes old, or more than five minutes in the future, are unavailable. Missing or invalid values never become zero. Genuine zeroes and independent PM channel values are preserved. A valid locker without a current measurement can be configured, but its sensors remain unavailable.

## Troubleshooting

- **HTTP 403/429 or CAPTCHA:** access was refused. The integration reports unavailability and does not solve CAPTCHA. Try again later.
- **Search area too large:** reduce the distance or enter the exact locker code.
- **No measurements:** check the same point on Allegro's map and inspect its source timestamp.
- **Integration missing after installation:** check the directory path, restart HA, and inspect dependency installation errors.

For [bug reports](https://github.com/typ14mg/OBox-Air/issues), include HA and integration versions and sanitized errors. Diagnostics exclude cookies, response bodies, and the search location, but include the selected public locker ID. Remove that ID if you do not want to disclose which locker you use.

## Updating and removing

Update through HACS, or replace the entire `custom_components/allegro_onebox_air` directory and restart HA. The internal domain remains unchanged to preserve existing devices, entities, and history. Entries from versions 0.1 and 0.2 migrate automatically; obsolete MQTT settings are removed.

To remove the integration, delete its config entries in HA, uninstall it through HACS or remove its component directory, then restart HA.

## Experimental use and responsibility

This is an **experimental, educational project** demonstrating public measurement retrieval and Home Assistant sensors. It is independent of Allegro and is not endorsed by Allegro.

**Use at your own risk.** The code is provided AS IS, without warranties, under the [MIT License](LICENSE), to the extent permitted by applicable law. Measurement accuracy, source availability, and uninterrupted operation are not guaranteed.

The MIT License covers this project's code; **it does not grant Allegro's permission to retrieve or reuse data**. Assess your use against applicable law, [Allegro's terms](https://allegro.pl/regulamin), and data rights, and obtain permission where required. An educational purpose or disclaimer does not override those requirements or exclude liability that cannot legally be excluded.

## Development

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Testing](TESTING.md) · [Publishing](PUBLISHING.md) · [Security](SECURITY.md)

The project structure was inspired by [InPost Air](https://github.com/CyberDeer/InPost-Air); this implementation was written independently. Data comes from Allegro's undocumented public map endpoint and JSON embedded in point pages. Source changes may require integration updates.
