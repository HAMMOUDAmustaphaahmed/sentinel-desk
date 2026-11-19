from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pytest

from sentineldesk.config import settings
from sentineldesk.db import make_session_factory
from sentineldesk.knowledge import KnowledgeBase
from sentineldesk.llm import ToolCall, Turn
from sentineldesk.supervisor import Platform
from sentineldesk.triage import TriageModel

T0 = datetime(2026, 1, 5, 12, 0, 0)

# A tiny training set with real Banking77 intent names. Tests must not need the dataset.
TRAINING = {
    "failed_transfer": [
        "my transfer failed", "the transfer did not go through", "transfer failed again why",
        "i tried to send money and the transfer failed", "bank transfer keeps failing",
        "why did my transfer fail", "transfer was unsuccessful", "sending money failed with an error",
    ],
    "declined_card_payment": [
        "my card payment was declined", "card declined at the shop", "why was my card payment declined",
        "the card got declined when paying", "payment with card declined", "card keeps getting declined",
        "my card was refused at checkout", "card payment declined although i have money",
    ],
    "top_up_failed": [
        "my top up failed", "top-up did not work", "the top up failed", "topping up failed with an error",
        "i cannot top up it fails", "top up was unsuccessful", "why did my top-up fail", "top up keeps failing",
    ],
    "card_arrival": [
        "when will my card arrive", "my new card has not arrived yet", "how long until the card is delivered",
        "where is my card", "i am still waiting for my card", "card delivery status",
        "has my card been posted", "tracking my new card",
    ],
    "exchange_rate": [
        "what exchange rate do you use", "which rate do i get for currency exchange", "how is the exchange rate set",
        "exchange rate for euros", "what is your currency conversion rate", "do you use the interbank exchange rate",
        "rate for exchanging dollars", "tell me the exchange rate",
    ],
    "transfer_timing": [
        "how long does a transfer take", "when will the transfer arrive", "transfer time to another bank",
        "how many days for an international transfer", "how fast are transfers", "time for a transfer to arrive",
        "when does the money arrive after a transfer", "duration of a bank transfer",
    ],
}


class FakeModel:
    """A scripted model: each call to `complete` returns the next prepared turn."""

    name = "fake"

    def __init__(self, turns: list[Turn]):
        self.turns = list(turns)
        self.conversations: list[dict[str, Any]] = []
        self.results: list[list[tuple[ToolCall, str, bool]]] = []

    def start(self, system: str, user: str) -> dict[str, Any]:
        conversation = {"system": system, "user": user}
        self.conversations.append(conversation)
        return conversation

    def complete(self, conversation: Any, tools: list[Any]) -> Turn:
        return self.turns.pop(0) if self.turns else Turn()

    def add_results(self, conversation: Any, results: list[tuple[ToolCall, str, bool]]) -> None:
        self.results.append(results)


def call(name: str, **args: Any) -> Turn:
    return Turn(tool_calls=[ToolCall(f"call_{name}", name, args)])


@pytest.fixture(scope="session")
def triage_model() -> TriageModel:
    texts = [t for group in TRAINING.values() for t in group]
    labels = [label for label, group in TRAINING.items() for _ in group]
    return TriageModel.train(texts, labels)


@pytest.fixture(scope="session")
def knowledge() -> KnowledgeBase:
    return KnowledgeBase.from_dirs(settings.runbook_dir, settings.faq_dir)


@pytest.fixture()
def make_platform(triage_model, knowledge):
    def build(model: Optional[FakeModel] = None, executor=None) -> Platform:
        executed: list[tuple[str, str]] = []

        def record(service: str, kind: str) -> str:
            executed.append((service, kind))
            return f"{kind} applied to {service}"

        platform = Platform(make_session_factory("sqlite:///:memory:"), triage_model, knowledge, settings,
                            model=model, executor=executor or record)
        platform.executed = executed  # type: ignore[attr-defined]
        return platform
    return build


def outage(service: str, count: int, at: datetime = T0) -> list[dict[str, Any]]:
    return [{"service": service, "exc_type": "LedgerTimeoutError", "ts": at,
             "message": f"ledger write timed out after {3000 + i} ms for transfer {100000 + i}"}
            for i in range(count)]
