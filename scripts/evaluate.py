"""Measure the platform on data it has not seen. Writes docs/evaluation.json.

    python -m scripts.evaluate

Two parts:
1. Triage accuracy on the Banking77 test split (3,080 tickets the model never trained on).
2. Simulated incidents. Each scenario runs the whole platform on a fake clock: background
   noise in the logs, then either an outage that raises exceptions or a silent failure
   that only customers notice, with real test-split tickets arriving around it, mixed
   with unrelated tickets. We know which tickets belong to the incident, so we can count
   how many the platform linked, how many it linked wrongly, and how fast it noticed.

No language model is involved here: this measures the deterministic path that every
ticket goes through first.
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from sklearn.metrics import accuracy_score, f1_score
from sqlalchemy import select

from sentineldesk.config import ROOT, settings
from sentineldesk.db import Incident, Ticket, make_session_factory
from sentineldesk.intents import SERVICES, feature_of, is_problem
from sentineldesk.knowledge import KnowledgeBase
from sentineldesk.supervisor import Platform
from sentineldesk.triage import TriageModel, load_csv

SCENARIOS = 300
SEED = 7
START = datetime(2026, 1, 5, 9, 0, 0)

EXCEPTIONS = {
    "transfers": ("LedgerTimeoutError", "ledger write timed out after {n} ms for transfer {id}"),
    "cards": ("AcquirerConnectionError", "connection to acquirer gateway refused (attempt {n}) for payment {id}"),
    "topup": ("PaymentProviderError", "provider returned 502 while confirming top-up {id}"),
    "atm": ("AtmNetworkError", "no response from ATM network switch after {n} ms, withdrawal {id}"),
    "exchange": ("RateFeedStaleError", "rate feed is {n} s old, refusing to quote for order {id}"),
    "auth": ("IdentityProviderError", "identity provider rejected token refresh for session {id}"),
}


def exception(rng: random.Random, service: str, ts: datetime) -> dict:
    exc_type, template = EXCEPTIONS[service]
    return {"service": service, "exc_type": exc_type, "ts": ts,
            "message": template.format(n=rng.randint(3000, 30000), id=rng.randint(10**6, 10**7))}


def triage_metrics(model: TriageModel, texts: list[str], labels: list[str]) -> dict:
    predictions = model.classify_many(texts)
    intents = [p.intent for p in predictions]
    confident = [(label, p) for label, p in zip(labels, predictions) if p.confidence >= settings.min_confidence]
    unsure = [(label, p) for label, p in zip(labels, predictions) if p.confidence < settings.min_confidence]
    return {
        "test_tickets": len(texts),
        "intents": len(set(labels)),
        "intent_accuracy": round(accuracy_score(labels, intents), 4),
        "intent_macro_f1": round(f1_score(labels, intents, average="macro"), 4),
        "feature_accuracy": round(sum(feature_of(l) == p.feature for l, p in zip(labels, predictions)) / len(labels), 4),
        "failure_flag_accuracy": round(
            sum(is_problem(l) == p.is_problem for l, p in zip(labels, predictions)) / len(labels), 4),
        "below_confidence_threshold": {
            "share": round(len(unsure) / len(labels), 4),
            "accuracy": round(sum(l == p.intent for l, p in unsure) / max(1, len(unsure)), 4),
        },
        "above_confidence_threshold": {
            "accuracy": round(sum(l == p.intent for l, p in confident) / max(1, len(confident)), 4),
        },
    }


def run_scenario(rng: random.Random, model: TriageModel, kb: KnowledgeBase,
                 pool: dict[tuple[str, bool], list[str]], all_texts: list[tuple[str, str]]) -> dict:
    platform = Platform(make_session_factory("sqlite:///:memory:"), model, kb, settings,
                        executor=lambda service, kind: "simulated")
    kind = "outage" if rng.random() < 0.7 else "silent"
    service = rng.choice(SERVICES)
    while not pool.get((service, True)):
        service = rng.choice(SERVICES)
    fault_at = START + timedelta(minutes=rng.uniform(35, 45))  # after a full baseline window of normal traffic
    fault_for = timedelta(minutes=rng.uniform(6, 12))
    end = fault_at + fault_for + timedelta(minutes=8)

    timeline: list[tuple[datetime, str, object]] = []

    # Background: the odd exception on any service, all the time.
    t = START
    while t < end:
        t += timedelta(seconds=rng.expovariate(1 / 150))  # about one every 2.5 minutes
        timeline.append((t, "exception", exception(rng, rng.choice(SERVICES), t)))

    if kind == "outage":
        per_second = rng.uniform(0.3, 2.0)
        t = fault_at
        while t < fault_at + fault_for:
            t += timedelta(seconds=rng.expovariate(per_second))
            timeline.append((t, "exception", exception(rng, service, t)))

    # Customers hit by the fault write in, starting a little after it begins.
    related = rng.randint(5, 15)
    for _ in range(related):
        at = fault_at + timedelta(seconds=rng.uniform(20, fault_for.total_seconds()))
        timeline.append((at, "ticket", (rng.choice(pool[(service, True)]), True)))

    # Everyone else: any ticket about anything other than a failure of this feature.
    unrelated = rng.randint(8, 20)
    others = [text for text, label in all_texts if not (feature_of(label) == service and is_problem(label))]
    for _ in range(unrelated):
        at = START + timedelta(seconds=rng.uniform(0, (end - START).total_seconds()))
        timeline.append((at, "ticket", (rng.choice(others), False)))

    timeline.sort(key=lambda item: item[0])
    truth: dict[int, bool] = {}
    detected_at = None
    related_before_detection = 0
    batch: list[dict] = []
    batch_due = START + timedelta(seconds=5)
    customer = 0

    def flush(now: datetime) -> None:
        nonlocal batch, detected_at
        if batch:
            platform.ingest_exceptions(batch, now)
            batch = []
        if detected_at is None:
            with platform.sessions() as s:
                if s.scalars(select(Incident).where(Incident.service == service)).first():
                    detected_at = now

    for at, what, payload in timeline:
        while at >= batch_due:  # logs are shipped every five seconds
            flush(batch_due)
            platform.tick(batch_due)
            batch_due += timedelta(seconds=5)
        if what == "exception":
            batch.append(payload)
        else:
            text, is_related = payload
            customer += 1
            if is_related and detected_at is None:
                related_before_detection += 1
            ticket_id = platform.submit_ticket(f"customer-{customer}", text, at)
            truth[ticket_id] = is_related
            if detected_at is None:
                flush(at)
    flush(end)

    with platform.sessions() as s:
        incidents = list(s.scalars(select(Incident)))
        target_ids = {i.id for i in incidents if i.service == service}
        tickets = list(s.scalars(select(Ticket)))
        true_links = sum(1 for t in tickets if truth[t.id] and t.incident_id in target_ids)
        wrong_links = sum(1 for t in tickets if t.incident_id is not None
                          and not (truth[t.id] and t.incident_id in target_ids))
        return {
            "kind": kind, "detected": bool(target_ids),
            "delay_s": (detected_at - fault_at).total_seconds() if detected_at else None,
            "tickets_before_detection": related_before_detection,
            "related": related, "true_links": true_links, "wrong_links": wrong_links,
            "false_incidents": sum(1 for i in incidents if i.service != service),
            "extra_incidents_same_service": max(0, len(target_ids) - 1),
        }


def summarise(rows: list[dict]) -> dict:
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_kind[row["kind"]].append(row)
    true_links = sum(r["true_links"] for r in rows)
    wrong_links = sum(r["wrong_links"] for r in rows)
    related = sum(r["related"] for r in rows)
    out = {
        "scenarios": len(rows),
        "linking": {
            "tickets_caused_by_the_incident": related,
            "linked_correctly": true_links,
            "linked_wrongly": wrong_links,
            "precision": round(true_links / max(1, true_links + wrong_links), 4),
            "recall": round(true_links / max(1, related), 4),
        },
        "false_incidents_per_scenario": round(sum(r["false_incidents"] for r in rows) / len(rows), 3),
    }
    for kind, group in by_kind.items():
        delays = sorted(r["delay_s"] for r in group if r["delay_s"] is not None)
        entry = {
            "scenarios": len(group),
            "detected": round(sum(r["detected"] for r in group) / len(group), 4),
        }
        if delays:
            entry["seconds_to_detect_median"] = round(statistics.median(delays), 1)
            entry["seconds_to_detect_p90"] = round(delays[int(0.9 * (len(delays) - 1))], 1)
        if kind == "silent":
            counts = [r["tickets_before_detection"] for r in group if r["detected"]]
            entry["tickets_needed_median"] = statistics.median(counts) if counts else None
        out[kind] = entry
    return out


def main() -> None:
    test_path = settings.data_dir / "test.csv"
    if not test_path.exists() or not settings.model_path.exists():
        raise SystemExit("Run first: python -m scripts.fetch_data && python -m scripts.train")
    texts, labels = load_csv(test_path)
    model = TriageModel.load(settings.model_path)
    kb = KnowledgeBase.from_dirs(settings.runbook_dir, settings.faq_dir)

    pool: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for text, label in zip(texts, labels):
        pool[(feature_of(label), is_problem(label))].append(text)

    rng = random.Random(SEED)
    rows = [run_scenario(rng, model, kb, pool, list(zip(texts, labels))) for _ in range(SCENARIOS)]
    report = {"triage": triage_metrics(model, texts, labels), "incidents": summarise(rows),
              "seed": SEED, "language_model": None}

    out = ROOT / "docs" / "evaluation.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
