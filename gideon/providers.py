from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import requests

from .config import Config, Secrets
from .models import ProviderMode


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> str: ...


class OllamaProvider(LLMProvider):
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def available(self) -> bool:
        try:
            return requests.get(f"{self.cfg.ollama_url}/api/tags", timeout=1).ok
        except requests.RequestException:
            return False

    def complete(self, prompt: str, system: str = "") -> str:
        try:
            response = requests.post(
                f"{self.cfg.ollama_url}/api/chat",
                json={
                    "model": self.cfg.local_model,
                    "stream": False,
                    "keep_alive": self.cfg.llm_keep_alive,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    "options": {"temperature": 0.2, "num_predict": 400},
                },
                timeout=90,
            )
            response.raise_for_status()
            return str(response.json()["message"]["content"])
        except (requests.RequestException, KeyError) as exc:
            raise ProviderError(f"Local model failed: {exc}") from exc


class OpenAIProvider(LLMProvider):
    def __init__(self, cfg: Config, secrets: Secrets):
        self.cfg, self.secrets = cfg, secrets

    def available(self) -> bool:
        return bool(self.secrets.get("openai_api_key"))

    def complete(self, prompt: str, system: str = "") -> str:
        key = self.secrets.get("openai_api_key")
        if not key:
            raise ProviderError("OpenAI API key is not configured")
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": self.cfg.openai_model,
                "instructions": system,
                "input": prompt,
                "max_output_tokens": 500,
                "store": False,
            },
            timeout=90,
        )
        if not response.ok:
            raise ProviderError(f"OpenAI returned HTTP {response.status_code}")
        data = response.json()
        if data.get("output_text"):
            return str(data["output_text"])
        return "".join(
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )


class OpenRouterProvider(LLMProvider):
    def __init__(self, cfg: Config, secrets: Secrets):
        self.cfg, self.secrets = cfg, secrets

    def available(self) -> bool:
        return bool(self.secrets.get("openrouter_api_key"))

    def complete(self, prompt: str, system: str = "") -> str:
        key = self.secrets.get("openrouter_api_key")
        if not key:
            raise ProviderError("OpenRouter API key is not configured")
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "X-Title": "Gideon V1",
            },
            json={
                "model": self.cfg.openrouter_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 500,
            },
            timeout=90,
        )
        if not response.ok:
            raise ProviderError(f"OpenRouter returned HTTP {response.status_code}")
        return str(response.json()["choices"][0]["message"]["content"])


class ProviderRouter:
    """Select providers according to the configured mode, with fallback in AUTO."""

    def __init__(self, cfg: Config, secrets: Secrets | None = None):
        self.cfg, self.secrets = cfg, secrets or Secrets()
        self.local = OllamaProvider(cfg)
        self.cloud: LLMProvider = (
            OpenRouterProvider(cfg, self.secrets)
            if cfg.cloud_provider == "openrouter"
            else OpenAIProvider(cfg, self.secrets)
        )

    def complete(self, prompt: str, system: str = "", hard: bool = False) -> str:
        mode = ProviderMode(self.cfg.provider_mode)
        errors: list[str] = []
        candidates: list[LLMProvider]
        if mode == ProviderMode.LOCAL_ONLY:
            candidates = [self.local]
        elif mode == ProviderMode.CLOUD_ONLY:
            candidates = [self.cloud]
        else:
            candidates = [self.local, self.cloud]
        for provider in candidates:
            if not provider.available():
                continue
            try:
                return provider.complete(prompt, system)
            except ProviderError as exc:
                errors.append(str(exc))
        detail = "; ".join(errors) or "no configured provider is available"
        raise ProviderError(detail)

    def classify(self, text: str, tool_names: list[str]) -> dict[str, Any] | None:
        system = (
            "Route a personal-assistant command. Return ONLY compact JSON with keys name and args. "
            f"Allowed names: {', '.join(tool_names)}, general_question. Never invent an action."
        )
        try:
            raw = self.complete(text, system)
            start, end = raw.find("{"), raw.rfind("}")
            return json.loads(raw[start : end + 1]) if start >= 0 and end > start else None
        except (ProviderError, json.JSONDecodeError):
            return None
