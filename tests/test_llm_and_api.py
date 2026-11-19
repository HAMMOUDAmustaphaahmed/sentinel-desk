import json
import sys
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from sentineldesk import llm
from sentineldesk.agent import Tool, run_agent
from sentineldesk.api import create_app
from sentineldesk.config import Settings
from sentineldesk.llm import ToolCall, ToolSpec

WEATHER = ToolSpec("get_weather", "Weather for a city.",
                   {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})


# ------------------------------------------------------- OpenAI-compatible adapter

def test_openai_compatible_adapter_speaks_the_chat_completions_format():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None, "reasoning": "provider-specific field",
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city": "Tunis"}'}}],
        }}]})

    model = llm.OpenAICompatible("https://example.test/v1/", "some-model", "secret",
                                 transport=httpx.MockTransport(handler))
    conversation = model.start("system prompt", "user prompt")
    turn = model.complete(conversation, [WEATHER])

    assert turn.tool_calls == [ToolCall("call_1", "get_weather", {"city": "Tunis"})]
    sent = requests[0]
    assert sent["model"] == "some-model"
    assert sent["messages"][0] == {"role": "system", "content": "system prompt"}
    assert sent["tools"][0] == {"type": "function", "function": {
        "name": "get_weather", "description": "Weather for a city.", "parameters": WEATHER.parameters}}

    model.add_results(conversation, [(turn.tool_calls[0], "22 C", False)])
    # Provider-specific fields are not echoed back; the tool result references the call id.
    assert "reasoning" not in conversation[2]
    assert conversation[3] == {"role": "tool", "tool_call_id": "call_1", "content": "22 C"}


def test_openai_compatible_adapter_turns_http_failures_into_llm_errors():
    model = llm.OpenAICompatible("https://example.test/v1", "m", transport=httpx.MockTransport(
        lambda request: httpx.Response(429, text="slow down")))
    with pytest.raises(llm.LLMError, match="429"):
        model.complete(model.start("s", "u"), [])


def test_malformed_tool_arguments_do_not_crash_the_adapter():
    model = llm.OpenAICompatible("https://example.test/v1", "m", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "get_weather", "arguments": "{not json"}}]}}]})))
    turn = model.complete(model.start("s", "u"), [WEATHER])
    assert turn.tool_calls[0].args == {}


# ---------------------------------------------------------------- Claude adapter

def test_anthropic_adapter_builds_messages_api_requests(monkeypatch):
    calls = []

    class Block(types.SimpleNamespace):
        pass

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(stop_reason="tool_use", content=[
                Block(type="thinking", thinking=""),
                Block(type="text", text="Checking."),
                Block(type="tool_use", id="toolu_1", name="get_weather", input={"city": "Tunis"}),
            ])

    fake_sdk = types.ModuleType("anthropic")
    fake_sdk.Anthropic = lambda **kwargs: types.SimpleNamespace(messages=Messages())
    for name in ("RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(fake_sdk, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake_sdk)

    model = llm.Anthropic("some-claude-model", "key")
    conversation = model.start("system prompt", "user prompt")
    turn = model.complete(conversation, [WEATHER])

    assert turn.text == "Checking." and turn.tool_calls == [ToolCall("toolu_1", "get_weather", {"city": "Tunis"})]
    sent = calls[0]
    assert sent["system"] == "system prompt" and sent["model"] == "some-claude-model"
    assert sent["tools"] == [{"name": "get_weather", "description": "Weather for a city.",
                              "input_schema": WEATHER.parameters}]
    assert "tool_choice" not in sent  # forcing a tool is rejected by current models

    model.add_results(conversation, [(turn.tool_calls[0], "22 C", False)])
    # The assistant content goes back whole (thinking block included), results in one user message.
    assert len(conversation["messages"][1]["content"]) == 3
    assert conversation["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "22 C", "is_error": False}]}


def test_provider_selection():
    assert llm.from_settings(Settings(llm_model="")) is None
    assert isinstance(llm.from_settings(Settings(llm_model="m", llm_provider="openai")), llm.OpenAICompatible)
    with pytest.raises(llm.LLMError):
        llm.from_settings(Settings(llm_model="m", llm_provider="something-else"))


# -------------------------------------------------------------------- agent loop

def test_agent_loop_reports_model_failures_instead_of_raising():
    class Broken:
        name = "broken"

        def start(self, system, user):
            return []

        def complete(self, conversation, tools):
            raise llm.LLMError("HTTP 500")

        def add_results(self, conversation, results):
            pass

    result = run_agent(Broken(), "s", "u", [Tool(WEATHER, lambda args: {"t": 22})], max_steps=3)
    assert result.decision is None and result.stopped == "error: HTTP 500"


# ---------------------------------------------------------------------------- API

def test_api_end_to_end(make_platform):
    platform = make_platform()
    client = TestClient(create_app(platform))

    assert client.get("/api/health").json() == {"status": "ok", "model": None}

    events = [{"service": "transfers", "exc_type": "LedgerTimeoutError",
               "message": f"ledger write timed out after {i} ms for transfer {i}"} for i in range(10)]
    ingested = client.post("/api/ingest/exceptions", json={"events": events}).json()
    assert ingested["stored"] == 10 and len(ingested["incidents_opened"]) == 1

    linked = client.post("/api/tickets", json={"customer": "alice", "text": "my transfer failed"}).json()
    assert linked["incident_id"] == ingested["incidents_opened"][0] and linked["status"] == "answered"
    draft = client.post("/api/tickets", json={"customer": "bob", "text": "when will my card arrive"}).json()
    assert draft["status"] == "awaiting_approval"

    overview = client.get("/api/overview").json()
    assert overview["counts"] == {"tickets": 2, "linked": 1, "answered_automatically": 1, "awaiting_approval": 1,
                                  "escalated": 0, "open_incidents": 1, "actions_waiting": 1}
    incident = overview["incidents"][0]
    assert incident["ticket_ids"] == [linked["id"]] and sum(incident["exceptions_per_minute"]) == 10
    assert incident["exceptions"][0]["count"] == 10 and incident["actions"][0]["status"] == "proposed"

    approved = client.post(f"/api/tickets/{draft['id']}/decision", json={"approve": True}).json()
    assert approved["status"] == "answered" and approved["decided_by"] == "human"
    assert client.post(f"/api/tickets/{draft['id']}/decision", json={"approve": True}).status_code == 409
    assert client.post("/api/tickets/999/decision", json={"approve": True}).status_code == 404

    action_id = incident["actions"][0]["id"]
    assert client.post(f"/api/actions/{action_id}/decision", json={"approve": True}).json()["status"] == "executed"
    assert client.get("/api/overview").json()["incidents"][0]["status"] == "mitigated"

    assert client.post("/api/ingest/exceptions", json={"events": [{"service": "nope", "exc_type": "X"}]}).status_code == 422
    assert client.post("/api/tickets", json={"customer": "x", "text": ""}).status_code == 422
    assert len(client.get("/api/audit").json()) > 5
