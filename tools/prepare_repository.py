#!/usr/bin/env python3
"""Set real repository metadata before publishing; never upload or publish files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare_repository(repository: str, codeowner: str, root: Path = ROOT) -> Path:
    """Validate both arguments before changing the manifest."""
    repository = repository.rstrip("/")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected https://github.com/OWNER/REPO")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", codeowner):
        raise ValueError("Invalid GitHub username (pass it without @)")
    manifest_path = root / "custom_components/allegro_onebox_air/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        documentation=repository,
        issue_tracker=repository + "/issues",
        codeowners=["@" + codeowner],
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="Real https://github.com/OWNER/REPO URL")
    parser.add_argument("--codeowner", required=True, help="GitHub username, without @")
    args = parser.parse_args()
    try:
        prepare_repository(args.repository, args.codeowner)
    except (OSError, ValueError) as err:
        parser.error(str(err))
    print("Updated manifest metadata. No files were uploaded or published.")


if __name__ == "__main__":
    main()
