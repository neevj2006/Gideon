from __future__ import annotations

from pathlib import Path

import pytest

from gideon.assistant import Gideon
from gideon.config import Config
from gideon.db import Database


class FakeSecrets:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = values or {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def assistant(database: Database) -> Gideon:
    cfg = Config(provider_mode="LOCAL_ONLY")
    return Gideon(cfg, database, FakeSecrets())  # type: ignore[arg-type]
