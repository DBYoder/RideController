"""Locating the bundled ViGEmBus installer."""

import sys

from ridecontroller.driver import (
    describe_exit_code,
    find_installer,
    target_arch,
)


def _make_vgamepad_tree(root, arch="x64"):
    """A stand-in for vgamepad's package data layout."""
    install_dir = root / "vgamepad" / "win" / "vigem" / "install" / arch
    install_dir.mkdir(parents=True)
    msi = install_dir / f"ViGEmBusSetup_{arch}.msi"
    msi.write_bytes(b"not really an msi")
    return msi


def test_target_arch_is_one_of_the_two_vgamepad_ships():
    assert target_arch() in {"x64", "x86"}


def test_find_installer_returns_none_when_vgamepad_is_absent(monkeypatch):
    monkeypatch.setattr("ridecontroller.driver._vgamepad_data_root", lambda: None)
    assert find_installer() is None


def test_find_installer_locates_the_bundled_msi(monkeypatch, tmp_path):
    msi = _make_vgamepad_tree(tmp_path)
    monkeypatch.setattr(
        "ridecontroller.driver._vgamepad_data_root", lambda: tmp_path / "vgamepad"
    )
    assert find_installer(arch="x64") == msi


def test_find_installer_returns_none_for_a_missing_architecture(monkeypatch, tmp_path):
    _make_vgamepad_tree(tmp_path, arch="x64")
    monkeypatch.setattr(
        "ridecontroller.driver._vgamepad_data_root", lambda: tmp_path / "vgamepad"
    )
    assert find_installer(arch="x86") is None


def test_frozen_builds_look_under_meipass(monkeypatch, tmp_path):
    """PyInstaller unpacks collected package data under sys._MEIPASS."""
    _make_vgamepad_tree(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert find_installer(arch="x64") is not None


def test_unfrozen_builds_do_not_consult_meipass(monkeypatch, tmp_path):
    """_MEIPASS means nothing outside a frozen build."""
    _make_vgamepad_tree(tmp_path)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)

    found = find_installer(arch="x64")
    # Off Windows there is no vgamepad and this is None; on Windows it
    # resolves through the real package. Either way it must not come from
    # the _MEIPASS tree planted above.
    assert found is None or tmp_path not in found.parents


def test_exit_code_zero_is_success():
    succeeded, message = describe_exit_code(0)
    assert succeeded
    assert "installed" in message


def test_exit_code_3010_is_success_pending_reboot():
    succeeded, message = describe_exit_code(3010)
    assert succeeded
    assert "Reboot" in message


def test_exit_code_1602_is_a_cancelled_install():
    succeeded, message = describe_exit_code(1602)
    assert not succeeded
    assert "cancelled" in message


def test_an_unknown_exit_code_is_reported_verbatim():
    succeeded, message = describe_exit_code(1603)
    assert not succeeded
    assert "1603" in message
