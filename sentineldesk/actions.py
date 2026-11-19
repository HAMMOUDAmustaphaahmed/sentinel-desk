"""Recovery actions: a short allowlist, proposed by an agent or a runbook, run only after approval.

There is no free-form command anywhere. An action is one of the names below, applied to
one service, and nothing executes until a person approves it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import httpx
from sqlalchemy.orm import Session

from .db import Action, Incident, audit

ALLOWED_ACTIONS: dict[str, str] = {
    "restart_service": "Restart the service's workers. Clears stuck connections and bad in-memory state.",
    "clear_cache": "Drop the service's cache so stale entries are rebuilt from the source.",
    "disable_feature": "Turn the feature off behind its flag so customers see a clear notice instead of failures.",
}

# (service, action kind) -> human-readable result. Raises on failure.
Executor = Callable[[str, str], str]


def http_executor(bank_url: str) -> Executor:
    def execute(service: str, kind: str) -> str:
        response = httpx.post(f"{bank_url}/admin/actions", json={"service": service, "action": kind}, timeout=10)
        response.raise_for_status()
        return str(response.json().get("result", "done"))
    return execute


def propose(session: Session, incident: Incident, kind: str, rationale: str, by: str, now: datetime) -> Action:
    if kind not in ALLOWED_ACTIONS:
        raise ValueError(f"'{kind}' is not an allowed action. Allowed: {', '.join(ALLOWED_ACTIONS)}.")
    action = Action(incident_id=incident.id, kind=kind, rationale=rationale, proposed_by=by,
                    status="proposed", created_at=now)
    session.add(action)
    session.flush()
    audit(session, by, "action_proposed", now, action=action.id, incident=incident.id, kind=kind)
    return action


def decide(session: Session, action: Action, approve: bool, now: datetime, execute: Executor) -> Action:
    if action.status != "proposed":
        raise ValueError(f"Action #{action.id} was already {action.status}.")
    action.decided_at = now
    if not approve:
        action.status = "rejected"
        audit(session, "human", "action_rejected", now, action=action.id)
        return action

    audit(session, "human", "action_approved", now, action=action.id, kind=action.kind)
    incident = action.incident
    try:
        action.result = execute(incident.service, action.kind)
    except Exception as error:  # the action's target is outside our control
        action.status = "failed"
        action.result = str(error)
        audit(session, "platform", "action_failed", now, action=action.id, error=str(error))
        return action

    action.status = "executed"
    if incident.status == "open":
        # Not "resolved" yet: that is decided by the failures actually stopping.
        incident.status = "mitigated"
        incident.last_seen_at = now
    audit(session, "platform", "action_executed", now, action=action.id, result=action.result)
    return action
