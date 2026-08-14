"""A small Tkinter control panel for the bridge.

The bridge is asyncio and Tk is not thread-safe, so the two never touch: the
bridge runs its own event loop on a daemon thread and posts plain tuples to a
queue, and the UI drains that queue from a Tk ``after`` callback on the main
thread. Nothing in this module calls a widget method off the main thread.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .bridge import Bridge
from .config import Config
from .driver import VIGEMBUS_RELEASES, describe_exit_code, find_installer, run_installer
from .mapping import NEUTRAL, OutputState, TRIGGER_MAX
from .outputs import GamepadOutput, OutputError, create_output

#: Buttons drawn in the live display, in two rows of a sensible width.
_BUTTON_ROWS = (
    ("A", "B", "X", "Y"),
    ("LB", "RB", "LS", "RS"),
    ("BACK", "START", "GUIDE"),
    ("DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"),
)

_IDLE_BG = "#e9e9e9"
_ACTIVE_BG = "#2f7d32"
_IDLE_FG = "#555555"
_ACTIVE_FG = "#ffffff"


class _ObservedOutput(GamepadOutput):
    """Forwards to a real backend and copies each state to the UI."""

    def __init__(self, inner: GamepadOutput, sink: Any) -> None:
        self._inner = inner
        self._sink = sink
        self.name = inner.name

    def open(self) -> None:
        self._inner.open()

    def apply(self, state: OutputState) -> None:
        self._inner.apply(state)
        self._sink(state)

    def reset(self) -> None:
        self._inner.reset()
        self._sink(NEUTRAL)

    def close(self) -> None:
        self._inner.close()


class BridgeThread:
    """Runs a :class:`Bridge` on its own event loop, off the UI thread."""

    def __init__(self, config: Config, events: queue.Queue) -> None:
        self._config = config
        self._events = events
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the bridge to wind down. Returns without waiting."""
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)

    def _post(self, kind: str, payload: Any = None) -> None:
        self._events.put((kind, payload))

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._pump())
        except Exception as exc:  # surfaced in the UI, never a bare traceback
            self._post("error", str(exc))
        finally:
            self._post("stopped")
            self._loop = None
            self._stop = None
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    async def _pump(self) -> None:
        self._stop = asyncio.Event()
        self._post("scanning")

        backend = create_output(self._config.output.backend)
        observed = _ObservedOutput(backend, lambda state: self._post("state", state))

        bridge = Bridge(self._config, observed)
        original_discover = bridge.discover

        async def discover_and_report():
            controllers = await original_discover()
            self._post("connected", [c.label() for c in controllers])
            return controllers

        bridge.discover = discover_and_report  # type: ignore[method-assign]

        battery_seen: dict[str, int] = {}

        async def watch_battery() -> None:
            # Bridge logs battery rather than exposing a callback, so poll the
            # dict it maintains. Cheap, and keeps bridge.py unchanged.
            assert self._stop is not None
            while not self._stop.is_set():
                if bridge.battery != battery_seen:
                    battery_seen.clear()
                    battery_seen.update(bridge.battery)
                    self._post("battery", dict(battery_seen))
                await asyncio.sleep(1.0)

        watcher = asyncio.ensure_future(watch_battery())
        try:
            await bridge.run(self._stop)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


