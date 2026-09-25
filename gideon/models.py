from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProviderMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    CLOUD_ONLY = "CLOUD_ONLY"
    AUTO = "AUTO"


@dataclass(slots=True)
class Intent:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    confirmation_required: bool = False


@dataclass(slots=True)
class Reply:
    text: str
    speak: bool = True
    data: Any = None
    needs_confirmation: bool = False
