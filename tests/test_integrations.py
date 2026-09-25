import base64
import socket
import threading
import time
from unittest.mock import Mock, patch

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from gideon.config import Config
from gideon.db import Database
from gideon.integrations.phone import PairingServer, PhoneBridge, signature
from gideon.integrations.web import WebService
from tests.conftest import FakeSecrets


def test_hmac_signature_is_stable() -> None:
    assert signature("key", "1", "nonce", b"{}") == signature("key", "1", "nonce", b"{}")
    assert signature("key", "1", "nonce", b"{}") != signature("key", "1", "nonce", b"x")


def test_phone_command_is_authenticated(database: Database) -> None:
    secrets = FakeSecrets()
    bridge = PhoneBridge(Config(), database, secrets)  # type: ignore[arg-type]
    bridge.add_device("phone", "http://100.64.0.2:8767", "pair-secret")
    result = Mock()
    result.json.return_value = {"message": "ok"}
    result.raise_for_status.return_value = None
    with patch("requests.post", return_value=result) as post:
        assert bridge.command("ring")["message"] == "ok"
        headers = post.call_args.kwargs["headers"]
        assert headers["X-Gideon-Signature"]
        assert "pair-secret" not in str(post.call_args)


def test_pairing_secret_is_encrypted_to_android_key(database: Database) -> None:
    secrets = FakeSecrets()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    cfg = Config(bridge_host="127.0.0.1", bridge_port=port)
    bridge = PhoneBridge(cfg, database, secrets)  # type: ignore[arg-type]
    server = PairingServer(cfg, bridge)
    worker = threading.Thread(target=server.serve_once, args=("123456", 5))
    worker.start()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    for _ in range(20):
        try:
            response = requests.post(
                f"http://127.0.0.1:{port}/v1/pair",
                json={
                    "code": "123456",
                    "name": "test phone",
                    "base_url": "http://127.0.0.1:8767",
                    "public_key": base64.b64encode(public).decode(),
                },
                timeout=1,
            )
            break
        except requests.ConnectionError:
            time.sleep(0.05)
    worker.join(5)
    encrypted = base64.b64decode(response.json()["encrypted_token"])
    token = key.decrypt(
        encrypted,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    ).decode()
    stored_name = database.execute("SELECT secret_name FROM phone_devices")[0]["secret_name"]
    assert token == secrets.get(stored_name)


def test_weather_parsing() -> None:
    result = Mock()
    result.json.return_value = {"current_condition": [{"temp_F": "72", "weatherDesc": [{"value": "Clear"}]}]}
    with patch("requests.get", return_value=result):
        assert WebService().weather("Boston") == "In Boston, it is 72 degrees Fahrenheit and clear."
