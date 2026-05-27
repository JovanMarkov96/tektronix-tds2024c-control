#!/usr/bin/env python3
"""User-friendly launcher for the Tektronix TDS2024C GUI.

Just run this file:

    python launch_gui.py

Unlike ``src/tektronix_tds2024c/gui_app.py`` (which uses package-relative
imports and must be run as a module), this script adds the package ``src``
directory to the import path first, so it works when run directly — including
by double-clicking, or from a one-line .bat/.sh wrapper.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tektronix_tds2024c.gui_app import main  # noqa: E402

if __name__ == "__main__":
    main()
