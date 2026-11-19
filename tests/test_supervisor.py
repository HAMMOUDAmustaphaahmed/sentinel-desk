from datetime import timedelta

import pytest
from sqlalchemy import select

from sentineldesk.db import Action, Audit, Incident, Ticket
from sentineldesk.llm import ToolCall, Turn

from .conftest import T0, FakeModel, call, outage


def ticket(platform, ticket_id: int) -> Ticket:
    with platform.sessions() as s:
        return s.get(Ticket, ticket_id)


# ------------------------------------------------------------- without a model

def test_ticket_about_an_open_incident_is_linked_and_answered_at_once(make_platform):
    platform = make_platform()
    (incident_id,) = platform.ingest_exceptions(outage("transfers", 10), T0)
    t = ticket(platform, platform.submit_ticket("alice", "my transfer failed", T0 + timedelta(minutes=1)))
    assert t.incident_id == incident_id
    assert (t.status, t.decided_by, t.reply_kind) == ("answered", "auto", "incident_status")
    assert f"incident #{incident_id}" in t.reply
    assert [step["step"] for step in t.trace] == ["triage", "correlate", "reply"]


def test_ticket_about_another_feature_is_not_linked(make_platform):
    platform = make_platform()
    platform.ingest_exceptions(outage("transfers", 10), T0)
    t = ticket(platform, platform.submit_ticket("bob", "my card payment was declined", T0 + timedelta(minutes=1)))
    assert t.incident_id is None and t.feature == "cards"


def test_question_gets_a_draft_from_the_knowledge_base_and_waits_for_approval(make_platform):
    platform = make_platform()
    t = ticket(platform, platform.submit_ticket("carol", "when will my card arrive", T0))
    assert t.status == "awaiting_approval" and t.decided_by == ""
    assert t.reply_sources == ["card-arrival"] and "ten working days" in t.reply

    platform.decide_ticket(t.id, True, T0 + timedelta(minutes=5), edited_reply="Edited by a person.")
    t = ticket(platform, t.id)
    assert (t.status, t.decided_by, t.reply) == ("answered", "human", "Edited by a person.")
    with pytest.raises(ValueError):
        platform.decide_ticket(t.id, True, T0)  # already decided


def test_rejected_draft_goes_to_a_person(make_platform):
    platform = make_platform()
    t = ticket(platform, platform.submit_ticket("carol", "what exchange rate do you use", T0))
    platform.decide_ticket(t.id, False, T0)
    assert ticket(platform, t.id).status == "escalated"


def test_unclear_ticket_is_escalated_not_guessed(make_platform):
    platform = make_platform()
    t = ticket(platform, platform.submit_ticket("dave", "hello i have a question about something", T0))
    assert t.confidence < 0.35
    assert t.status == "escalated" and t.reply == ""


def test_complaints_with_nothing_in_the_logs_open_an_incident(make_platform):
    platform = make_platform()
    ids = [platform.submit_ticket(f"customer-{i}", "my top up failed", T0 + timedelta(minutes=i)) for i in range(4)]
    with platform.sessions() as s:
        (incident,) = s.scalars(select(Incident))
        assert (incident.service, incident.source) == ("topup", "tickets")
        assert "4 customers" in incident.reason
        # Every ticket of the cluster is linked and informed, including the earlier ones.
        assert {t.id for t in incident.tickets} == set(ids)
        assert all(t.status == "answered" for t in incident.tickets)
        # The runbook for a silent top-up failure recommends clearing the cache.
        assert [(a.kind, a.status, a.proposed_by) for a in incident.actions] == [("clear_cache", "proposed", "runbook")]


def test_same_customer_complaining_four_times_is_not_a_cluster(make_platform):
    platform = make_platform()
    for i in range(4):
        platform.submit_ticket("one-customer", "my top up failed", T0 + timedelta(minutes=i))
    with platform.sessions() as s:
        assert s.scalars(select(Incident)).first() is None


def test_tickets_sent_just_before_detection_are_adopted_by_the_incident(make_platform):
    platform = make_platform()
    early = platform.submit_ticket("erin", "my transfer failed", T0)
    assert ticket(platform, early).incident_id is None
    (incident_id,) = platform.ingest_exceptions(outage("transfers", 10, T0 + timedelta(minutes=2)),
                                                 T0 + timedelta(minutes=2))
    t = ticket(platform, early)
    assert t.incident_id == incident_id and t.reply_kind == "incident_status" and t.status == "answered"


