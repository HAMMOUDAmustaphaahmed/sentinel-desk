"""Correlator: a support ticket and a log exception are two views of the same problem.

Two directions:
- an incident is open and a customer complains about that feature: link the ticket, so
  twenty complaints become one investigation;
- several customers report the same feature failing and the logs show nothing: open an
  incident from the tickets alone. That is a failure monitoring did not see.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db import Incident, Ticket, audit


def match_incident(session: Session, ticket: Ticket, cfg: Settings) -> tuple[Optional[Incident], str]:
    """The open incident this ticket most plausibly reports, with the reason for the decision."""
    if not ticket.is_problem:
        return None, "The ticket does not report a failure."
    if ticket.feature == "general":
        return None, "The ticket is not about a monitored feature."
    if ticket.confidence < cfg.min_confidence:
        return None, f"Classifier confidence {ticket.confidence:.2f} is too low to link automatically."

    for incident in session.scalars(
        select(Incident).where(Incident.service == ticket.feature, Incident.status != "resolved")
        .order_by(Incident.id.desc())
    ):
        earliest = incident.opened_at - timedelta(seconds=cfg.link_before_s)
        latest = incident.last_seen_at + timedelta(seconds=cfg.link_after_s)
        if earliest <= ticket.created_at <= latest:
            return incident, (
                f"Reports a {ticket.feature} failure while incident #{incident.id} "
                f"is {incident.status} on the same feature."
            )
    return None, f"No open incident on {ticket.feature} at that time."


def link(session: Session, ticket: Ticket, incident: Incident, now: datetime, actor: str, reason: str) -> None:
    ticket.incident_id = incident.id
    audit(session, actor, "ticket_linked", now, ticket=ticket.id, incident=incident.id, reason=reason)


def detect_ticket_cluster(session: Session, feature: str, now: datetime, cfg: Settings) -> Optional[Incident]:
    """Open an incident when enough distinct customers report the same feature failing.

    Only unlinked, confidently classified problem tickets count. Returns the new incident,
    with those tickets already linked to it.
    """
    if feature == "general":
        return None
    since = now - timedelta(seconds=cfg.cluster_window_s)
    tickets = list(session.scalars(
        select(Ticket).where(
            Ticket.feature == feature, Ticket.is_problem.is_(True), Ticket.incident_id.is_(None),
            Ticket.confidence >= cfg.min_confidence, Ticket.created_at > since, Ticket.created_at <= now,
        ).order_by(Ticket.created_at)
    ))
    customers = {t.customer for t in tickets}
    if len(customers) < cfg.cluster_min_customers:
        return None

    incident = Incident(
        service=feature, source="tickets", status="open",
        opened_at=tickets[0].created_at, last_seen_at=now,
        title=f"Customers report {feature} failing, nothing in the logs",
        reason=(
            f"{len(customers)} customers reported a {feature} failure within "
            f"{cfg.cluster_window_s // 60} min, and no exception was logged."
        ),
    )
    session.add(incident)
    session.flush()
    audit(session, "correlator", "incident_opened", now, incident=incident.id, kind="ticket_cluster",
          reason=incident.reason)
    for ticket in tickets:
        link(session, ticket, incident, now, "correlator", "Part of the cluster that opened the incident.")
    return incident
