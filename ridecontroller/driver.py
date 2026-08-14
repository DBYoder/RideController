"""Finding and running the bundled ViGEmBus installer.

``vgamepad`` ships the ViGEmBus MSI as package data and runs it from its own
``setup.py``, so a pip install gets the driver as a side effect. A frozen
executable never runs that ``setup.py``: the MSI is still bundled inside the
exe, but nothing invokes it, and the first thing the user sees is a driver
that was never installed.

Nothing here imports ``vgamepad``. Importing it is what fails when the driver
is missing, which is the one situation this module exists for.
"""

from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from pathlib import Path

#: Where to send someone whose bundled copy is missing.
VIGEMBUS_RELEASES = "https://github.com/nefarius/ViGEmBus/releases"

#: msiexec exit codes worth naming.
_MSI_SUCCESS = 0
_MSI_REBOOT_REQUIRED = 3010
_MSI_USER_CANCELLED = 1602


def target_arch() -> str:
    """``x64`` or ``x86``, matching the directory names vgamepad uses."""
    machine = platform.machine()
    if machine.endswith("64"):
        return "x64"
    if machine.endswith("86"):
        return "x86"
    return "x64" if sys.maxsize > 2**32 else "x86"


def _vgamepad_data_root() -> Path | None:
    """Locate vgamepad's package directory without importing it."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks collected package data under _MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if not meipass:
            return None
        bundled = Path(meipass) / "vgamepad"
        return bundled if bundled.is_dir() else None

    spec = importlib.util.find_spec("vgamepad")
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).parent


def find_installer(arch: str | None = None) -> Path | None:
    """Path to the bundled ViGEmBus MSI, or ``None`` if it is not there."""
    root = _vgamepad_data_root()
    if root is None:
        return None
    arch = arch or target_arch()
    msi = root / "win" / "vigem" / "install" / arch / f"ViGEmBusSetup_{arch}.msi"
    return msi if msi.is_file() else None


def run_installer(msi: Path, quiet: bool = False) -> int:
    """Hand the MSI to msiexec and return its exit code.

    Interactive by default: this is normally run by someone sitting in front
    of the machine, and Windows has to raise a UAC prompt regardless.
    """
    command = ["msiexec", "/i", str(msi)]
    if quiet:
        command += ["/quiet", "/norestart"]
    return subprocess.run(command).returncode


def describe_exit_code(code: int) -> tuple[bool, str]:
    """Turn an msiexec exit code into (succeeded, message)."""
    if code == _MSI_SUCCESS:
        return True, "ViGEmBus installed."
    if code == _MSI_REBOOT_REQUIRED:
        return True, "ViGEmBus installed. Reboot before using the virtual pad."
    if code == _MSI_USER_CANCELLED:
        return False, "Installation was cancelled."
    return False, f"The installer failed with exit code {code}."