def test_action_runs_only_after_approval_and_only_from_the_allowlist(make_platform):
    platform = make_platform()
    (incident_id,) = platform.ingest_exceptions(outage("transfers", 10), T0)
    with platform.sessions() as s:
        (action,) = s.get(Incident, incident_id).actions
        assert (action.kind, action.status) == ("restart_service", "proposed")
    assert platform.executed == []  # proposing runs nothing

    assert platform.decide_action(action.id, True, T0 + timedelta(minutes=1)) == "executed"
    assert platform.executed == [("transfers", "restart_service")]
    with platform.sessions() as s:
        assert s.get(Incident, incident_id).status == "mitigated"
        events = [a.event for a in s.scalars(select(Audit).order_by(Audit.id))]
        assert events[-3:] == ["action_proposed", "action_approved", "action_executed"]
    with pytest.raises(ValueError):
        platform.decide_action(action.id, True, T0)  # cannot run twice


def test_rejected_or_failing_action_leaves_the_incident_open(make_platform):
    def broken(service, kind):
        raise ConnectionError("bank unreachable")

    platform = make_platform(executor=broken)
    (incident_id,) = platform.ingest_exceptions(outage("transfers", 10), T0)
    with platform.sessions() as s:
        action_id = s.get(Incident, incident_id).actions[0].id
    assert platform.decide_action(action_id, True, T0) == "failed"
    with platform.sessions() as s:
        assert s.get(Incident, incident_id).status == "open"
        assert "unreachable" in s.get(Action, action_id).result


# ---------------------------------------------------------------- with a model

def test_support_agent_links_a_ticket_the_rules_could_not(make_platform):
    model = FakeModel([
        # incident analyst, on the outage
        call("propose_action", kind="restart_service", likely_cause="Stale ledger connections.", rationale="Runbook."),
        # support agent, on the vague ticket
        call("list_open_incidents"),
        call("link_to_incident", incident_id=1, reason="Customer says money they sent never left the account."),
    ])
    platform = make_platform(model)
    platform.ingest_exceptions(outage("transfers", 10), T0)
    # Too vague for the classifier, so the correlator refuses to link it by itself.
    t = ticket(platform, platform.submit_ticket("fay", "hello i have a question about something",
                                                T0 + timedelta(minutes=1)))
    assert t.incident_id == 1 and t.status == "answered" and t.reply_kind == "incident_status"
    assert [s["detail"].split(":")[0] for s in t.trace if s["step"] == "tool"] == [
        "list_open_incidents", "link_to_incident"]
    # The customer's words reach the model inside a delimited block, as data.
    assert "<ticket_text>\nhello i have a question about something\n</ticket_text>" in model.conversations[-1]["user"]


def test_agent_reply_must_cite_articles_that_exist(make_platform):
    model = FakeModel([
        call("propose_reply", reply="Your card will arrive tomorrow, guaranteed.", sources=["made-up-article"]),
        call("search_knowledge", query="card arrival"),
        call("propose_reply", reply="A new card usually arrives within ten working days.", sources=["card-arrival"]),
    ])
    platform = make_platform(model)
    t = ticket(platform, platform.submit_ticket("gus", "when will my card arrive", T0))
    assert t.status == "awaiting_approval"  # written by the agent, still approved by a person
    assert t.reply_sources == ["card-arrival"] and "ten working days" in t.reply
    rejected = model.results[0][0]
    assert rejected[2] is True and "made-up-article" in rejected[1]


def test_agent_that_cannot_decide_falls_back_to_the_deterministic_path(make_platform):
    for turns in ([Turn(text="I am not sure.")], [Turn(refused=True)], [call("search_knowledge", query="x")] * 20):
        platform = make_platform(FakeModel(list(turns)))
        t = ticket(platform, platform.submit_ticket("hal", "when will my card arrive", T0))
        assert t.status == "awaiting_approval" and t.reply_sources == ["card-arrival"]
        assert any(s["step"] == "fallback" for s in t.trace)


def test_analyst_agent_cannot_propose_an_action_outside_the_allowlist(make_platform):
    model = FakeModel([
        call("propose_action", kind="drop_database", likely_cause="x", rationale="y"),
        Turn(tool_calls=[ToolCall("c1", "get_exceptions", {})]),
        call("propose_action", kind="clear_cache", likely_cause="Stale cache entries.", rationale="Cheap and safe."),
    ])
    platform = make_platform(model)
    (incident_id,) = platform.ingest_exceptions(outage("transfers", 10), T0)
    with platform.sessions() as s:
        incident = s.get(Incident, incident_id)
        assert (incident.analysis, incident.analysis_by) == ("Stale cache entries.", "agent")
        assert [(a.kind, a.proposed_by, a.status) for a in incident.actions] == [
            ("clear_cache", "analyst agent", "proposed")]
    assert "Not an allowed action" in model.results[0][0][1]
    assert platform.executed == []
