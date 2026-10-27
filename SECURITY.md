# Security

Use the latest published version. Older releases may not receive separate fixes.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** feature when private reporting is enabled for this repository. If it is unavailable, open an issue requesting a private contact method without including exploit details or sensitive data. Do not publish credentials, cookies, full response pages, personal email addresses, or home coordinates.

Include the affected version, expected and observed behavior, and a minimal reproduction. The maintainer will assess reports as availability allows; no fixed response time is promised.

## Data and scope

The integration makes outbound HTTPS requests to Allegro for map results and selected public point pages. It does not need account credentials, API keys, an inbound server, or a separate browser process. Selected point identifiers are stored in HA's configuration. A chosen map center is used for the search and is not stored in the resulting integration entry.

Diagnostics omit search coordinates, cookies, response bodies, and raw exception messages. They still contain the selected public locker identifier and readings, which may reveal a location preference. Review diagnostics before sharing.

Do not increase traffic, expand map clusters recursively, or add CAPTCHA-solving services as a workaround for refused access. Source access and data reuse remain subject to applicable law and third-party terms as described in the README.
