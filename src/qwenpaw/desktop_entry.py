"""Desktop entry point for Tauri sidecar — auto-init + start backend."""
import os
import sys

os.environ.setdefault("COPAW_DESKTOP_APP", "1")
# Disable heavy optional services that may fail in PyInstaller bundle
os.environ.setdefault("QWENPAW_DISABLE_MEMORY_MANAGER", "1")
os.environ.setdefault(
    "QWENPAW_CORS_ORIGINS",
    "tauri://localhost,https://tauri.localhost,http://tauri.localhost,http://localhost:1420",
)


def main() -> None:
    from qwenpaw.cli.main import cli
    from qwenpaw.constant import WORKING_DIR

    # Auto-initialize if no config exists
    config_path = WORKING_DIR / "config.json"
    if not config_path.exists():
        sys.argv = ["qwenpaw", "init", "--defaults", "--accept-security"]
        try:
            cli(standalone_mode=False)
        except SystemExit:
            pass

    # Start the backend server
    sys.argv = ["qwenpaw", "app", "--host", "127.0.0.1", "--port", "8088"]
    cli()


if __name__ == "__main__":
    main()
