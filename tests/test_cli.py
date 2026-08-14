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
