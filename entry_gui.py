"""Root-level launcher for the desktop GUI.

Used as the PyInstaller entry script (battery_gui.spec) and as a convenient
`python entry_gui.py` target. Importing through the package guarantees every
module has proper package context, so relative imports always resolve.
"""
import sys

from battery_notifier.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
