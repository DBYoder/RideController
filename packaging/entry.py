"""Entry point for the frozen executable.

PyInstaller needs a real script to start from; ``ridecontroller/__main__.py``
is not usable as one because a frozen build has no ``-m`` to invoke it.
"""

from __future__ import annotations

import multiprocessing
import sys

from ridecontroller.cli import main

if __name__ == "__main__":
    # Without this a frozen process that ever spawns a child re-runs the whole
    # program in it. Nothing here does today, but it costs one call.
    multiprocessing.freeze_support()
    sys.exit(main())
