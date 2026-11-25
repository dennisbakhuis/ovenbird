from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ovenbird.launcher import (
    LauncherError,
    Plan,
    System,
    data_dir,
    drop_privileges,
    launch,
    main,
    plan,
    repair_ownership,
    target_ids,
)

SERVICE_UID = 10001


class FakeOs:
    def __init__(self, euid: int = 0, *, regain: bool = False, ignore_setuid: bool = False) -> None:
        self.uid = self.euid = euid
        self.gid = self.egid = euid
        self.groups: list[int] | None = None
        self.calls: list[tuple[Any, ...]] = []
        self.chowned: list[tuple[str, int, int, int | None]] = []
        self.regain = regain
        self.ignore_setuid = ignore_setuid
        self.exec: tuple[str, list[str]] | None = None

    def setgroups(self, groups: list[int]) -> None:
        self.calls.append(("setgroups", groups))
        self.groups = groups

    def setgid(self, gid: int) -> None:
        self.calls.append(("setgid", gid))
        self.gid = self.egid = gid

    def setuid(self, uid: int) -> None:
        self.calls.append(("setuid", uid))
        if not self.ignore_setuid:
            self.uid = self.euid = uid

    def chown(self, path: str, uid: int, gid: int, *, dir_fd: int | None) -> None:
        self.chowned.append((path, uid, gid, dir_fd))

    def execv(self, path: str, args: list[str]) -> None:
        self.calls.append(("execv",))
        self.exec = (path, args)

    def system(self) -> System:
        return replace(
            System(),
            geteuid=lambda: self.euid,
            getuid=lambda: self.uid,
            getegid=lambda: self.egid,
            setgroups=self.setgroups,
            setgid=self.setgid,
            setuid=self.setuid,
            chown=self.chown,
            cannot_regain_root=lambda: not self.regain,
            execv=self.execv,
        )


def root_owned_tree(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "sub").mkdir(parents=True)
    (data / "options.json").write_text("{}", encoding="utf-8")
    os.chmod(data / "options.json", 0o600)
    (data / "sub" / "history.db").write_bytes(b"")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    (data / "link").symlink_to(outside)
    (data / "dirlink").symlink_to(tmp_path, target_is_directory=True)
    return data


@pytest.mark.parametrize(
    ("euid", "args", "expected"),
    [
        (10001, [], Plan(repair=False, drop=False)),
        (1000, ["--check"], Plan(repair=False, drop=False)),
        (0, [], Plan(repair=True, drop=True)),
        (0, ["--check"], Plan(repair=False, drop=True)),
        (0, ["--version"], Plan(repair=False, drop=True)),
    ],
)
def test_plan(euid: int, args: list[str], expected: Plan) -> None:
    assert plan(euid, args) == expected


def test_target_ids_default_and_refuse_root() -> None:
    assert target_ids({}) == (SERVICE_UID, SERVICE_UID)
    assert target_ids({"OVENBIRD_UID": "1000", "OVENBIRD_GID": "100"}) == (1000, 100)
    for bad in ("0", "-1", "root", ""):
        with pytest.raises(LauncherError):
            target_ids({"OVENBIRD_UID": bad})


def test_data_dir_from_environment(tmp_path: Path) -> None:
    assert data_dir({}) == Path("/data")
    assert data_dir({"OVENBIRD_DATA_DIR": str(tmp_path)}) == tmp_path


def test_repair_gives_a_root_owned_tree_to_the_service_user(tmp_path: Path) -> None:
    data = root_owned_tree(tmp_path)
    fake = FakeOs()
    changed = repair_ownership(data, SERVICE_UID, SERVICE_UID, fake.system())
    names = sorted(Path(path).name for path, *_ in fake.chowned)
    assert names == ["data", "dirlink", "history.db", "link", "options.json", "sub"]
    assert changed == 6
    assert all(dir_fd is not None for path, _, _, dir_fd in fake.chowned if path != str(data))
    assert (tmp_path / "outside.txt").read_text(encoding="utf-8") == "keep"


