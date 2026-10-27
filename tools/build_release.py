#!/usr/bin/env python3
"""Build and verify the manual-install component ZIP without publishing it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# Also support importing this tool in offline tests.
if __package__:
    from .validate_project import (
        ROOT,
        ValidationError,
        component_files,
        validate_archive,
        validate_project,
    )
else:
    from validate_project import (
        ROOT,
        ValidationError,
        component_files,
        validate_archive,
        validate_project,
    )


def build_release(root: Path = ROOT, output: Path | None = None, *, public: bool = False) -> Path:
    manifest = validate_project(root, public=public)
    destination = output if output is not None else root / "dist"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"obox-air-component-{manifest['version']}.zip"
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for source in component_files(root):
            member = ZipInfo(source.relative_to(root).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            member.compress_type = ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            archive.writestr(member, source.read_bytes())
    validate_archive(path, root)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output directory (default: dist)")
    parser.add_argument(
        "--release",
        "--public",
        dest="public",
        action="store_true",
        help="Require real GitHub repository metadata",
    )
    args = parser.parse_args()
    try:
        result = build_release(output=args.output, public=args.public)
    except (ValidationError, OSError) as err:
        parser.exit(1, f"Build failed: {err}\n")
    print(result)


if __name__ == "__main__":
    sys.exit(main())
