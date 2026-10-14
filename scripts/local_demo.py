"""Install and open the local demo. Uses only the standard library to bootstrap."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import venv
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv-local"
LOCK = ROOT / "requirements.lock"


def run(command, **kwargs):
    subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def chromium_path():
    candidates = [shutil.which("chromium"), shutil.which("chromium-browser")]
    if os.name == "nt":
        for base in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            directory = os.environ.get(base)
            if directory:
                candidates.extend([
                    str(Path(directory) / "Microsoft/Edge/Application/msedge.exe"),
                    str(Path(directory) / "Google/Chrome/Application/chrome.exe"),
                ])
    return next((path for path in candidates if path and Path(path).is_file()), None)


def install():
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("Creating a private Python environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)
    fingerprint = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    marker = VENV / ".zandop-dependencies"
    if not marker.is_file() or marker.read_text().strip() != fingerprint:
        print("Installing pinned dependencies (internet needed on first launch)...", flush=True)
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(LOCK)])
        marker.write_text(fingerprint)
    browser = chromium_path()
    if not browser:
        print("Preparing Chromium for the delivery quality checks...", flush=True)
        run([str(python), "-m", "playwright", "install", "chromium"])
    return python, browser


def demo_environment(browser=None, data=None):
    # A demo launch must never inherit live provider settings or load .env.
    prefixes = (
        "ZANDOP_", "OUTREACH_", "INSTANTLY_", "SMARTLEAD_", "CALCOM_", "CALENDLY_",
        "CALENDAR_", "RESEND_", "STRIPE_", "GOOGLE_PLACES_", "MODEL_", "PERSONAL_EMAIL_",
        "AGENCY_", "BOOKING_", "CLIENT_EMAIL_", "AUTOMATION_WEBHOOK_", "PUBLIC_BASE_",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith(prefixes)}
    env.pop("CHROMIUM_EXECUTABLE", None)
    env.pop("MAX_BOUNCE_RATE", None)
    default_data = (Path(os.environ["LOCALAPPDATA"]) / "ZanDop" / "demo"
                    if os.name == "nt" and os.environ.get("LOCALAPPDATA")
                    else ROOT / ".local-demo" / "data")
    env.update({
        "ZANDOP_LIVE_MODE": "false", "ZANDOP_SEED_DEMO": "true",
        "ZANDOP_OPERATOR_TOKEN": "", "ZANDOP_DATA_DIR": str(Path(data or default_data).resolve()),
        "PYTHONUNBUFFERED": "1",
    })
    if browser:
        env["CHROMIUM_EXECUTABLE"] = browser
    return env


def serve(open_browser=True):
    # This path runs only in the installed environment; never honor inherited live settings.
    os.environ.update({"ZANDOP_LIVE_MODE": "false", "ZANDOP_SEED_DEMO": "true", "ZANDOP_OPERATOR_TOKEN": ""})
    sys.path.insert(0, str(ROOT))
    import uvicorn

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # An OS-assigned port avoids conflicts with other software. Bind only to this computer.
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        address = "http://127.0.0.1:" + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config("zandop.main:app", workers=1, log_level="warning"))
        stop_waiting = threading.Event()

        def open_when_ready():
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(120):
                if stop_waiting.is_set():
                    return
                try:
                    with opener.open(address + "/api/state", timeout=2) as response:
                        state = json.load(response)
                    if state["mode"] == "demo" and state["leads"]:
                        print("\nZanDop is ready: " + address, flush=True)
                        print("Demo only: no real emails, bookings, invoices, or payments.", flush=True)
                        print("Your data: " + os.environ["ZANDOP_DATA_DIR"], flush=True)
                        print("Keep this window open. Press Ctrl+C here to stop.\n", flush=True)
                        if open_browser and not webbrowser.open(address):
                            print("Open the address above in your browser.", flush=True)
                        return
                except (OSError, ValueError, KeyError, urllib.error.URLError):
                    pass
                stop_waiting.wait(0.5)
            print("Startup is taking longer than expected. Check the error above.", flush=True)
            server.should_exit = True

        ready = threading.Thread(target=open_when_ready, daemon=True)
        ready.start()
        try:
            server.run(sockets=[listener])
        finally:
            stop_waiting.set()
            ready.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description="Install and open the ZanDop local demo.")
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser.")
    parser.add_argument("--data-dir", type=Path, help="Optional separate demo data folder.")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Install Python 3.12, then launch ZanDop again.")
    if args.serve:
        serve(not args.no_browser)
        return
    python, browser = install()
    command = [str(python), str(Path(__file__).resolve()), "--serve"]
    if args.no_browser:
        command.append("--no-browser")
    run(command, env=demo_environment(browser, args.data_dir))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nZanDop stopped. Your saved demo data is kept.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("\nZanDop could not start: " + str(exc), file=sys.stderr)
        print("Keep this window open to read the error. Internet is required for the first installation.", file=sys.stderr)
        sys.exit(1)
