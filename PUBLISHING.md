# Publishing OBox Air

The target repository is **https://github.com/typ14mg/OBox-Air**, maintained as **@typ14mg**. Preparing these local files does not create a GitHub repository, upload files, or publish a release.

## Identity and privacy

A GitHub username or pseudonym is sufficient for the project's public maintainer metadata. This project uses `typ14mg`; it does not require a legal name or private email address. Before creating commits, review Git's author name and email. To keep your email private, use the exact `noreply` address shown in your GitHub email settings. Changing it later does not remove an address already recorded in old commits. See [GitHub's instructions](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address).

## Repository setup

1. Create the public GitHub repository `typ14mg/OBox-Air`, with Issues enabled. Set its description, for example: “Home Assistant integration for Allegro One Box air quality measurements in Poland”. Add topics such as `home-assistant`, `hacs`, `air-quality`, and `allegro`. Review the source and data access limitations before publishing.
2. If the destination changes, update metadata with:

```sh
python tools/prepare_repository.py https://github.com/typ14mg/OBox-Air --codeowner typ14mg
```

3. Run the local release checks:

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest
python tools/validate_project.py --release
python tools/build_release.py --release
```

4. Publish the source at the repository root, including `custom_components`, `brand`, `hacs.json`, the license, documentation, tests, and workflows. Do not upload virtual environments, caches, credentials, generated `dist/` files as source, or the old MQTT/browser prototype.
5. Enable GitHub private vulnerability reporting when available, and review Actions permissions. Run CI and the official HACS and Hassfest validation workflows; a local validator is not a substitute for those checks.

## Releases and HACS

Keep the version in `custom_components/allegro_onebox_air/manifest.json` and `CHANGELOG.md` aligned. Build the component archive from that version. For version 0.3.0, the artifact is `dist/obox-air-component-0.3.0.zip`; it contains `custom_components/allegro_onebox_air/` so manual extraction into HA's configuration directory is straightforward.

After checks pass, create a matching Git tag and GitHub release, attach the component ZIP, and describe changes and known limitations. Users can then add the repository to HACS as a custom **Integration** repository. Inclusion in the default HACS catalogue requires a separate submission and acceptance.

References: [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/), [HACS publishing](https://www.hacs.xyz/docs/publish/start/), [Home Assistant integration manifest](https://contributors.home-assistant.io/core/integrations/manifest/).