class App(ttk.Frame):
    """The control panel window."""

    def __init__(self, master: tk.Tk, config: Config) -> None:
        super().__init__(master, padding=12)
        self.config_obj = config
        self.events: queue.Queue = queue.Queue()
        self.bridge = BridgeThread(config, self.events)
        self._button_labels: dict[str, tk.Label] = {}
        # Held rather than read back off the widgets, so the two halves of the
        # controller line can be rebuilt without parsing the label text.
        self._controllers = "not connected"
        self._battery = ""
        self._errored = False

        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._build_status()
        self._build_controls()
        self._build_live()

        self.after(50, self._drain)
        self.after(0, self._refresh_driver)

    # -- layout ------------------------------------------------------------

    def _build_status(self) -> None:
        box = ttk.LabelFrame(self, text="Status", padding=8)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="ViGEmBus").grid(row=0, column=0, sticky="w")
        self.driver_value = ttk.Label(box, text="checking...")
        self.driver_value.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.driver_button = ttk.Button(
            box, text="Install driver", command=self._install_driver
        )
        self.driver_button.grid(row=0, column=2, sticky="e")
        self.driver_button.grid_remove()

        ttk.Label(box, text="Controller").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.controller_value = ttk.Label(box, text="not connected")
        self.controller_value.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

    def _build_controls(self) -> None:
        row = ttk.Frame(self, padding=(0, 10))
        row.grid(row=1, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)

        self.toggle = ttk.Button(row, text="Start bridge", command=self._toggle)
        self.toggle.grid(row=0, column=0, sticky="ew", ipady=4)

        self.message = ttk.Label(self, text="Ready.", foreground="#555555")
        self.message.grid(row=2, column=0, sticky="w")

    def _build_live(self) -> None:
        box = ttk.LabelFrame(self, text="Live input", padding=8)
        box.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.rowconfigure(3, weight=1)
        box.columnconfigure(0, weight=1)

        grid = ttk.Frame(box)
        grid.grid(row=0, column=0, sticky="w")
        for r, names in enumerate(_BUTTON_ROWS):
            for c, name in enumerate(names):
                label = tk.Label(
                    grid,
                    text=name.replace("DPAD_", ""),
                    width=7,
                    padx=4,
                    pady=3,
                    bg=_IDLE_BG,
                    fg=_IDLE_FG,
                    relief="flat",
                )
                label.grid(row=r, column=c, padx=2, pady=2, sticky="w")
                self._button_labels[name] = label

        triggers = ttk.Frame(box, padding=(0, 8, 0, 0))
        triggers.grid(row=1, column=0, sticky="ew")
        # uniform= keeps the two bars the same width whatever the frame does,
        # so an equal press does not look unequal.
        triggers.columnconfigure(1, weight=1, uniform="trigger")
        triggers.columnconfigure(3, weight=1, uniform="trigger")

        ttk.Label(triggers, text="LT").grid(row=0, column=0, sticky="w")
        self.left_trigger = ttk.Progressbar(triggers, maximum=TRIGGER_MAX, length=110)
        self.left_trigger.grid(row=0, column=1, sticky="ew", padx=(4, 12))
        ttk.Label(triggers, text="RT").grid(row=0, column=2, sticky="w")
        self.right_trigger = ttk.Progressbar(triggers, maximum=TRIGGER_MAX, length=110)
        self.right_trigger.grid(row=0, column=3, sticky="ew", padx=(4, 0))

        self.sticks = ttk.Label(box, text="sticks  L 0,0   R 0,0")
        self.sticks.grid(row=2, column=0, sticky="w", pady=(8, 0))

    # -- driver ------------------------------------------------------------

    def _refresh_driver(self) -> None:
        """Probe the driver off the UI thread; it can block briefly."""

        def probe() -> None:
            try:
                output = create_output("xbox360")
                output.open()
                output.reset()
                output.close()
            except OutputError as exc:
                self.events.put(("driver", (False, str(exc))))
            except Exception as exc:
                self.events.put(("driver", (False, str(exc))))
            else:
                self.events.put(("driver", (True, "")))

        threading.Thread(target=probe, daemon=True).start()

    def _install_driver(self) -> None:
        msi = find_installer()
        if msi is None:
            messagebox.showerror(
                "RideController",
                "No bundled ViGEmBus installer was found.\n\n"
                f"Download and run it from:\n{VIGEMBUS_RELEASES}",
            )
            return

        self.driver_button.state(["disabled"])
        self._say("Running the ViGEmBus installer...")

        def install() -> None:
            succeeded, text = describe_exit_code(run_installer(msi))
            self.events.put(("installed", (succeeded, text)))

        threading.Thread(target=install, daemon=True).start()

    # -- bridge ------------------------------------------------------------

    def _toggle(self) -> None:
        if self.bridge.running:
            self._say("Stopping...")
            self.toggle.state(["disabled"])
            self.bridge.stop()
        else:
            self.bridge.start()
            self.toggle.configure(text="Stop bridge")
            self._say("Scanning for a controller...")

    def _say(self, text: str, error: bool = False) -> None:
        self._errored = error
        self.message.configure(text=text, foreground="#b3261e" if error else "#555555")

    def _show_controllers(self) -> None:
        text = self._controllers
        if self._battery:
            text = f"{text}   battery {self._battery}"
        self.controller_value.configure(text=text)

    # -- event pump --------------------------------------------------------

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.after(50, self._drain)

    def _handle(self, kind: str, payload: Any) -> None:
        if kind == "state":
            self._show_state(payload)
        elif kind == "scanning":
            self._controllers = "scanning..."
            self._battery = ""
            self._show_controllers()
        elif kind == "connected":
            self._controllers = ", ".join(payload) or "connected"
            self._show_controllers()
            self._say("Connected. Leave this open while you play.")
        elif kind == "battery":
            self._battery = "  ".join(f"{pct}%" for pct in payload.values())
            self._show_controllers()
        elif kind == "error":
            self._say(payload, error=True)
        elif kind == "stopped":
            self.toggle.state(["!disabled"])
            self.toggle.configure(text="Start bridge")
            self._controllers = "not connected"
            self._battery = ""
            self._show_controllers()
            self._show_state(NEUTRAL)
            # Keep a failure reason on screen rather than replacing it.
            if not self._errored:
                self._say("Stopped.")
        elif kind == "driver":
            ok, detail = payload
            if ok:
                self.driver_value.configure(text="OK", foreground="#2f7d32")
                self.driver_button.grid_remove()
            else:
                self.driver_value.configure(text="not working", foreground="#b3261e")
                self.driver_button.grid()
                self.driver_button.state(["!disabled"])
                if detail:
                    self._say(detail.splitlines()[0], error=True)
        elif kind == "installed":
            succeeded, text = payload
            self.driver_button.state(["!disabled"])
            self._say(text, error=not succeeded)
            if succeeded:
                self._refresh_driver()

    def _show_state(self, state: OutputState) -> None:
        for name, label in self._button_labels.items():
            pressed = name in state.buttons
            label.configure(
                bg=_ACTIVE_BG if pressed else _IDLE_BG,
                fg=_ACTIVE_FG if pressed else _IDLE_FG,
            )
        self.left_trigger.configure(value=state.left_trigger)
        self.right_trigger.configure(value=state.right_trigger)
        self.sticks.configure(
            text="sticks  L %d,%d   R %d,%d"
            % (state.left_stick + state.right_stick)
        )

    def shutdown(self) -> None:
        if self.bridge.running:
            self.bridge.stop()


def run(config: Config) -> int:
    """Open the control panel. Returns when the window closes."""
    root = tk.Tk()
    root.title("RideController")
    root.minsize(430, 400)

    app = App(root, config)

    def on_close() -> None:
        app.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0
