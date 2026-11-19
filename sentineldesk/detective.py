"""Log detective: turn a stream of application exceptions into incidents.

Plain counting, no model. An incident must open within seconds and must never be imagined,
so this part is deterministic and every decision comes with the numbers behind it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import Settings
from .db import ExceptionEvent, Incident, audit

# Anything that varies between two occurrences of the same bug: ids, amounts, addresses.
_VARIABLE = re.compile(r"0x[0-9a-f]+|[0-9a-f]{8}-[0-9a-f-]{27}|\d+")


def fingerprint(service: str, exc_type: str, message: str) -> str:
    """Same bug, same fingerprint, whatever account or amount was involved."""
    normalized = _VARIABLE.sub("#", message.lower()).strip()
    return hashlib.sha1(f"{service}|{exc_type}|{normalized}".encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Detection:
    kind: str  # "spike" | "new_error"
    reason: str


def evaluate(
    window_count: int,
    baseline_count: int,
    new_fingerprint_count: int,
    cfg: Settings,
) -> Optional[Detection]:
    """Decide from three counts whether a service is having an incident.

    window_count: exceptions in the last `spike_window_s`.
    baseline_count: exceptions in the `baseline_window_s` before that window.
    new_fingerprint_count: of the window's exceptions, how many belong to an error
        type never seen before the window.
    """
    if new_fingerprint_count >= cfg.new_error_min_events:
        return Detection(
            "new_error",
            f"{new_fingerprint_count} exceptions of a type never seen before, "
            f"in the last {cfg.spike_window_s} s.",
        )
    if window_count < cfg.spike_min_events:
        return None
    window_rate = window_count / cfg.spike_window_s
    baseline_rate = baseline_count / cfg.baseline_window_s
    if window_rate >= cfg.spike_ratio * baseline_rate:
        per_min = window_rate * 60
        base_per_min = baseline_rate * 60
        return Detection(
            "spike",
            f"{window_count} exceptions in the last {cfg.spike_window_s} s "
            f"({per_min:.1f}/min against a usual {base_per_min:.1f}/min).",
        )
    return None


def open_incident_for(session: Session, service: str) -> Optional[Incident]:
    return session.scalars(
        select(Incident).where(Incident.service == service, Incident.status != "resolved")
        .order_by(Incident.id.desc())
    ).first()


def ingest(session: Session, events: list[ExceptionEvent], now: datetime, cfg: Settings) -> list[Incident]:
    """Store events, then check each affected service. Returns incidents opened by this call."""
    session.add_all(events)
    session.flush()
    opened = []
    for service in sorted({e.service for e in events}):
        incident = check_service(session, service, now, cfg)
        if incident is not None:
            opened.append(incident)
    return opened


def check_service(session: Session, service: str, now: datetime, cfg: Settings) -> Optional[Incident]:
    """Open an incident for `service` if its exceptions warrant one. Returns it only when new."""
    window_start = now - timedelta(seconds=cfg.spike_window_s)
    baseline_start = window_start - timedelta(seconds=cfg.baseline_window_s)

    def count(*conditions) -> int:
        return session.scalar(
            select(func.count()).select_from(ExceptionEvent)
            .where(ExceptionEvent.service == service, *conditions)
        ) or 0

    window_count = count(ExceptionEvent.ts > window_start, ExceptionEvent.ts <= now)
    if window_count == 0:
        return None

    existing = open_incident_for(session, service)
    if existing is not None:
        # Already known: keep its clock fresh, and reopen it if a fix did not hold.
        existing.last_seen_at = now
        if existing.status == "mitigated":
            existing.status = "open"
            audit(session, "detective", "incident_reopened", now, incident=existing.id)
        return None

    baseline_count = count(ExceptionEvent.ts > baseline_start, ExceptionEvent.ts <= window_start)
    seen_before = select(ExceptionEvent.fingerprint).where(
        ExceptionEvent.service == service, ExceptionEvent.ts <= window_start
    )
    new_fingerprint_count = count(
        ExceptionEvent.ts > window_start, ExceptionEvent.ts <= now,
        ExceptionEvent.fingerprint.not_in(seen_before),
    )

    detection = evaluate(window_count, baseline_count, new_fingerprint_count, cfg)
    if detection is None:
        return None

    first_ts = session.scalar(
        select(func.min(ExceptionEvent.ts))
        .where(ExceptionEvent.service == service, ExceptionEvent.ts > window_start)
    )
    top = session.execute(
        select(ExceptionEvent.exc_type, func.count().label("n"))
        .where(ExceptionEvent.service == service, ExceptionEvent.ts > window_start)
        .group_by(ExceptionEvent.exc_type).order_by(func.count().desc())
    ).first()
    incident = Incident(
        service=service, source="logs", status="open",
        opened_at=first_ts or now, last_seen_at=now,
        title=f"{top[0] if top else 'Exceptions'} on {service}",
        reason=detection.reason,
    )
    session.add(incident)
    session.flush()
    audit(session, "detective", "incident_opened", now, incident=incident.id, kind=detection.kind,
          reason=detection.reason)
    return incident


def resolve_quiet(session: Session, now: datetime, cfg: Settings) -> list[Incident]:
    """Close incidents that have been quiet for long enough.

    A log-driven incident closes when its exceptions stop. A ticket-driven one has no
    exceptions to watch, so it closes only after an approved action and a quiet period
    with no new complaint (each linked ticket refreshes `last_seen_at`).
    """
    quiet_since = now - timedelta(seconds=cfg.quiet_resolve_s)
    resolved = []
    for incident in session.scalars(
        select(Incident).where(
            Incident.status != "resolved", Incident.last_seen_at <= quiet_since,
            or_(Incident.source == "logs", Incident.status == "mitigated"),
        )
    ):
        incident.status = "resolved"
        incident.resolved_at = now
        audit(session, "detective", "incident_resolved", now, incident=incident.id)
        resolved.append(incident)
    return resolved
