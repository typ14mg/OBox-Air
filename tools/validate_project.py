#!/usr/bin/env python3
"""Validate this project's JSON metadata and translations locally.

This is a project check, not a replacement for Home Assistant hassfest or HACS.
Use --release to require GitHub publication metadata as well.
"""

from __future__ import annotations

import argparse
import json
import re
import string
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

DOMAIN = "allegro_onebox_air"
ROOT = Path(__file__).resolve().parents[1]
COMPONENT = Path("custom_components") / DOMAIN
IGNORED_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache"}


class ValidationError(ValueError):
    """A project file is inconsistent or unsuitable for release."""


def load_json(path: Path, *, object_only: bool = True) -> Any:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ValidationError(f"Cannot read JSON in {path}: {err}") from err
    if object_only and not isinstance(result, dict):
        raise ValidationError(f"Expected a JSON object in {path}")
    return result


def string_leaves(value: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    if isinstance(value, str):
        return {prefix: value}
    if not isinstance(value, dict):
        raise ValidationError(f"Translation {'.'.join(prefix)} must be a string or object")
    result = {}
    for key, child in value.items():
        if not isinstance(key, str):
            raise ValidationError("Translation keys must be strings")
        result.update(string_leaves(child, (*prefix, key)))
    return result


def placeholders(value: str) -> set[str]:
    try:
        return {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
    except ValueError as err:
        raise ValidationError(f"Malformed translation placeholder: {value}") from err


def component_files(root: Path = ROOT) -> list[Path]:
    folder = root / COMPONENT
    if not folder.is_dir():
        raise ValidationError(f"Missing integration folder: {folder}")
    result = []
    for path in sorted(folder.rglob("*")):
        if any(part in IGNORED_NAMES or part.startswith(".git") for part in path.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValidationError(f"Release contains a symlink: {path}")
        if path.is_file():
            result.append(path)
    return result


def validate_project(root: Path = ROOT, *, public: bool = False) -> dict[str, Any]:
    component = root / COMPONENT
    manifest = load_json(component / "manifest.json")
    required = {
        "domain": str,
        "name": str,
        "version": str,
        "config_flow": bool,
        "iot_class": str,
        "integration_type": str,
        "requirements": list,
        "codeowners": list,
        "documentation": str,
    }
    for key, expected in required.items():
        if not isinstance(manifest.get(key), expected):
            raise ValidationError(f"manifest.{key} must be {expected.__name__}")
    if manifest["domain"] != DOMAIN:
        raise ValidationError("The integration domain does not match its directory")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[ab]|rc)?\d*", manifest["version"]):
        raise ValidationError("manifest.version must be a version such as 0.3.0")
    if manifest["config_flow"] is not True or manifest["iot_class"] != "cloud_polling":
        raise ValidationError("The integration must declare its config flow and cloud polling")
    for dependency in manifest["requirements"]:
        if not isinstance(dependency, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+==[^\s]+", dependency
        ):
            raise ValidationError("Runtime requirements must use exact versions")
    for key in ("documentation", "issue_tracker"):
        if key not in manifest and key == "issue_tracker" and not public:
            continue
        value = manifest.get(key, "")
        if not isinstance(value, str):
            raise ValidationError(f"manifest.{key} must be an HTTPS URL")
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname:
            raise ValidationError(f"manifest.{key} must be an HTTPS URL")
    for owner in manifest["codeowners"]:
        if not isinstance(owner, str) or not re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
            raise ValidationError("Invalid GitHub codeowner")
    if public:
        documentation = manifest["documentation"].rstrip("/")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", documentation):
            raise ValidationError("Public release requires the real GitHub repository URL")
        if manifest.get("issue_tracker") != documentation + "/issues" or not manifest["codeowners"]:
            raise ValidationError("Public release requires repository issues and a codeowner")
    strings = load_json(component / "strings.json")
    expected_leaves = string_leaves(strings)
    for language in ("en", "pl"):
        translated = load_json(component / "translations" / f"{language}.json")
        leaves = string_leaves(translated)
        if leaves.keys() != expected_leaves.keys():
            missing = set(expected_leaves) - set(leaves)
            extra = set(leaves) - set(expected_leaves)
            raise ValidationError(
                f"{language}: translation keys differ (missing={missing}, extra={extra})"
            )
        for key, value in leaves.items():
            if not value.strip() or placeholders(value) != placeholders(expected_leaves[key]):
                raise ValidationError(f"{language}: invalid value/placeholders at {'.'.join(key)}")
    if load_json(component / "translations" / "en.json") != strings:
        raise ValidationError("English translation must match strings.json")
    for path in component_files(root):
        if path.suffix == ".json":
            load_json(path, object_only=False)
    hacs = load_json(root / "hacs.json")
    if hacs.get("name") != manifest["name"] or hacs.get("country") != "PL":
        raise ValidationError("HACS display metadata must match the integration")
    return manifest


def validate_archive(path: Path, root: Path = ROOT) -> None:
    expected = {
        file.relative_to(root).as_posix(): file.read_bytes() for file in component_files(root)
    }
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != set(expected):
                raise ValidationError("Archive file list differs from the integration files")
            for name, content in expected.items():
                if archive.read(name) != content:
                    raise ValidationError(f"Archive content differs: {name}")
    except (OSError, BadZipFile, KeyError) as err:
        raise ValidationError(f"Cannot validate archive {path}: {err}") from err


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release",
        "--public",
        dest="public",
        action="store_true",
        help="Require real GitHub publication metadata",
    )
    parser.add_argument(
        "--archive", type=Path, help="Also compare a component ZIP with its sources"
    )
    args = parser.parse_args()
    try:
        manifest = validate_project(public=args.public)
        if args.archive:
            validate_archive(args.archive)
    except ValidationError as err:
        parser.exit(1, f"Validation failed: {err}\n")
    print(
        f"Project checks passed for {DOMAIN} {manifest['version']}. This is not hassfest/HACS certification."
    )


if __name__ == "__main__":
    main()
