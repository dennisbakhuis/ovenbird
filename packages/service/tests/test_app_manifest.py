from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

from ovenbird import __version__
from ovenbird.config import DEFAULT_HTTP_PORT, Settings, load_settings
from ovenbird.history.snapshot import TMP_SUFFIX
from ovenbird.instance import LOCK_NAME

ROOT = Path(__file__).resolve().parents[3]
APP_DIR = ROOT / "app" / "ovenbird"
REQUIRED_KEYS = {
    "name",
    "slug",
    "version",
    "description",
    "arch",
    "image",
    "ingress",
    "ingress_port",
    "watchdog",
    "options",
    "schema",
}


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    return loaded


def test_required_keys(manifest: dict[str, Any]) -> None:
    assert manifest.keys() >= REQUIRED_KEYS
    assert manifest["slug"] == "ovenbird"
    assert manifest["image"] == "ghcr.io/dennisbakhuis/ovenbird"
    assert manifest["arch"] == ["amd64", "aarch64"]


def test_backups_contain_only_the_consistent_snapshot(manifest: dict[str, Any]) -> None:
    assert manifest["backup"] == "hot"
    excluded = manifest["backup_exclude"]
    data = PurePosixPath("/data")
    for name in (
        "history.db",
        "history.db-wal",
        "history.db-shm",
        f"history.db{TMP_SUFFIX}",
        f"history.snapshot.db{TMP_SUFFIX}",
        LOCK_NAME,
        "archive/2026-11.db",
        "archive/2026-11.db-journal",
        f"archive/2026-10.zip{TMP_SUFFIX}",
    ):
        assert any((data / name).match(pattern) for pattern in excluded), name
    for kept in ("history.snapshot.db", "options.json", "archive/2026-10.zip"):
        assert not any((data / kept).match(pattern) for pattern in excluded), kept


def test_dockerfile_pins_multi_arch_bases_and_uses_the_launcher() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for line in dockerfile.splitlines():
        if line.startswith("FROM ") or "COPY --from=ghcr.io" in line:
            assert "@sha256:" in line, line
    assert 'ENTRYPOINT ["python", "-m", "ovenbird.launcher"]' in dockerfile
    assert 'CMD ["python", "-m", "ovenbird.launcher", "--check"]' in dockerfile


def test_version_and_ports_match_the_service(manifest: dict[str, Any]) -> None:
    assert manifest["version"] == __version__
    assert manifest["ingress"] is True
    assert manifest["ingress_port"] == DEFAULT_HTTP_PORT
    assert f":{DEFAULT_HTTP_PORT}" in manifest["watchdog"]
    assert manifest["watchdog"].endswith("/api/v1/health")


def test_least_privilege(manifest: dict[str, Any]) -> None:
    assert manifest["host_network"] is False
    assert not manifest.get("map")
    assert "hassio_api" not in manifest
    assert all(value is None for value in manifest["ports"].values())


def test_options_match_schema_and_settings(manifest: dict[str, Any]) -> None:
    assert set(manifest["options"]) <= set(manifest["schema"])
    assert set(manifest["schema"]) <= set(Settings.model_fields)
    for name in ("mqtt_password", "admin_password"):
        assert manifest["schema"][name].startswith("password")


def test_default_options_load_as_settings(
    manifest: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(manifest["options"]), encoding="utf-8")
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(path))
    monkeypatch.setenv("OVENBIRD_INGRESS", "true")
    settings = load_settings()
    assert settings.mqtt_host == "core-mosquitto"
    assert settings.ingress_mode


def test_translations_cover_every_option(manifest: dict[str, Any]) -> None:
    for language in ("en", "nl"):
        text = (APP_DIR / "translations" / f"{language}.yaml").read_text(encoding="utf-8")
        translated = yaml.safe_load(text)["configuration"]
        assert set(translated) == set(manifest["schema"]), language


def test_repository_manifest() -> None:
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
    assert repository["name"] == "ovenbird"
    assert repository["maintainer"] == "Dennis Bakhuis"
    assert repository["url"].startswith("https://github.com/")


def test_docs_files_exist() -> None:
    for name in ("DOCS.md", "CHANGELOG.md"):
        assert (APP_DIR / name).is_file()
