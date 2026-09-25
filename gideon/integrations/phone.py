from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets as secure_random
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests

from ..config import Config, Secrets
from ..db import Database, now_iso


def signature(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    return hmac.new(
        secret.encode(), timestamp.encode() + b"." + nonce.encode() + b"." + body, hashlib.sha256
    ).hexdigest()


class PhoneBridge:
    def __init__(self, cfg: Config, db: Database, secrets: Secrets):
        self.cfg, self.db, self.secrets = cfg, db, secrets

    def devices(self) -> list[dict[str, Any]]:
        return self.db.execute("SELECT id,name,base_url,paired_at,last_seen_at FROM phone_devices")

    def add_device(self, name: str, base_url: str, token: str) -> str:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Phone URL must use HTTP or HTTPS")
        device_id = uuid.uuid4().hex[:8]
        secret_name = f"phone:{device_id}"
        self.secrets.set(secret_name, token)
        self.db.execute(
            "INSERT INTO phone_devices(id,name,base_url,secret_name,paired_at) VALUES(?,?,?,?,?)",
            (device_id, name, base_url.rstrip("/"), secret_name, now_iso()),
        )
        return device_id

    def command(
        self, action: str, args: dict[str, Any] | None = None, device_id: str | None = None
    ) -> dict[str, Any]:
        rows = (
            self.db.execute("SELECT * FROM phone_devices WHERE id=?", (device_id,))
            if device_id
            else self.db.execute("SELECT * FROM phone_devices ORDER BY paired_at DESC LIMIT 1")
        )
        if not rows:
            raise RuntimeError("No phone is paired")
        device = rows[0]
        secret = self.secrets.get(device["secret_name"])
        if not secret:
            raise RuntimeError("Paired phone secret is missing")
        body = json.dumps({"action": action, "args": args or {}}, separators=(",", ":")).encode()
        timestamp, nonce = str(int(time.time())), secure_random.token_hex(12)
        response = requests.post(
            device["base_url"] + "/v1/action",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Gideon-Time": timestamp,
                "X-Gideon-Nonce": nonce,
                "X-Gideon-Signature": signature(secret, timestamp, nonce, body),
            },
            timeout=20,
        )
        response.raise_for_status()
        self.db.execute("UPDATE phone_devices SET last_seen_at=? WHERE id=?", (now_iso(), device["id"]))
        return dict(response.json())


class PairingServer:
    """Short-lived laptop endpoint used to exchange a generated pairing secret."""

    def __init__(self, cfg: Config, bridge: PhoneBridge):
        self.cfg, self.bridge = cfg, bridge

    def serve_once(self, code: str, timeout: int = 180) -> tuple[str, int]:
        bridge = self.bridge

        class Handler(BaseHTTPRequestHandler):
            paired = False
            attempts = 0

            def log_message(self, *_: Any) -> None:
                pass

            def do_POST(self) -> None:
                if self.path != "/v1/pair":
                    self.send_error(404)
                    return
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                data = json.loads(self.rfile.read(length))
                if not hmac.compare_digest(str(data.get("code", "")), code):
                    Handler.attempts += 1
                    self.send_error(403)
                    return
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding, rsa

                public_key = serialization.load_der_public_key(base64.b64decode(str(data["public_key"])))
                if not isinstance(public_key, rsa.RSAPublicKey):
                    self.send_error(400)
                    return
                token = secure_random.token_urlsafe(32)
                bridge.add_device(str(data.get("name", "Android phone")), str(data["base_url"]), token)
                encrypted = public_key.encrypt(
                    token.encode(),
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None,
                    ),
                )
                payload = json.dumps({"encrypted_token": base64.b64encode(encrypted).decode()}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                Handler.paired = True

        server = ThreadingHTTPServer((self.cfg.bridge_host, self.cfg.bridge_port), Handler)
        server.timeout = 1
        deadline = time.time() + timeout
        while time.time() < deadline and not Handler.paired and Handler.attempts < 10:
            server.handle_request()
        server.server_close()
        if not Handler.paired:
            raise TimeoutError("Pairing timed out or received too many invalid attempts")
        address = server.server_address
        return str(address[0]), int(address[1])
