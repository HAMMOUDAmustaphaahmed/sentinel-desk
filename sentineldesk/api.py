"""HTTP API: ingestion for the bank, and everything the dashboard reads and decides.

Demo software: there is no authentication. Put it behind your own before exposing it.
"""
from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from . import llm
from .actions import ALLOWED_ACTIONS
from .config import Settings, settings
from .db import Action, Audit, ExceptionEvent, Incident, Ticket, make_session_factory, utcnow
from .intents import SERVICES, feature_of, is_problem
from .knowledge import KnowledgeBase
from .supervisor import Platform
from .triage import TriageModel, load_csv

Service = Literal["transfers", "cards", "topup", "atm", "exchange", "auth"]


class ExceptionIn(BaseModel):
    service: Service
    exc_type: str = Field(min_length=1, max_length=120)
    message: str = Field(default="", max_length=2000)
    endpoint: str = Field(default="", max_length=200)
    ts: Optional[datetime] = None


class ExceptionBatch(BaseModel):
    events: list[ExceptionIn] = Field(min_length=1, max_length=500)


class TicketIn(BaseModel):
    customer: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=3, max_length=2000)


class TicketDecision(BaseModel):
    approve: bool
    reply: str = Field(default="", max_length=1500)


class ActionDecision(BaseModel):
    approve: bool


class FaultIn(BaseModel):
    service: Service
    mode: Literal["exception", "silent", "off"]


class DemoTickets(BaseModel):
    service: Service
    count: int = Field(default=5, ge=1, le=30)
    kind: Literal["problem", "question"] = "problem"


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="seconds") + "Z" if value else None


def ticket_out(t: Ticket) -> dict[str, Any]:
    return {
        "id": t.id, "created_at": _iso(t.created_at), "customer": t.customer, "text": t.text,
        "intent": t.intent, "confidence": round(t.confidence, 3), "feature": t.feature,
        "is_problem": t.is_problem, "status": t.status, "reply": t.reply, "reply_kind": t.reply_kind,
        "reply_sources": t.reply_sources, "decided_by": t.decided_by, "incident_id": t.incident_id,
        "trace": t.trace,
    }


def action_out(a: Action) -> dict[str, Any]:
    return {
        "id": a.id, "incident_id": a.incident_id, "kind": a.kind, "description": ALLOWED_ACTIONS.get(a.kind, ""),
        "rationale": a.rationale, "proposed_by": a.proposed_by, "status": a.status,
        "created_at": _iso(a.created_at), "decided_at": _iso(a.decided_at), "result": a.result,
    }


