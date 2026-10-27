# Testing OBox Air 0.3.0

Validation date: 2026-10-27. Baseline: Python 3.13.15, Home Assistant 2025.12.4, curl-cffi 0.16.3. Tests use actual HA classes and isolated temporary configuration directories. Ordinary test runs are offline.

## Automated coverage

The suite covers measurement and map parsing, numeric and timestamp validation, empty readings, genuine zeroes, blocked responses, fresh HTTP sessions, nationwide code lookup, map clusters, config flow, entity metadata, availability, configuration migration, reload, unload, and shutdown cleanup. A full HA bootstrap test loads the integration, creates sensors, exercises failures and recovery, and checks stable entity IDs during migration.

Local tools also check manifest metadata, matching translations, the component layout, and reproducible ZIP contents. Ruff checks imports, selected Python errors, and formatting. The release validator requires the declared GitHub repository, Issues URL, and maintainer; it does not test whether that repository has been published.

The complete release candidate passed **78 tests** on the baseline HA version. Ruff checks and formatting passed for 24 Python files. Strict release metadata validation passed. One deprecation warning originates in Home Assistant's HTTP component.

## Live source checks

Limited public HTTP probes on 2026-10-27 confirmed:

- Point pages contain measurement JSON in the initial HTML; JavaScript execution is unnecessary.
- A fresh session per request can fetch repeated readings successfully.
- Map searches work outside the original development city: a small Warsaw area returned 50 points with no clusters.
- A larger Warsaw area returned grouped markers; such responses must not be presented as complete lists.
- Exact code lookup resolved a Warsaw One Box (`AL012WE1`) through the national map filter.

The final v0.3 client also resolved that code to point `751575`, fetched its address (Warszawa, Czarnomorska 7) and a valid measurement, and returned 44 unclustered results for a separate 2 km Warsaw search. These checks used the actual integration client rather than a parallel probe implementation.

These are source compatibility checks at a point in time, not a guarantee of availability from every IP address or of every locker having measurements. No full-country catalogue was downloaded. Live probes are separate from the offline test suite.

## Repeat locally

```sh
python -m pip install -r requirements-test.txt
python -m pytest
python -m ruff check .
python -m ruff format --check .
python tools/validate_project.py --release
python tools/build_release.py --release
```

## Limits

The baseline HA version is tested; compatibility with every newer HA release is not implied. The maintainer must run official HACS and Hassfest workflows after publishing; no remote Actions run or HACS catalogue acceptance is claimed by local validation. Changes to Allegro's page, map service, or access controls may require an update.
