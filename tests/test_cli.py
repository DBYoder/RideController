import pytest

from ridecontroller.cli import main


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    """Keep the tests away from a real config file on the developer's machine."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path


def test_init_config_writes_a_loadable_file(tmp_path, capsys):
    path = tmp_path / "config.toml"
    assert main(["init-config", "--path", str(path)]) == 0
    assert path.exists()
    assert "Wrote" in capsys.readouterr().out
    assert main(["--config", str(path), "outputs"]) == 0


def test_init_config_will_not_overwrite_without_force(tmp_path):
    path = tmp_path / "config.toml"
    assert main(["init-config", "--path", str(path)]) == 0
    assert main(["init-config", "--path", str(path)]) == 1
    assert main(["init-config", "--path", str(path), "--force"]) == 0


def test_outputs_lists_the_mapping(capsys):
    assert main(["outputs"]) == 0
    out = capsys.readouterr().out
    assert "dpad_up" in out
    assert "left_paddle" in out
    assert "DPAD_UP" in out


def test_outputs_reflects_a_custom_config(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[buttons]\na = "START"\n', encoding="utf-8")
    assert main(["--config", str(path), "outputs"]) == 0
    assert "a                  -> START" in capsys.readouterr().out


def test_a_broken_config_is_reported_as_an_error(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[buttons]\na = "TRIANGLE"\n', encoding="utf-8")
    assert main(["--config", str(path), "outputs"]) == 2
    assert "error:" in capsys.readouterr().err


def test_missing_config_file_is_reported(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "absent.toml"), "outputs"]) == 2
    assert "not found" in capsys.readouterr().err


def test_simulate_runs_against_the_debug_backend(capsys):
    assert main(["simulate", "--backend", "debug", "--hold", "0"]) == 0
    out = capsys.readouterr().out
    assert "dpad_up            -> DPAD_UP" in out
    assert "onoff_left         -> (unmapped)" in out
    assert "left_paddle        -> LT (ramp)" in out


def test_unknown_backend_is_an_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--backend", "nintendo"])
    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


def _stub_scan(monkeypatch):
    """Keep doctor away from a real Bluetooth radio."""

    async def no_controllers(*args, **kwargs):
        return []

    monkeypatch.setattr("ridecontroller.cli.scan", no_controllers)


def test_doctor_survives_vgamepad_raising_during_import(monkeypatch, capsys):
    """The check that reports a missing driver must not crash on one.

    vgamepad raises a bare Exception at import time when ViGEmBus is absent,
    so catching only ImportError took down the whole command.
    """
    import builtins

    _stub_scan(monkeypatch)
    real_import = builtins.__import__

    def exploding_import(name, *args, **kwargs):
        if name == "vgamepad":
            raise Exception("VIGEM_ERROR_BUS_NOT_FOUND")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", exploding_import)

    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "VIGEM_ERROR_BUS_NOT_FOUND" in out
    assert "install-driver" in out
    assert "Some checks failed" in out


def test_doctor_still_reports_a_missing_vgamepad_package(monkeypatch, capsys):
    _stub_scan(monkeypatch)
    monkeypatch.setitem(__import__("sys").modules, "vgamepad", None)

    assert main(["doctor"]) == 1
    assert "vgamepad is not installed" in capsys.readouterr().out


def test_install_driver_refuses_off_windows(monkeypatch, capsys):
    monkeypatch.setattr("ridecontroller.cli.platform.system", lambda: "Linux")
    assert main(["install-driver"]) == 2
    assert "Windows driver" in capsys.readouterr().err


def test_install_driver_points_at_the_download_when_unbundled(monkeypatch, capsys):
    monkeypatch.setattr("ridecontroller.cli.platform.system", lambda: "Windows")
    monkeypatch.setattr("ridecontroller.cli.find_installer", lambda *a, **k: None)
    assert main(["install-driver"]) == 1
    assert "nefarius/ViGEmBus" in capsys.readouterr().err


def test_install_driver_reports_a_reboot_requirement(monkeypatch, tmp_path, capsys):
    msi = tmp_path / "ViGEmBusSetup_x64.msi"
    msi.write_bytes(b"")
    monkeypatch.setattr("ridecontroller.cli.platform.system", lambda: "Windows")
    monkeypatch.setattr("ridecontroller.cli.find_installer", lambda *a, **k: msi)
    monkeypatch.setattr("ridecontroller.cli.run_installer", lambda *a, **k: 3010)

    assert main(["install-driver"]) == 0
    assert "Reboot" in capsys.readouterr().out


def test_install_driver_reports_a_cancelled_install(monkeypatch, tmp_path, capsys):
    msi = tmp_path / "ViGEmBusSetup_x64.msi"
    msi.write_bytes(b"")
    monkeypatch.setattr("ridecontroller.cli.platform.system", lambda: "Windows")
    monkeypatch.setattr("ridecontroller.cli.find_installer", lambda *a, **k: msi)
    monkeypatch.setattr("ridecontroller.cli.run_installer", lambda *a, **k: 1602)

    assert main(["install-driver"]) == 1
    assert "cancelled" in capsys.readouterr().out


def test_no_arguments_opens_the_control_panel(monkeypatch):
    """Double-clicking the exe passes no arguments; that must not be an error."""
    called = {}

    def fake_gui(args, config):
        called["command"] = args.command
        return 0

    monkeypatch.setattr("ridecontroller.cli.cmd_gui", fake_gui)
    assert main([]) == 0
    assert called["command"] == "gui"


def test_an_unknown_command_is_still_an_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["nonsense"])
    assert excinfo.value.code == 2
