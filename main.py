"""Launcher kept at the repo root so run.bat, the Desktop / Start-menu shortcuts and
PyInstaller all have one obvious entry point. The app lives in the `soundboard`
package; `python -m soundboard` works too."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from soundboard.app import main  # noqa: E402

if __name__ == "__main__":
    main()
