# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the single-file Windows console executable.

Build with:

    pyinstaller --noconfirm --clean packaging/ridecontroller.spec

PyInstaller cannot cross-compile, so this only produces a .exe when run on
Windows. See .github/workflows/build-exe.yml for the build that does it.
"""

import importlib.util
import os

from PyInstaller.utils.hooks import collect_all

# collect_all raises something fairly opaque for a package that is not
# installed, and a build without vgamepad produces an exe that cannot create a
# pad at all - so say so plainly instead.
if importlib.util.find_spec("vgamepad") is None:
    raise SystemExit(
        "vgamepad is not installed, so the executable would have no virtual "
        "gamepad backend.\n"
        "It is a Windows-only dependency: run this build on Windows, after "
        "`pip install .`."
    )

datas = []
binaries = []
hiddenimports = []

# vgamepad carries ViGEmClient.dll and the ViGEmBus installer as package data.
# Without these the exe builds happily and then fails at runtime the moment it
# tries to create a pad.
#
# bleak ships its own PyInstaller hooks (a pyinstaller40 entry point), which
# pull in the WinRT backend, so it deliberately is not listed here.
for package in ("vgamepad",):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],  # noqa: F821 - SPECPATH is injected
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821 - PYZ is injected

# Passing binaries and datas straight to EXE is what makes this one file
# rather than a directory.
exe = EXE(  # noqa: F821 - EXE is injected
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ridecontroller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
