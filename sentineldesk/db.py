"""Storage. SQLite by default so the project runs with zero setup; any SQLAlchemy URL works."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow() -> datetime:
    """Naive UTC. Every timestamp in the database uses this convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class ExceptionEvent(Base):
    __tablename__ = "exception_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    service: Mapped[str] = mapped_column(String(40), index=True)
    exc_type: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    endpoint: Mapped[str] = mapped_column(String(200), default="")
    fingerprint: Mapped[str] = mapped_column(String(16), index=True)

    __table_args__ = (Index("ix_events_service_ts", "service", "ts"),)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(40), index=True)
    # "logs": opened by exception detection. "tickets": opened because customers reported
    # a failure that produced no exception at all.
    source: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open | mitigated | resolved
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)  # why detection fired, in plain words
    analysis: Mapped[str] = mapped_column(Text, default="")  # the analyst's likely cause
    analysis_by: Mapped[str] = mapped_column(String(20), default="")  # agent | runbook

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="incident")
    actions: Mapped[list["Action"]] = relationship(back_populates="incident", order_by="Action.id")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    customer: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(80), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    feature: Mapped[str] = mapped_column(String(40), default="general", index=True)
    is_problem: Mapped[bool] = mapped_column(default=False)
    # answered: a reply went out. awaiting_approval: a draft waits for a person.
    # escalated: handed to a support engineer with no usable draft.
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    reply: Mapped[str] = mapped_column(Text, default="")
    reply_kind: Mapped[str] = mapped_column(String(20), default="")  # incident_status | knowledge
    reply_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    decided_by: Mapped[str] = mapped_column(String(20), default="")  # auto | human
    trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # one entry per step taken
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)

    incident: Mapped[Optional[Incident]] = relationship(back_populates="tickets")


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    rationale: Mapped[str] = mapped_column(Text, default="")
    proposed_by: Mapped[str] = mapped_column(String(20), default="")  # agent | runbook
    # proposed -> executed | failed (after approval), or proposed -> rejected
    status: Mapped[str] = mapped_column(String(12), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")

    incident: Mapped[Incident] = relationship(back_populates="actions")


class Audit(Base):
    """Append-only record of every decision, automatic or human."""

    __tablename__ = "audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    actor: Mapped[str] = mapped_column(String(40))
    event: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def make_session_factory(url: str) -> sessionmaker[Session]:
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool  # one shared connection, so tables persist
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def audit(session: Session, actor: str, event: str, now: datetime, **detail: Any) -> None:
    session.add(Audit(ts=now, actor=actor, event=event, detail=detail))
