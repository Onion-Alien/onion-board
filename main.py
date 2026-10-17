"""Launcher kept at the repo root so scripts/run.bat, the Desktop / Start-menu
shortcuts and PyInstaller all have one obvious entry point. The app lives in the `soundboard`
package; `python -m soundboard` works too."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__" and sys.argv[1:2] == ["--firewall-rule"]:
    # the admin copy a remote add-on asks for (soundboard.firewall): adds its rule, no app
    from soundboard.firewall import cli
    sys.exit(cli(sys.argv[2:]))

if __name__ == "__main__" and sys.argv[1:2] == ["--direct-mic"]:
    # the admin copy that installs / removes the mic effect (soundboard.directmic), no app
    from soundboard.directmic import cli as direct_mic_cli
    sys.exit(direct_mic_cli(sys.argv[2:]))

if __name__ == "__main__" and sys.argv[1:2] == ["--ytdl-worker"]:
    # the app's helper that runs yt-dlp's searches and downloads (soundboard.ytworker)
    from soundboard.ytworker import child_main
    sys.exit(child_main())

if __name__ == "__main__" and sys.argv[1:2] == ["--render-worker"]:
    # the app's helper that renders a slow sound's effects (soundboard.renderworker)
    from soundboard.renderworker import child_main as render_main
    sys.exit(render_main())

from soundboard import bootmark  # noqa: E402  (small: no Qt, no sound library)

# no breadcrumb for the one-off commands app.main() runs and exits (one would look like
# a start that failed: see soundboard/bootmark.py); the installer runs those itself
if __name__ == "__main__" and not (set(sys.argv[1:]) & set(bootmark.ONE_OFF)):
    if bootmark.installing():
        # the installer is replacing these files: it opens the app once it's done
        sys.exit(0)
    # a breadcrumb before the heavy import below, so a crash while it loads is counted
    from soundboard import __version__  # noqa: E402
    bootmark.start(__version__)

try:
    from soundboard.app import main  # noqa: E402
except Exception:
    # the installer started replacing the files while this loaded (bootmark.installing)
    if __name__ == "__main__" and bootmark.installing():
        sys.exit(0)
    raise

if __name__ == "__main__":
    main()
