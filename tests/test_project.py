"""Check publication metadata and the actual manual-install package."""

from __future__ import annotations

import json
import shutil
from zipfile import ZipFile

import pytest

from tools.build_release import build_release
from tools.prepare_repository import prepare_repository
from tools.validate_project import (
    COMPONENT,
    ROOT,
    ValidationError,
    validate_archive,
    validate_project,
)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(ROOT / COMPONENT, root / COMPONENT)
    shutil.copyfile(ROOT / "hacs.json", root / "hacs.json")
    return root


def test_translations_have_matching_keys_and_placeholders(project):
    validate_project(project)
    path = project / COMPONENT / "translations/pl.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["unexpected"] = "Brak tego klucza w pliku źródłowym"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="translation keys differ"):
        validate_project(project)


def test_prepare_public_metadata_and_preserve_version(project):
    before = validate_project(project)
    prepare_repository("https://github.com/example/onebox-air/", "example-user", project)
    after = validate_project(project, public=True)
    assert after["version"] == before["version"]
    assert after["documentation"] == "https://github.com/example/onebox-air"
    assert after["issue_tracker"] == "https://github.com/example/onebox-air/issues"
    assert after["codeowners"] == ["@example-user"]


@pytest.mark.parametrize(
    "url,owner",
    [
        ("https://example.com/project", "owner"),
        ("https://github.com/a/b", "@owner"),
        ("https://github.com/a/b", "owner-"),
    ],
)
def test_invalid_publication_metadata_does_not_change_manifest(project, url, owner):
    path = project / COMPONENT / "manifest.json"
    before = path.read_bytes()
    with pytest.raises(ValueError):
        prepare_repository(url, owner, project)
    assert path.read_bytes() == before


def test_unprepared_project_cannot_claim_public_readiness(project):
    path = project / COMPONENT / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(documentation="https://allegro.pl/kampania/one/znajdz-nas", codeowners=[])
    manifest.pop("issue_tracker", None)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    validate_project(project)
    with pytest.raises(ValidationError):
        validate_project(project, public=True)


def test_component_archive_is_installable_reproducible_and_clean(project, tmp_path):
    component = project / COMPONENT
    (component / ".DS_Store").write_bytes(b"not release content")
    cache = component / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "api.cpython-313.pyc").write_bytes(b"not release content")
    archive = build_release(project, tmp_path / "first")
    second = build_release(project, tmp_path / "second")
    assert archive.read_bytes() == second.read_bytes()
    with ZipFile(archive) as package:
        names = package.namelist()
        assert f"{COMPONENT.as_posix()}/manifest.json" in names
        assert f"{COMPONENT.as_posix()}/config_flow.py" in names
        assert not any(".DS_Store" in name or "__pycache__" in name for name in names)
        destination = tmp_path / "config"
        package.extractall(destination)
    assert (
        json.loads((destination / COMPONENT / "manifest.json").read_text())["domain"]
        == "allegro_onebox_air"
    )
    validate_archive(archive, project)
    with ZipFile(archive, "a") as package:
        package.writestr("../unexpected.txt", "invalid release")
    with pytest.raises(ValidationError, match="file list differs"):
        validate_archive(archive, project)
