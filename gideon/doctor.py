from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from .config import DB_PATH, Config, Secrets
from .db import Database


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str


def _run(name: str, fn: Callable[[], tuple[str, str]]) -> Check:
    try:
        status, detail = fn()
        return Check(name, status, detail)
    except Exception as exc:
        return Check(name, "FAILED", str(exc))


def run_doctor(cfg: Config, secrets: Secrets | None = None) -> list[Check]:
    secrets = secrets or Secrets()

    def audio() -> tuple[str, str]:
        import sounddevice as sd

        microphones = [device for device in sd.query_devices() if device["max_input_channels"] > 0]
        return (
            ("OK", f"{len(microphones)} microphone input(s) found")
            if microphones
            else ("FAILED", "no microphone input found")
        )

    def speaker() -> tuple[str, str]:
        import pyttsx3

        voices = pyttsx3.init().getProperty("voices")
        return ("OK", f"{len(voices)} TTS voice(s) found")

    def database() -> tuple[str, str]:
        Database()
        sqlite3.connect(DB_PATH).execute("PRAGMA quick_check").fetchone()
        return "OK", str(DB_PATH)

    def local_llm() -> tuple[str, str]:
        try:
            response = requests.get(cfg.ollama_url + "/api/tags", timeout=2)
        except requests.RequestException as exc:
            return "SETUP_REQUIRED", f"Ollama unavailable: {exc}"
        if not response.ok:
            return "SETUP_REQUIRED", f"Ollama HTTP {response.status_code}"
        models = [x["name"] for x in response.json().get("models", [])]
        present = any(x.split(":")[0] == cfg.local_model.split(":")[0] for x in models)
        return (
            "OK" if present else "SETUP_REQUIRED",
            cfg.local_model + (" installed" if present else " not pulled"),
        )

    def configured(secret: str, detail: str) -> tuple[str, str]:
        return (
            ("CONFIGURED", detail)
            if secrets.get(secret)
            else ("SETUP_REQUIRED", detail + " credential missing")
        )

    def module(name: str, description: str) -> tuple[str, str]:
        return (
            ("CONFIGURED", description)
            if importlib.util.find_spec(name)
            else ("SETUP_REQUIRED", f"optional package {name} not installed")
        )

    def google(service: str, accounts: dict[str, str]) -> tuple[str, str]:
        if not importlib.util.find_spec("googleapiclient"):
            return "SETUP_REQUIRED", "Google API packages are not installed"
        if not accounts:
            return "SETUP_REQUIRED", "no account aliases configured"
        missing = [alias for alias in accounts if not secrets.get(f"google:{service}:{alias}")]
        return (
            ("SETUP_REQUIRED", "OAuth required for: " + ", ".join(missing))
            if missing
            else ("CONFIGURED", "OAuth stored for: " + ", ".join(accounts))
        )

    def spotify() -> tuple[str, str]:
        return (
            configured("spotify_client_id", "Spotify API")
            if secrets.get("spotify_client_secret")
            else ("SETUP_REQUIRED", "Spotify credentials missing")
        )

    ollama_executable = shutil.which("ollama")
    if not ollama_executable:
        candidate = Path(os.getenv("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
        if candidate.exists():
            ollama_executable = str(candidate)
    checks = [
        _run("microphone / STT", audio),
        _run("speaker / TTS", speaker),
        Check(
            "wake word",
            "CONFIGURED" if cfg.vosk_model_path else "SETUP_REQUIRED",
            f"offline phrase detector configured for '{cfg.wake_word}'"
            if cfg.vosk_model_path
            else "install the Vosk model",
        ),
        _run("database", database),
        _run("local LLM", local_llm),
        _run("OpenAI", lambda: configured("openai_api_key", cfg.openai_model)),
        _run("OpenRouter", lambda: configured("openrouter_api_key", cfg.openrouter_model)),
        _run("Gmail", lambda: google("gmail", cfg.gmail_accounts)),
        _run("Calendar", lambda: google("calendar", cfg.calendar_accounts)),
        _run("Spotify", spotify),
        Check(
            "Android bridge",
            "CONFIGURED" if Database().execute("SELECT id FROM phone_devices") else "SETUP_REQUIRED",
            "paired" if Database().execute("SELECT id FROM phone_devices") else "no paired phone",
        ),
        Check(
            "Ollama executable",
            "OK" if ollama_executable else "SETUP_REQUIRED",
            ollama_executable or "not installed",
        ),
    ]
    return checks
