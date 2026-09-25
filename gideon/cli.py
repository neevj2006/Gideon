from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import psutil

from .assistant import Gideon
from .config import APP_DIR, CONFIG_PATH, LOG_PATH, PID_PATH, STOP_PATH, Config, Secrets
from .db import Database
from .doctor import run_doctor
from .integrations.google import GoogleAuth
from .integrations.phone import PairingServer, PhoneBridge


def _pid() -> int | None:
    try:
        pid = int(PID_PATH.read_text().strip())
        return pid if psutil.pid_exists(pid) else None
    except (OSError, ValueError):
        return None


def start() -> int:
    if pid := _pid():
        print(f"Gideon is already running (PID {pid}).")
        return 0
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STOP_PATH.unlink(missing_ok=True)
    creationflags = 0x08000000 | 0x00000008 if os.name == "nt" else 0
    subprocess.Popen(
        [sys.executable, "-m", "gideon.cli", "run"],
        cwd=str(APP_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    for _ in range(30):
        if pid := _pid():
            print(f"Gideon started in the background (PID {pid}).")
            return 0
        time.sleep(0.1)
    print(f"Gideon failed to start. Check {LOG_PATH}")
    return 1


def stop() -> int:
    pid = _pid()
    if not pid:
        PID_PATH.unlink(missing_ok=True)
        print("Gideon is not running.")
        return 0
    STOP_PATH.touch()
    try:
        psutil.Process(pid).wait(timeout=8)
    except psutil.TimeoutExpired:
        print("Gideon did not stop cleanly; terminating it.")
        psutil.Process(pid).terminate()
    print("Gideon stopped.")
    return 0


def status() -> int:
    if pid := _pid():
        print(f"RUNNING (PID {pid})")
        return 0
    print("STOPPED")
    return 1


def chat(once: str | None = None) -> int:
    assistant = Gideon()
    if once:
        print(assistant.handle(once).text)
        return 0
    print("Gideon text mode. Type help or exit.")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        reply = assistant.handle(text)
        print("gideon>", reply.text)
        if reply.data and reply.data.get("exit"):
            break
    return 0


def setup() -> int:
    cfg, secrets = Config.load(), Secrets()
    print(f"Configuration: {CONFIG_PATH}\nPress Enter to preserve existing values.")
    mode = input(f"Provider mode [{cfg.provider_mode}]: ").strip().upper()
    if mode in {"LOCAL_ONLY", "CLOUD_ONLY", "AUTO"}:
        cfg.provider_mode = mode
    local = input(f"Ollama model [{cfg.local_model}]: ").strip()
    if local:
        cfg.local_model = local
    location = input(f"Briefing weather location [{cfg.location}]: ").strip()
    if location:
        cfg.location = location
    cloud = input(f"Cloud provider openai/openrouter [{cfg.cloud_provider}]: ").strip().lower()
    if cloud in {"openai", "openrouter"}:
        cfg.cloud_provider = cloud
    cfg.save()
    for name, label in (
        ("openai_api_key", "OpenAI API key"),
        ("openrouter_api_key", "OpenRouter API key"),
        ("spotify_client_id", "Spotify client ID"),
        ("spotify_client_secret", "Spotify client secret"),
    ):
        if input(f"Configure {label}? [y/N] ").strip().lower() == "y":
            secrets.set(name, getpass.getpass(label + ": "))
    print("Setup saved securely.")
    return 0


def google_setup(service: str, alias: str, client_json: str) -> int:
    cfg = Config.load()
    alias = alias.lower()
    target = cfg.gmail_accounts if service == "gmail" else cfg.calendar_accounts
    target[alias] = client_json
    cfg.save()
    GoogleAuth(cfg).credentials(alias, service, interactive=True)
    print(f"Google {service} alias '{alias}' connected.")
    return 0


def pair_phone() -> int:
    import secrets

    cfg, db, secret_store = Config.load(), Database(), Secrets()
    bridge = PhoneBridge(cfg, db, secret_store)
    code = f"{secrets.randbelow(1000000):06d}"
    print(
        f"Enter this pairing code in the Android app: {code}\nWaiting on port {cfg.bridge_port} for up to 3 minutes..."
    )
    PairingServer(cfg, bridge).serve_once(code)
    print("Phone paired.")
    return 0


def install_vosk_model() -> int:
    """Install the small English offline STT model into Gideon's private app directory."""
    import requests

    url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    archive = APP_DIR / "vosk-model.zip"
    target = APP_DIR / "models"
    APP_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading the 40 MB offline English speech model...")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with archive.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                output.write(chunk)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        root = target.resolve()
        for member in bundle.infolist():
            destination = (target / member.filename).resolve()
            if root not in destination.parents and destination != root:
                raise RuntimeError("Unsafe path in model archive")
        bundle.extractall(target)
    archive.unlink(missing_ok=True)
    model_path = target / "vosk-model-small-en-us-0.15"
    cfg = Config.load()
    cfg.vosk_model_path = str(model_path)
    cfg.save()
    print(f"Offline speech model installed at {model_path}")
    return 0


def set_autostart(enabled: bool) -> int:
    """Manage a per-user logon task without requiring administrator access."""
    task_name = "GideonV1"
    if not enabled:
        result = subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True
        )
        print("Autostart removed." if result.returncode == 0 else result.stderr.strip())
        return result.returncode
    executable = Path(sys.executable).resolve()
    command = f'"{executable}" -m gideon.cli start'
    result = subprocess.run(
        ["schtasks.exe", "/Create", "/SC", "ONLOGON", "/TN", task_name, "/TR", command, "/F"],
        capture_output=True,
        text=True,
    )
    print("Autostart installed." if result.returncode == 0 else result.stderr.strip())
    return result.returncode


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gideon", description="Gideon V1 local-first assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("status")
    sub.add_parser("doctor")
    sub.add_parser("setup")
    sub.add_parser("run", help=argparse.SUPPRESS)
    sub.add_parser("pair-phone")
    sub.add_parser("install-vosk-model")
    sub.add_parser("install-autostart")
    sub.add_parser("uninstall-autostart")
    chat_parser = sub.add_parser("chat")
    chat_parser.add_argument("--once")
    google_parser = sub.add_parser("google-setup")
    google_parser.add_argument("service", choices=["gmail", "calendar"])
    google_parser.add_argument("alias")
    google_parser.add_argument("client_json")
    config_parser = sub.add_parser("config")
    config_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "start":
        code = start()
    elif args.command == "stop":
        code = stop()
    elif args.command == "status":
        code = status()
    elif args.command == "chat":
        code = chat(args.once)
    elif args.command == "setup":
        code = setup()
    elif args.command == "google-setup":
        code = google_setup(args.service, args.alias, args.client_json)
    elif args.command == "pair-phone":
        code = pair_phone()
    elif args.command == "install-vosk-model":
        code = install_vosk_model()
    elif args.command == "install-autostart":
        code = set_autostart(True)
    elif args.command == "uninstall-autostart":
        code = set_autostart(False)
    elif args.command == "config":
        print(json.dumps(__import__("dataclasses").asdict(Config.load()), indent=2))
        code = 0
    elif args.command == "doctor":
        checks = run_doctor(Config.load())
        width = max(len(c.name) for c in checks)
        for check in checks:
            print(f"{check.name:<{width}}  {check.status:<23} {check.detail}")
        code = 1 if any(c.status == "FAILED" for c in checks) else 0
    else:
        from .daemon import run_daemon

        run_daemon()
        code = 0
    raise SystemExit(code)


if __name__ == "__main__":
    main()