def create_app(platform: Optional[Platform] = None, cfg: Settings = settings) -> FastAPI:
    state: dict[str, Any] = {"platform": platform, "samples": None}

    def get_platform() -> Platform:
        if state["platform"] is None:
            if not cfg.model_path.exists():
                raise RuntimeError(
                    f"No triage model at {cfg.model_path}. Run: python -m scripts.fetch_data && python -m scripts.train")
            state["platform"] = Platform(
                make_session_factory(cfg.database_url), TriageModel.load(cfg.model_path),
                KnowledgeBase.from_dirs(cfg.runbook_dir, cfg.faq_dir), cfg, model=llm.from_settings(cfg),
            )
        return state["platform"]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        get_platform()

        async def housekeeping() -> None:
            while True:
                await asyncio.sleep(10)
                await asyncio.to_thread(get_platform().tick, utcnow())

        task = asyncio.create_task(housekeeping())
        yield
        task.cancel()

    app = FastAPI(title="Sentinel Desk", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware, allow_origins=[o.strip() for o in cfg.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )

    # ------------------------------------------------------------------ ingestion

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        p = get_platform()
        return {"status": "ok", "model": p.model.name if p.model else None}

    @app.post("/api/ingest/exceptions")
    def ingest_exceptions(batch: ExceptionBatch) -> dict[str, Any]:
        opened = get_platform().ingest_exceptions([e.model_dump() for e in batch.events], utcnow())
        return {"stored": len(batch.events), "incidents_opened": opened}

    @app.post("/api/tickets")
    def submit_ticket(body: TicketIn) -> dict[str, Any]:
        p = get_platform()
        ticket_id = p.submit_ticket(body.customer, body.text, utcnow())
        with p.sessions() as session:
            return ticket_out(session.get(Ticket, ticket_id))

    # -------------------------------------------------------------------- reading

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        p = get_platform()
        now = utcnow()
        with p.sessions() as session:
            def count(model, *conditions) -> int:
                return session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0

            total = count(Ticket)
            linked = count(Ticket, Ticket.incident_id.is_not(None))
            incidents = list(session.scalars(
                select(Incident).order_by((Incident.status == "resolved"), Incident.id.desc()).limit(20)))
            return {
                "now": _iso(now),
                "model": p.model.name if p.model else None,
                "counts": {
                    "tickets": total,
                    "linked": linked,
                    "answered_automatically": count(Ticket, Ticket.decided_by == "auto"),
                    "awaiting_approval": count(Ticket, Ticket.status == "awaiting_approval"),
                    "escalated": count(Ticket, Ticket.status == "escalated"),
                    "open_incidents": count(Incident, Incident.status != "resolved"),
                    "actions_waiting": count(Action, Action.status == "proposed"),
                },
                "incidents": [incident_out(p, session, i, now) for i in incidents],
                "tickets": [ticket_out(t) for t in session.scalars(
                    select(Ticket).order_by(Ticket.id.desc()).limit(40))],
            }

    def incident_out(p: Platform, session, incident: Incident, now: datetime) -> dict[str, Any]:
        # Exceptions per minute over the last 30 minutes, oldest first, for the sparkline.
        start = now.replace(second=0, microsecond=0) - timedelta(minutes=29)
        series = [0] * 30
        for (ts,) in session.execute(
            select(ExceptionEvent.ts).where(ExceptionEvent.service == incident.service, ExceptionEvent.ts >= start)
        ):
            index = int((ts - start).total_seconds() // 60)
            if 0 <= index < 30:
                series[index] += 1
        return {
            **p._incident_summary(session, incident),
            "last_seen_at": _iso(incident.last_seen_at), "resolved_at": _iso(incident.resolved_at),
            "opened_at": _iso(incident.opened_at),
            "analysis": incident.analysis, "analysis_by": incident.analysis_by,
            "exceptions_per_minute": series,
            "exceptions": p._exception_groups(session, incident),
            "actions": [action_out(a) for a in incident.actions],
            "ticket_ids": [t.id for t in incident.tickets],
        }

    @app.get("/api/audit")
    def audit_log(limit: int = 100) -> list[dict[str, Any]]:
        with get_platform().sessions() as session:
            return [{"id": a.id, "ts": _iso(a.ts), "actor": a.actor, "event": a.event, "detail": a.detail}
                    for a in session.scalars(select(Audit).order_by(Audit.id.desc()).limit(min(limit, 500)))]

    # ------------------------------------------------------------------ decisions

    @app.post("/api/tickets/{ticket_id}/decision")
    def decide_ticket(ticket_id: int, body: TicketDecision) -> dict[str, Any]:
        p = get_platform()
        try:
            p.decide_ticket(ticket_id, body.approve, utcnow(), body.reply)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        with p.sessions() as session:
            return ticket_out(session.get(Ticket, ticket_id))

    @app.post("/api/actions/{action_id}/decision")
    def decide_action(action_id: int, body: ActionDecision) -> dict[str, Any]:
        p = get_platform()
        try:
            p.decide_action(action_id, body.approve, utcnow())
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        with p.sessions() as session:
            return action_out(session.get(Action, action_id))

    # ----------------------------------------------------------------------- demo
    # Controls for the demonstration: break the fake bank, send sample tickets, start over.

    def sample_texts() -> dict[tuple[str, bool], list[str]]:
        """Real customer phrasings from the Banking77 test split, by feature and kind."""
        if state["samples"] is None:
            samples: dict[tuple[str, bool], list[str]] = {}
            path = cfg.data_dir / "test.csv"
            if path.exists():
                for text, label in zip(*load_csv(path)):
                    samples.setdefault((feature_of(label), is_problem(label)), []).append(text)
            state["samples"] = samples
        return state["samples"]

    @app.get("/api/demo/state")
    def demo_state() -> dict[str, Any]:
        try:
            faults = httpx.get(f"{cfg.bank_url}/admin/state", timeout=3).json()["faults"]
            return {"bank_reachable": True, "faults": faults, "services": list(SERVICES)}
        except (httpx.HTTPError, KeyError, ValueError):
            return {"bank_reachable": False, "faults": {}, "services": list(SERVICES)}

    @app.post("/api/demo/fault")
    def demo_fault(body: FaultIn) -> dict[str, Any]:
        try:
            response = httpx.post(f"{cfg.bank_url}/admin/faults", json=body.model_dump(), timeout=5)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as error:
            raise HTTPException(502, f"The demo bank is not reachable at {cfg.bank_url}.") from error

    @app.post("/api/demo/tickets")
    def demo_tickets(body: DemoTickets) -> dict[str, Any]:
        pool = sample_texts().get((body.service, body.kind == "problem"), [])
        if not pool:
            raise HTTPException(409, "No sample tickets available. Run: python -m scripts.fetch_data")
        p = get_platform()
        ids = [p.submit_ticket(f"customer-{random.randint(1000, 9999)}", random.choice(pool), utcnow())
               for _ in range(body.count)]
        return {"submitted": ids}

    @app.post("/api/demo/reset")
    def demo_reset() -> dict[str, str]:
        with get_platform().sessions() as session:
            for model in (Action, Ticket, Incident, ExceptionEvent, Audit):
                session.execute(delete(model))
            session.commit()
        try:
            httpx.post(f"{cfg.bank_url}/admin/reset", timeout=3)
        except httpx.HTTPError:
            pass  # the bank being down does not prevent clearing the platform
        return {"status": "reset"}

    return app


app = create_app()
