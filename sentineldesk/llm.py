"""Model access for the agents, independent of the provider.

Two adapters cover the field:
- `OpenAICompatible`: the chat-completions format that OpenAI, Groq, Mistral, Gemini,
  OpenRouter, DeepSeek, Together and local servers (Ollama, vLLM) all accept.
- `Anthropic`: the Claude API, through the official SDK.

Both expose the same three calls, so the agent loop never sees a provider detail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import httpx

from .config import Settings


class LLMError(RuntimeError):
    """The model could not be reached or answered with an error. Agents fall back on this."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    refused: bool = False  # the provider declined the request


class ChatModel(Protocol):
    name: str

    def start(self, system: str, user: str) -> Any:
        """A new conversation, in whatever shape the provider needs."""

    def complete(self, conversation: Any, tools: list[ToolSpec]) -> Turn:
        """Ask for the next assistant turn and record it in the conversation."""

    def add_results(self, conversation: Any, results: list[tuple[ToolCall, str, bool]]) -> None:
        """Record tool results as (call, content, is_error), in one message."""


class OpenAICompatible:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self.name = model
        self._model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
            transport=transport,  # tests pass a mock here
        )

    def start(self, system: str, user: str) -> list[dict[str, Any]]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def complete(self, conversation: list[dict[str, Any]], tools: list[ToolSpec]) -> Turn:
        payload = {
            "model": self._model,
            "messages": conversation,
            "tools": [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ],
        }
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
        except httpx.HTTPStatusError as error:
            raise LLMError(f"HTTP {error.response.status_code}: {error.response.text[:300]}") from error
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            raise LLMError(str(error)) from error

        calls = []
        for raw in message.get("tool_calls") or []:
            try:
                args = json.loads(raw["function"].get("arguments") or "{}")
            except ValueError:
                args = {}  # the agent loop reports the missing arguments back to the model
            calls.append(ToolCall(raw["id"], raw["function"]["name"], args if isinstance(args, dict) else {}))

        # Keep only the fields every provider accepts back.
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        conversation.append(assistant)
        return Turn(text=message.get("content") or "", tool_calls=calls)

    def add_results(self, conversation: list[dict[str, Any]], results: list[tuple[ToolCall, str, bool]]) -> None:
        for call, content, _is_error in results:
            conversation.append({"role": "tool", "tool_call_id": call.id, "content": content})


class Anthropic:
    def __init__(self, model: str, api_key: str = "", max_tokens: int = 16000):
        try:
            import anthropic
        except ImportError as error:  # optional dependency
            raise LLMError("LLM_PROVIDER=anthropic needs the SDK: pip install anthropic") from error
        self._sdk = anthropic
        # Without an explicit key the SDK resolves credentials from the environment.
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.name = model
        self._model = model
        self._max_tokens = max_tokens

    def start(self, system: str, user: str) -> dict[str, Any]:
        return {"system": system, "messages": [{"role": "user", "content": user}]}

    def complete(self, conversation: dict[str, Any], tools: list[ToolSpec]) -> Turn:
        sdk = self._sdk
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=conversation["system"],
                tools=[{"name": t.name, "description": t.description, "input_schema": t.parameters}
                       for t in tools],
                messages=conversation["messages"],
            )
        except sdk.RateLimitError as error:
            raise LLMError(f"Rate limited: {error}") from error
        except sdk.APIStatusError as error:
            raise LLMError(f"HTTP {error.status_code}: {error}") from error
        except sdk.APIConnectionError as error:
            raise LLMError(f"Connection failed: {error}") from error

        # Check why the model stopped before reading what it wrote.
        if response.stop_reason == "refusal":
            return Turn(refused=True)

        # The whole content goes back unchanged on the next request, thinking blocks included.
        conversation["messages"].append({"role": "assistant", "content": response.content})
        text = "".join(block.text for block in response.content if block.type == "text")
        calls = [ToolCall(block.id, block.name, dict(block.input))
                 for block in response.content if block.type == "tool_use"]
        return Turn(text=text, tool_calls=calls)

    def add_results(self, conversation: dict[str, Any], results: list[tuple[ToolCall, str, bool]]) -> None:
        # All results of one turn travel in a single user message.
        conversation["messages"].append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}
                for call, content, is_error in results
            ],
        })


def from_settings(cfg: Settings) -> Optional[ChatModel]:
    """The configured model, or None when the platform runs without one."""
    if not cfg.llm_model:
        return None
    if cfg.llm_provider == "anthropic":
        return Anthropic(cfg.llm_model, cfg.llm_api_key)
    if cfg.llm_provider == "openai":
        return OpenAICompatible(cfg.llm_base_url, cfg.llm_model, cfg.llm_api_key)
    raise LLMError(f"Unknown LLM_PROVIDER '{cfg.llm_provider}'. Use 'openai' or 'anthropic'.")
