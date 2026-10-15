"""Open the real local workspace by default; use --demo for fictional clients."""

import argparse
import hashlib
import json
import secrets
from contextlib import contextmanager
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
        "AGENCY_", "BOOKING_", "CLIENT_EMAIL_", "AUTOMATION_WEBHOOK_", "PUBLIC_BASE_", "GMAIL_",
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


def workspace_environment(browser=None, data=None):
    default = (Path(os.environ["LOCALAPPDATA"]) / "ZanDop" / "workspace"
               if os.name == "nt" and os.environ.get("LOCALAPPDATA") else ROOT / ".local-workspace" / "data")
    env = demo_environment(browser, data or default)
    env.update({"ZANDOP_LOCAL_WORKSPACE": "true", "ZANDOP_SEED_DEMO": "false",
                "ZANDOP_OPERATOR_TOKEN": secrets.token_urlsafe(40), "ZANDOP_LOCAL_BOOTSTRAP": secrets.token_urlsafe(40)})
    for key in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "GMAIL_LABEL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


@contextmanager
def instance_lock(directory):
    path = directory / ".instance.lock"
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def serve(open_browser=True, workspace=True):
    if workspace and (os.environ.get("ZANDOP_LOCAL_WORKSPACE") != "true" or not os.environ.get("ZANDOP_OPERATOR_TOKEN") or not os.environ.get("ZANDOP_LOCAL_BOOTSTRAP")):
        raise RuntimeError("Start the real workspace with Start ZanDop.bat or python scripts/local_demo.py; --serve is an internal option.")
    if not workspace:
        os.environ.update({"ZANDOP_LIVE_MODE": "false", "ZANDOP_SEED_DEMO": "true", "ZANDOP_OPERATOR_TOKEN": ""})
        os.environ.pop("ZANDOP_LOCAL_WORKSPACE", None)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    directory = Path(os.environ["ZANDOP_DATA_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    state_file = directory / ".instance.json"
    with instance_lock(directory) as acquired:
        if not acquired:
            print("ZanDop is already running for this workspace. Reopening the dashboard.", flush=True)
            if state_file.is_file() and open_browser:
                webbrowser.open(json.loads(state_file.read_text())["address"])
            return
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            address = "http://127.0.0.1:" + str(listener.getsockname()[1])
            state_file.write_text(json.dumps({"address": address}))
            server = uvicorn.Server(uvicorn.Config("zandop.main:app", workers=1, log_level="warning"))
            stop_waiting = threading.Event()

            def open_when_ready():
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(address + "/api/state")
                if workspace:
                    request.add_header("Authorization", "Bearer " + os.environ["ZANDOP_OPERATOR_TOKEN"])
                for _ in range(120):
                    if stop_waiting.is_set():
                        return
                    try:
                        with opener.open(request, timeout=2) as response:
                            state = json.load(response)
                        if (workspace and state["mode"] in {"paused", "live"}) or (state["mode"] == "demo" and state["leads"]):
                            print("\nZanDop is ready: " + address, flush=True)
                            print("Connect Gmail in Local setup. Financial sends always need your approval." if workspace else "Demo only: no real emails, bookings, invoices, or payments.", flush=True)
                            print("Your data: " + str(directory), flush=True)
                            print("Keep this window open. Press Ctrl+C here to stop.\n", flush=True)
                            destination = address
                            if workspace:
                                destination += "/local/session?code=" + os.environ["ZANDOP_LOCAL_BOOTSTRAP"]
                                opener_file = directory / "Open ZanDop.html"
                                opener_file.write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=' + destination + '"><title>Open ZanDop</title><a href="' + destination + '">Open your local ZanDop workspace</a>', encoding="utf-8")
                                print("If the browser does not open, double-click: " + str(opener_file), flush=True)
                            if open_browser:
                                webbrowser.open(destination)
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
                state_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Install and open the real ZanDop workspace. Gmail starts paused until configured.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--workspace", dest="workspace", action="store_true", help="Open the real local workspace (the default).")
    modes.add_argument("--demo", dest="workspace", action="store_false", help="Open the separate fictional demo; no real messages send.")
    parser.set_defaults(workspace=True)
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser.")
    parser.add_argument("--data-dir", type=Path, help="Optional separate data folder for the selected workspace.")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Install Python 3.12, then launch ZanDop again.")
    if args.serve:
        serve(not args.no_browser, args.workspace)
        return
    python, browser = install()
    command = [str(python), str(Path(__file__).resolve()), "--serve"]
    if args.no_browser:
        command.append("--no-browser")
    command.append("--workspace" if args.workspace else "--demo")
    environment = workspace_environment(browser, args.data_dir) if args.workspace else demo_environment(browser, args.data_dir)
    run(command, env=environment)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nZanDop stopped. Your saved workspace data is kept.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("\nZanDop could not start: " + str(exc), file=sys.stderr)
        print("Keep this window open to read the error. Internet is required for the first installation.", file=sys.stderr)
        sys.exit(1)
