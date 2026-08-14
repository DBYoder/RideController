"""Control panel tests.

The module imports tkinter at import time, and creating a window needs a
display, so both are skipped rather than failed where they are unavailable.
"""

import queue

import pytest

gui = pytest.importorskip("ridecontroller.gui", reason="tkinter is not available")

from ridecontroller.mapping import NEUTRAL, OutputState  # noqa: E402
from ridecontroller.outputs import NullOutput  # noqa: E402


@pytest.fixture
def root():
    """A hidden Tk root, skipped where no display exists."""
    import tkinter as tk

    try:
        window = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no display available: {exc}")
    window.withdraw()
    yield window
    window.destroy()


class RecordingOutput(NullOutput):
    def __init__(self):
        self.applied = []
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def apply(self, state):
        self.applied.append(state)

    def reset(self):
        self.applied.append(NEUTRAL)

    def close(self):
        self.closed = True


def test_observed_output_forwards_and_copies():
    inner = RecordingOutput()
    seen = []
    observed = gui._ObservedOutput(inner, seen.append)

    observed.open()
    state = OutputState(buttons=frozenset({"A"}))
    observed.apply(state)
    observed.close()

    assert inner.opened and inner.closed
    assert inner.applied == [state]
    assert seen == [state]


def test_observed_output_reports_a_reset_as_neutral():
    inner = RecordingOutput()
    seen = []
    observed = gui._ObservedOutput(inner, seen.append)

    observed.reset()

    assert seen == [NEUTRAL]


def test_observed_output_keeps_the_backend_name():
    assert gui._ObservedOutput(RecordingOutput(), lambda s: None).name == "null"


# -- widget behaviour ------------------------------------------------------


def _app(root, config):
    app = gui.App(root, config)
    return app


def test_pressed_buttons_are_highlighted(root, tmp_path):
    from ridecontroller.config import load_config

    app = _app(root, load_config(None))
    app._show_state(OutputState(buttons=frozenset({"A", "DPAD_UP"})))

    assert app._button_labels["A"].cget("bg") == gui._ACTIVE_BG
    assert app._button_labels["DPAD_UP"].cget("bg") == gui._ACTIVE_BG
    assert app._button_labels["B"].cget("bg") == gui._IDLE_BG


def test_triggers_track_the_state(root):
    from ridecontroller.config import load_config

    app = _app(root, load_config(None))
    app._show_state(OutputState(left_trigger=200, right_trigger=0))

    assert app.left_trigger["value"] == 200
    assert app.right_trigger["value"] == 0


def test_battery_does_not_accumulate_on_the_controller_line(root):
    """Rebuilt from stored values, not by parsing the label back out."""
    from ridecontroller.config import load_config

    app = _app(root, load_config(None))
    app._handle("connected", ["Zwift Ride"])
    app._handle("battery", {"aa": 87})
    app._handle("battery", {"aa": 86})
    app._handle("battery", {"aa": 85})

    text = app.controller_value.cget("text")
    assert text.count("battery") == 1
    assert "85%" in text


def test_a_failure_reason_survives_the_stop_that_follows_it(root):
    from ridecontroller.config import load_config

    app = _app(root, load_config(None))
    app._handle("error", "No Zwift Ride controller found")
    app._handle("stopped", None)

    assert "No Zwift Ride controller found" in app.message.cget("text")
    assert app.toggle.cget("text") == "Start bridge"


def test_stopping_without_an_error_says_so(root):
    from ridecontroller.config import load_config

    app = _app(root, load_config(None))
    app._handle("connected", ["Zwift Ride"])
    app._handle("stopped", None)

    assert app.message.cget("text") == "Stopped."
    assert app.controller_value.cget("text") == "not connected"


def test_a_missing_driver_offers_the_install_button(root):
    from ridecontroller.config import load_config

    app = _app(root, load_config(None))
    app._handle("driver", (False, "could not reach the ViGEmBus driver"))
    assert app.driver_button.winfo_manager() == "grid"

    app._handle("driver", (True, ""))
    assert app.driver_value.cget("text") == "OK"
    assert app.driver_button.winfo_manager() == ""


def test_bridge_thread_is_not_running_before_it_starts():
    from ridecontroller.config import load_config

    thread = gui.BridgeThread(load_config(None), queue.Queue())
    assert thread.running is False
    thread.stop()  # must be harmless before start
