from __future__ import annotations

import base64
import json
import secrets as random_secrets
import subprocess
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from ..config import Config, Secrets


class SpotifyError(RuntimeError):
    pass


class SpotifyService:
    """Spotify playback and OAuth client."""

    SCOPE = "user-read-playback-state user-modify-playback-state user-library-read"

    def __init__(self, cfg: Config, secrets: Secrets):
        self.cfg, self.secrets = cfg, secrets

    def configured(self) -> bool:
        return bool(self.secrets.get("spotify_client_id") and self.secrets.get("spotify_client_secret"))

    def _basic(self) -> str:
        client_id = self.secrets.get("spotify_client_id")
        secret = self.secrets.get("spotify_client_secret")
        if not client_id or not secret:
            raise SpotifyError("Spotify credentials need setup")
        return base64.b64encode(f"{client_id}:{secret}".encode()).decode()

    def _save_token(self, token: dict[str, Any]) -> str:
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
        self.secrets.set("spotify_token", json.dumps(token))
        return str(token["access_token"])

    def _token(self) -> str:
        saved = self.secrets.get("spotify_token")
        token = json.loads(saved) if saved else {}
        if token.get("access_token") and int(token.get("expires_at", 0)) > time.time() + 30:
            return str(token["access_token"])
        if token.get("refresh_token"):
            response = requests.post(
                "https://accounts.spotify.com/api/token",
                headers={"Authorization": "Basic " + self._basic()},
                data={"grant_type": "refresh_token", "refresh_token": token["refresh_token"]},
                timeout=20,
            )
            if response.ok:
                refreshed = response.json()
                refreshed.setdefault("refresh_token", token["refresh_token"])
                return self._save_token(refreshed)
        return self._authorize()

    def _authorize(self) -> str:
        client_id = self.secrets.get("spotify_client_id")
        if not client_id:
            raise SpotifyError("Spotify credentials need setup")
        redirect = urlparse(self.cfg.spotify_redirect_uri)
        state = random_secrets.token_urlsafe(24)
        result: dict[str, str] = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def do_GET(self) -> None:
                query = parse_qs(urlparse(self.path).query)
                if query.get("state", [""])[0] != state:
                    self.send_error(403)
                    return
                if code := query.get("code", [""])[0]:
                    result["code"] = code
                body = b"Spotify connected. You can close this window."
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer((redirect.hostname or "127.0.0.1", redirect.port or 8765), Callback)
        server.timeout = 180
        authorize_url = "https://accounts.spotify.com/authorize?" + urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "scope": self.SCOPE,
                "redirect_uri": self.cfg.spotify_redirect_uri,
                "state": state,
            }
        )
        webbrowser.open(authorize_url)
        server.handle_request()
        server.server_close()
        if "code" not in result:
            raise SpotifyError("Spotify authorization timed out or was denied")
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": "Basic " + self._basic()},
            data={
                "grant_type": "authorization_code",
                "code": result["code"],
                "redirect_uri": self.cfg.spotify_redirect_uri,
            },
            timeout=20,
        )
        if not response.ok:
            raise SpotifyError(f"Spotify authorization returned HTTP {response.status_code}")
        return self._save_token(response.json())

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = requests.request(
            method,
            "https://api.spotify.com/v1" + path,
            headers={"Authorization": "Bearer " + self._token()},
            params=params,
            json=payload,
            timeout=20,
        )
        if response.status_code == 204:
            return {}
        if not response.ok:
            raise SpotifyError(f"Spotify returned HTTP {response.status_code}: {response.text[:160]}")
        return dict(response.json())

    @staticmethod
    def launch() -> None:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "spotify:"], creationflags=0x08000000)
        except OSError:
            pass

    def play(self, query: str) -> str:
        self.launch()
        if query.lower() in {"liked songs", "my liked songs"}:
            items = self._request("GET", "/me/tracks", params={"limit": 50}).get("items", [])
            uris = [item["track"]["uri"] for item in items]
            if not uris:
                return "Your liked songs list is empty."
            self._request("PUT", "/me/player/play", payload={"uris": uris})
            return "Playing your liked songs."
        kind = (
            "playlist" if "playlist" in query.lower() else "artist" if "artist" in query.lower() else "track"
        )
        data = self._request("GET", "/search", params={"q": query, "type": kind, "limit": 1})
        found = data.get(kind + "s", {}).get("items", [])
        if not found:
            return f"I couldn't find {query}."
        item = found[0]
        payload = {"uris": [item["uri"]]} if kind == "track" else {"context_uri": item["uri"]}
        self._request("PUT", "/me/player/play", payload=payload)
        return f"Playing {item['name']}."

    def control(self, action: str) -> str:
        self.launch()
        if "pause" in action:
            self._request("PUT", "/me/player/pause")
            return "Paused."
        if "resume" in action:
            self._request("PUT", "/me/player/play")
            return "Resumed."
        if "next" in action:
            self._request("POST", "/me/player/next")
            return "Skipped."
        if "previous" in action:
            self._request("POST", "/me/player/previous")
            return "Going back."
        if "shuffle" in action:
            self._request(
                "PUT", "/me/player/shuffle", params={"state": "on" in action or "off" not in action}
            )
            return "Shuffle updated."
        if "repeat" in action:
            state = "off" if "off" in action else "track" if "track" in action else "context"
            self._request("PUT", "/me/player/repeat", params={"state": state})
            return "Repeat updated."
        if "volume" in action:
            value = max(0, min(100, next((int(x) for x in action.split() if x.isdigit()), 50)))
            self._request("PUT", "/me/player/volume", params={"volume_percent": value})
            return f"Spotify volume is {value} percent."
        current = self._request("GET", "/me/player")
        if current.get("item"):
            item = current["item"]
            return f"{item['name']} by {', '.join(artist['name'] for artist in item['artists'])}."
        return "Nothing is playing."
