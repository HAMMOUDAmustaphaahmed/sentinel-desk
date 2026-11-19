from datetime import timedelta

from sqlalchemy import select

from sentineldesk import detective
from sentineldesk.config import settings as cfg
from sentineldesk.db import Incident
from sentineldesk.intents import feature_of, is_problem

from .conftest import T0, outage


def test_intents_map_to_features_and_failures():
    assert feature_of("failed_transfer") == "transfers" and is_problem("failed_transfer")
    assert feature_of("top_up_failed") == "topup" and is_problem("top_up_failed")
    assert feature_of("declined_cash_withdrawal") == "atm"  # not "cards", despite "declined"
    assert feature_of("card_arrival") == "general" and not is_problem("card_arrival")
    assert not is_problem("transfer_timing")
    # An unrecognised payment is one customer's fraud worry, not an outage.
    assert not is_problem("card_payment_not_recognised")


def test_fingerprint_ignores_what_varies_between_occurrences():
    a = detective.fingerprint("transfers", "LedgerTimeoutError", "ledger write timed out after 4012 ms for transfer 991")
    b = detective.fingerprint("transfers", "LedgerTimeoutError", "Ledger write timed out after 87 ms for transfer 5")
    assert a == b
    assert a != detective.fingerprint("transfers", "LedgerTimeoutError", "ledger connection refused")
    assert a != detective.fingerprint("cards", "LedgerTimeoutError", "ledger write timed out after 1 ms for transfer 2")


def test_evaluate_thresholds():
    # Too few events is never an incident, however quiet the baseline.
    assert detective.evaluate(4, 0, 0, cfg) is None
    # 6 in two minutes against 30 in the half hour before (1/min): three times the usual rate.
    assert detective.evaluate(6, 30, 0, cfg).kind == "spike"
    # The same 6 against a baseline that is just as busy is normal traffic.
    assert detective.evaluate(6, 90, 0, cfg) is None
    # A never-seen error type needs only three occurrences.
    assert detective.evaluate(3, 500, 3, cfg).kind == "new_error"
    assert detective.evaluate(2, 500, 2, cfg) is None


def test_spike_opens_one_incident_and_later_events_do_not_duplicate_it(make_platform):
    platform = make_platform()
    assert platform.ingest_exceptions(outage("transfers", 2), T0) == []  # a trickle
    opened = platform.ingest_exceptions(outage("transfers", 10), T0 + timedelta(seconds=5))
    assert len(opened) == 1
    assert platform.ingest_exceptions(outage("transfers", 10), T0 + timedelta(seconds=10)) == []
    with platform.sessions() as s:
        incident = s.get(Incident, opened[0])
        assert (incident.service, incident.source, incident.status) == ("transfers", "logs", "open")
        assert "never seen before" in incident.reason
        assert incident.last_seen_at == T0 + timedelta(seconds=10)


def test_busy_but_steady_service_is_not_an_incident(make_platform):
    platform = make_platform()
    # Two exceptions a minute for forty minutes: noisy, but it is this service's normal.
    for minute in range(40):
        at = T0 + timedelta(minutes=minute)
        platform.ingest_exceptions(outage("cards", 2, at), at)
    with platform.sessions() as s:
        # The very first minutes look like a new error type; nothing opens after that.
        incidents = list(s.scalars(select(Incident)))
        assert len(incidents) <= 1
        assert all(i.opened_at <= T0 + timedelta(minutes=2) for i in incidents)


def test_incident_resolves_after_quiet_period_and_reopens_if_fix_does_not_hold(make_platform):
    platform = make_platform()
    (incident_id,) = platform.ingest_exceptions(outage("transfers", 10), T0)
    with platform.sessions() as s:
        action_id = s.get(Incident, incident_id).actions[0].id
    platform.decide_action(action_id, True, T0 + timedelta(seconds=30))

    # Exceptions keep coming after the fix: it did not hold.
    platform.ingest_exceptions(outage("transfers", 5, T0 + timedelta(seconds=60)), T0 + timedelta(seconds=60))
    with platform.sessions() as s:
        assert s.get(Incident, incident_id).status == "open"

    assert platform.tick(T0 + timedelta(seconds=120)) == []  # not quiet for long enough
    assert platform.tick(T0 + timedelta(seconds=60 + cfg.quiet_resolve_s)) == [incident_id]
    with platform.sessions() as s:
        assert s.get(Incident, incident_id).status == "resolved"
