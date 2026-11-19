"""The agent loop: a model, a set of tools, and a decision it must end on.

An agent investigates with lookup tools, then commits through exactly one *decision*
tool (link, reply, escalate, propose an action...). A decision is validated by ordinary
code before it counts; a rejected decision goes back to the model as an error so it can
correct itself. If the model stops without deciding, refuses, or runs out of steps, the
loop reports that and the caller falls back to a person.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .llm import ChatModel, LLMError, ToolSpec

# A lookup returns data for the model. A decision returns (accepted, message).
Lookup = Callable[[dict[str, Any]], Any]
Decision = Callable[[dict[str, Any]], tuple[bool, str]]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    run: Callable[[dict[str, Any]], Any]
    is_decision: bool = False


@dataclass
class AgentResult:
    decision: Optional[str] = None  # name of the accepted decision tool
    args: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)  # every tool call, for the audit trail
    stopped: str = ""  # why there is no decision: refused | no_decision | max_steps | error: ...


def _preview(value: str, limit: int = 240) -> str:
    return value if len(value) <= limit else value[:limit] + "…"


def run_agent(model: ChatModel, system: str, user: str, tools: list[Tool], max_steps: int) -> AgentResult:
    by_name = {t.spec.name: t for t in tools}
    specs = [t.spec for t in tools]
    result = AgentResult()
    conversation = model.start(system, user)

    for _ in range(max_steps):
        try:
            turn = model.complete(conversation, specs)
        except LLMError as error:
            result.stopped = f"error: {error}"
            return result
        if turn.refused:
            result.stopped = "refused"
            return result
        if not turn.tool_calls:
            result.stopped = "no_decision"
            return result

        outputs = []
        for call in turn.tool_calls:
            tool = by_name.get(call.name)
            if tool is None:
                content, is_error = f"Unknown tool '{call.name}'.", True
            elif result.decision is not None:
                content, is_error = "A decision was already recorded for this case.", True
            else:
                try:
                    value = tool.run(call.args)
                except (KeyError, TypeError, ValueError) as error:
                    content, is_error = f"Invalid arguments: {error}", True
                else:
                    if tool.is_decision:
                        accepted, content = value
                        is_error = not accepted
                        if accepted:
                            result.decision, result.args = call.name, call.args
                    else:
                        content, is_error = json.dumps(value, ensure_ascii=False, default=str), False
            result.steps.append({"tool": call.name, "args": call.args, "ok": not is_error,
                                 "result": _preview(content)})
            outputs.append((call, content, is_error))

        if result.decision is not None:
            return result
        model.add_results(conversation, outputs)

    result.stopped = "max_steps"
    return result
