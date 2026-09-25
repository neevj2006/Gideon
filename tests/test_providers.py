from unittest.mock import Mock, patch

import pytest

from gideon.config import Config
from gideon.providers import OllamaProvider, OpenAIProvider, ProviderError, ProviderRouter
from tests.conftest import FakeSecrets


def response(data: dict, ok: bool = True) -> Mock:
    item = Mock(ok=ok, status_code=200 if ok else 500)
    item.json.return_value = data
    item.raise_for_status.return_value = None
    return item


def test_ollama_request_is_lazy_and_releases_model() -> None:
    cfg = Config(llm_keep_alive="30s")
    provider = OllamaProvider(cfg)
    with patch("requests.post", return_value=response({"message": {"content": "local"}})) as post:
        assert provider.complete("hello") == "local"
        assert post.call_args.kwargs["json"]["keep_alive"] == "30s"


def test_openai_uses_responses_api_and_does_not_store() -> None:
    provider = OpenAIProvider(Config(), FakeSecrets({"openai_api_key": "secret"}))  # type: ignore[arg-type]
    with patch("requests.post", return_value=response({"output_text": "cloud"})) as post:
        assert provider.complete("hello") == "cloud"
        assert post.call_args.args[0].endswith("/responses")
        assert post.call_args.kwargs["json"]["store"] is False


def test_auto_falls_back_to_cloud() -> None:
    router = ProviderRouter(Config(provider_mode="AUTO"), FakeSecrets())  # type: ignore[arg-type]
    router.local.available = Mock(return_value=False)  # type: ignore[method-assign]
    router.cloud.available = Mock(return_value=True)  # type: ignore[method-assign]
    router.cloud.complete = Mock(return_value="fallback")  # type: ignore[method-assign]
    assert router.complete("hello") == "fallback"


def test_no_provider_has_clear_error() -> None:
    router = ProviderRouter(Config(provider_mode="LOCAL_ONLY"), FakeSecrets())  # type: ignore[arg-type]
    router.local.available = Mock(return_value=False)  # type: ignore[method-assign]
    with pytest.raises(ProviderError, match="no configured"):
        router.complete("hello")
