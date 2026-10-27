# Changelog

## 0.3.0 — 2026-10-27

- Rename the public project and integration display name to **OBox Air**.
- Replace the bundled Radomsko catalogue with live map searches anywhere in Poland.
- Resolve public locker codes nationwide, alongside numeric IDs and map links.
- Detect grouped map responses and request a narrower area rather than presenting an incomplete list.
- Preserve the integration domain and entity IDs; migrate existing configuration entries.
- Add diagnostics, Polish and English documentation, contributor guidance, issue templates, linting, validation, and reproducible component packaging.

## 0.2.0 — 2026-10-27

- Fetch point measurements directly over HTTP using a fresh `curl-cffi` session per request.
- Remove the external browser scraper and MQTT dependency.
- Add source timestamp validation, five-minute polling, and configuration through HA.

## 0.1.0 — 2026-10-26

- Initial local prototype using a separate scraper and MQTT transport.