def test_repair_leaves_a_correctly_owned_tree_alone(tmp_path: Path) -> None:
    data = root_owned_tree(tmp_path)
    fake = FakeOs()
    assert repair_ownership(data, os.getuid(), os.getgid(), fake.system()) == 0
    assert fake.chowned == []


def test_repair_creates_a_missing_data_dir(tmp_path: Path) -> None:
    fake = FakeOs()
    repair_ownership(tmp_path / "new" / "data", SERVICE_UID, SERVICE_UID, fake.system())
    assert (tmp_path / "new" / "data").is_dir()


def test_repair_refuses_a_file_as_data_dir(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        repair_ownership(path, SERVICE_UID, SERVICE_UID, FakeOs().system())


def test_drop_privileges_order_and_verification() -> None:
    fake = FakeOs()
    drop_privileges(SERVICE_UID, SERVICE_UID, fake.system())
    assert fake.calls == [("setgroups", []), ("setgid", SERVICE_UID), ("setuid", SERVICE_UID)]
    with pytest.raises(LauncherError, match="regained"):
        drop_privileges(SERVICE_UID, SERVICE_UID, FakeOs(regain=True).system())
    with pytest.raises(LauncherError, match="did not take effect"):
        drop_privileges(SERVICE_UID, SERVICE_UID, FakeOs(ignore_setuid=True).system())


def test_launch_as_root_repairs_drops_and_execs(tmp_path: Path) -> None:
    data = root_owned_tree(tmp_path)
    fake = FakeOs()
    launch([], {"OVENBIRD_DATA_DIR": str(data)}, fake.system())
    assert fake.chowned
    assert [call[0] for call in fake.calls] == ["setgroups", "setgid", "setuid", "execv"]
    assert fake.exec == (sys.executable, [sys.executable, "-m", "ovenbird"])
    assert fake.euid == SERVICE_UID


def test_launch_check_as_root_drops_without_repair(tmp_path: Path) -> None:
    data = root_owned_tree(tmp_path)
    fake = FakeOs()
    launch(["--check"], {"OVENBIRD_DATA_DIR": str(data)}, fake.system())
    assert fake.chowned == []
    assert fake.euid == SERVICE_UID
    assert fake.exec == (sys.executable, [sys.executable, "-m", "ovenbird", "--check"])


def test_launch_as_non_root_execs_unchanged(tmp_path: Path) -> None:
    fake = FakeOs(euid=SERVICE_UID)
    launch(["--check"], {"OVENBIRD_DATA_DIR": str(tmp_path)}, fake.system())
    assert fake.calls == [("execv",)]
    assert fake.chowned == []


def test_launch_continues_when_repair_fails(tmp_path: Path) -> None:
    fake = FakeOs()

    def refuse(path: str, uid: int, gid: int, *, dir_fd: int | None) -> None:
        raise PermissionError(1, "Operation not permitted")

    system = replace(fake.system(), chown=refuse)
    launch([], {"OVENBIRD_DATA_DIR": str(root_owned_tree(tmp_path))}, system)
    assert fake.exec is not None
    assert fake.euid == SERVICE_UID


def test_main_reports_unsafe_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*args: Any) -> None:
        raise LauncherError("root could be regained after dropping privileges")

    monkeypatch.setattr("ovenbird.launcher.launch", failing)
    assert main([]) == 1


def test_root_owned_data_dir_fails_cleanly_without_the_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from ovenbird.__main__ import main as service_main

    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o500)
    monkeypatch.setenv("OVENBIRD_DATA_DIR", str(data))
    monkeypatch.setenv("OVENBIRD_HTTP_PORT", "0")
    try:
        if os.access(data, os.W_OK):
            pytest.skip("running with privileges that ignore directory permissions")
        assert service_main([]) == 1
    finally:
        data.chmod(0o700)
    assert any("not writable by uid" in message for message in caplog.messages)
