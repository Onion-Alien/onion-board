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

# the one-off commands app.main() handles and exits (a breadcrumb would look like a
# start that failed: see soundboard/bootmark.py). Keep in step with app.main()'s branches.
_ONE_OFF = ("--selftest", "--get-tor", "--set-offline", "--keep-netlog", "--usage-count",
            "--uninstall-count", "--selftest-addon")

if __name__ == "__main__" and not (set(sys.argv[1:]) & set(_ONE_OFF)):
    # a breadcrumb before the heavy import below, so a crash while it loads is counted
    from soundboard import __version__, bootmark  # noqa: E402
    bootmark.start(__version__)

from soundboard.app import main  # noqa: E402

if __name__ == "__main__":
    main()
