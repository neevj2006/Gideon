from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import ProviderMode

APP_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Gideon"
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "gideon.db"
PID_PATH = APP_DIR / "gideon.pid"
STOP_PATH = APP_DIR / "stop.request"
LOG_PATH = APP_DIR / "gideon.log"


@dataclass(slots=True)
class Config:
    provider_mode: str = ProviderMode.AUTO
    local_model: str = "qwen2.5:1.5b-instruct-q4_K_M"
    cloud_provider: str = "openai"
    openai_model: str = "gpt-4.1-mini"
    openrouter_model: str = "openai/gpt-4.1-mini"
    ollama_url: str = "http://127.0.0.1:11434"
    llm_keep_alive: str = "30s"
    followup_seconds: int = 18
    location: str = "Boston, MA"
    timezone: str = "America/New_York"
    wake_word: str = "gideon"
    stt_provider: str = "auto"
    vosk_model_path: str = ""
    approved_apps: dict[str, str] = field(
        default_factory=lambda: {
            "spotify": "spotify.exe",
            "chrome": "chrome.exe",
            "vscode": "code.exe",
            "calculator": "calc.exe",
            "notepad": "notepad.exe",
        }
    )
    gmail_accounts: dict[str, str] = field(default_factory=dict)
    calendar_accounts: dict[str, str] = field(default_factory=dict)
    spotify_redirect_uri: str = "http://127.0.0.1:8765/callback"
    bridge_host: str = "0.0.0.0"
    bridge_port: int = 8766

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            result = cls()
            result.save(path)
            return result
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


class Secrets:
    """Keyring credentials with environment variable overrides."""

    service = "GideonV1"

    @staticmethod
    def env_name(name: str) -> str:
        return "GIDEON_" + name.upper().replace("-", "_").replace(":", "_")

    def get(self, name: str) -> str | None:
        if value := os.getenv(self.env_name(name)):
            return value
        try:
            import keyring

            return keyring.get_password(self.service, name)
        except Exception:
            return None

    def set(self, name: str, value: str) -> None:
        import keyring

        keyring.set_password(self.service, name, value)

    def delete(self, name: str) -> None:
        try:
            import keyring

            keyring.delete_password(self.service, name)
        except Exception:
            pass
