"""A small fake online bank to watch, break and repair.

It has six features, a switch to make any of them fail, and background traffic so that
a broken feature produces exceptions without anyone clicking. Two failure modes:

- "exception": requests raise. The exception is shipped to the platform, like an
  application logging to a central store.
- "silent": requests return 200 with a wrong result and log nothing. Only customers notice.
"""
from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://127.0.0.1:8000").rstrip("/")
TRAFFIC_PER_SECOND = float(os.environ.get("TRAFFIC_PER_SECOND", "2"))
NOISE_RATE = float(os.environ.get("NOISE_RATE", "0.004"))  # share of healthy requests that fail anyway

Service = Literal["transfers", "cards", "topup", "atm", "exchange", "auth"]

# What each feature raises when it is broken, and on which endpoint.
FAILURES: dict[str, tuple[str, str, str]] = {
    "transfers": ("LedgerTimeoutError", "ledger write timed out after {n} ms for transfer {id}", "POST /transfers"),
    "cards": ("AcquirerConnectionError", "connection to acquirer gateway refused (attempt {n}) for payment {id}",
              "POST /cards/pay"),
    "topup": ("PaymentProviderError", "provider returned 502 while confirming top-up {id}", "POST /topup"),
    "atm": ("AtmNetworkError", "no response from ATM network switch after {n} ms, withdrawal {id}",
            "POST /atm/withdraw"),
    "exchange": ("RateFeedStaleError", "rate feed is {n} s old, refusing to quote for order {id}", "POST /exchange"),
    "auth": ("IdentityProviderError", "identity provider rejected token refresh for session {id}",
             "POST /auth/login"),
}

faults: dict[str, str] = {}  # service -> "exception" | "silent"
_outbox: asyncio.Queue[dict] = asyncio.Queue(maxsize=5000)


class FaultIn(BaseModel):
    service: Service
    mode: Literal["exception", "silent", "off"]


class ActionIn(BaseModel):
    service: Service
    action: Literal["restart_service", "clear_cache", "disable_feature"]


class ServiceError(Exception):
    def __init__(self, service: str):
        exc_type, template, endpoint = FAILURES[service]
        self.event = {
            "service": service, "exc_type": exc_type, "endpoint": endpoint,
            "message": template.format(n=random.randint(3000, 30000), id=random.randint(10**6, 10**7)),
        }
        super().__init__(self.event["message"])


def call(service: str) -> dict[str, str]:
    """One customer operation on a feature."""
    mode = faults.get(service)
    # A healthy service still fails now and then. This gives detection a real baseline to beat.
    if mode == "exception" or (mode is None and random.random() < NOISE_RATE):
        error = ServiceError(service)
        try:
            _outbox.put_nowait(error.event)
        except asyncio.QueueFull:
            pass  # shipping logs must never block the application
        raise error
    if mode == "silent":
        return {"status": "pending"}  # accepted, never completes, nothing logged
    return {"status": "completed"}


async def ship_exceptions() -> None:
    """Send logged exceptions to the platform in small batches."""
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            batch = [await _outbox.get()]
            while not _outbox.empty() and len(batch) < 100:
                batch.append(_outbox.get_nowait())
            try:
                await client.post(f"{PLATFORM_URL}/api/ingest/exceptions", json={"events": batch})
            except httpx.HTTPError:
                await asyncio.sleep(2)  # platform down: drop this batch, keep serving


async def background_traffic() -> None:
    """Customers using the bank. Every feature gets its share of requests."""
    while True:
        await asyncio.sleep(random.expovariate(TRAFFIC_PER_SECOND))
        try:
            call(random.choice(list(FAILURES)))
        except ServiceError:
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(ship_exceptions()), asyncio.create_task(background_traffic())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Demo bank", lifespan=lifespan)


@app.post("/{service}/operation")
async def operation(service: Service) -> dict[str, str]:  # async: `call` touches the event loop's queue
    try:
        return call(service)
    except ServiceError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/admin/state")
def admin_state() -> dict[str, dict[str, str]]:
    return {"faults": faults}


@app.post("/admin/faults")
def admin_faults(body: FaultIn) -> dict[str, dict[str, str]]:
    if body.mode == "off":
        faults.pop(body.service, None)
    else:
        faults[body.service] = body.mode
    return {"faults": faults}


@app.post("/admin/actions")
def admin_actions(body: ActionIn) -> dict[str, str]:
    """Recovery actions. In this demo each of them clears the fault on the service."""
    was_broken = faults.pop(body.service, None)
    outcome = "the service is healthy again" if was_broken else "the service was already healthy"
    return {"result": f"{body.action} applied to {body.service}: {outcome}."}


@app.post("/admin/reset")
def admin_reset() -> dict[str, str]:
    faults.clear()
    return {"status": "reset"}
