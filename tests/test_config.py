import pytest
from fastapi.testclient import TestClient

from sentineldesk import llm, runtime_config
from sentineldesk.api import create_app
from sentineldesk.config import settings

from .conftest import T0, outage


@pytest.fixture()
def client(make_platform):
    platform = make_platform()
    test_client = TestClient(create_app(platform))
    test_client.platform = platform
    return test_client


def field(body: dict, key: str) -> dict:
    return next(f for f in body["fields"] if f["key"] == key)


def test_every_editable_field_exists_in_settings_and_validates_its_own_default():
    for f in runtime_config.FIELDS:
        default = getattr(settings, f.key)
        if f.kind == "secret" or (f.kind == "text" and default == ""):
            continue
        assert runtime_config.validate(f.key, default) == default, f.key
    assert {f.group for f in runtime_config.FIELDS} == set(runtime_config.GROUPS)


def test_config_page_data_never_contains_the_api_key(client):
    client.put("/api/config", json={"llm_api_key": "sk-very-secret", "llm_model": "some-model"})
    body = client.get("/api/config")
    assert "sk-very-secret" not in body.text
    key = field(body.json(), "llm_api_key")
    assert key["is_set"] is True and "value" not in key and "default" not in key


def test_saving_settings_changes_how_the_running_platform_behaves(client):
    platform = client.platform
    # Four exceptions: below the default minimum of five, and not a new error type yet.
    platform.ingest_exceptions(outage("transfers", 2), T0)
    assert client.get("/api/overview").json()["counts"]["open_incidents"] == 0

    body = client.put("/api/config", json={"new_error_min_events": 2, "spike_min_events": 2}).json()
    assert field(body, "new_error_min_events") == {**field(body, "new_error_min_events"),
                                                  "value": 2, "default": 3, "changed": True}
    assert platform.cfg.new_error_min_events == 2

    assert len(platform.ingest_exceptions(outage("cards", 2), T0)) == 1


def test_one_invalid_value_saves_nothing(client):
    r = client.put("/api/config", json={"min_confidence": 0.5, "spike_ratio": 500})
    assert r.status_code == 422
    assert r.json()["detail"] == {"field": "spike_ratio", "message": "Must be between 1.5 and 20."}
    assert client.platform.cfg.min_confidence == settings.min_confidence

    for bad in ({"llm_provider": "other"}, {"bank_url": "ftp://x"}, {"spike_min_events": 2.5},
                {"spike_min_events": "5"}, {"spike_min_events": True}, {"not_a_setting": 1}):
        assert client.put("/api/config", json=bad).status_code == 422, bad


def test_setting_a_model_turns_the_agents_on_and_reset_turns_them_off(client):
    assert client.get("/api/config").json()["model_active"] is None
    body = client.put("/api/config", json={"llm_model": "some-model", "llm_base_url": "https://example.test/v1"}).json()
    assert body["model_active"] == "some-model"
    assert isinstance(client.platform.model, llm.OpenAICompatible)

    body = client.post("/api/config/reset").json()
    assert body["model_active"] is None and client.platform.model is None
    assert not any(f["changed"] for f in body["fields"])


def test_unusable_model_configuration_is_reported_not_raised(client, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)  # the SDK is not installed
    body = client.put("/api/config", json={"llm_provider": "anthropic", "llm_model": "some-claude-model"}).json()
    assert body["model_active"] is None and "pip install anthropic" in body["model_problem"]


def test_model_connection_test(client):
    assert client.post("/api/config/test-model").json()["ok"] is False  # nothing configured

    class Answering:
        name = "answering-model"

        def start(self, system, user):
            return []

        def complete(self, conversation, tools):
            assert tools == []
            return llm.Turn(text="ready")

    client.platform.model = Answering()
    result = client.post("/api/config/test-model").json()
    assert result["ok"] is True and result["reply"] == "ready" and "answering-model" in result["message"]

    class Failing(Answering):
        def complete(self, conversation, tools):
            raise llm.LLMError("HTTP 401: invalid key")

    client.platform.model = Failing()
    assert client.post("/api/config/test-model").json() == {"ok": False, "message": "HTTP 401: invalid key"}
