"""From a Banking77 intent to the bank feature it concerns, and whether it reports a failure.

The mapping is rule-based on the intent name on purpose: it is short, reviewable in one
screen, and it does not silently change when the classifier is retrained.
"""
from __future__ import annotations

SERVICES = ("transfers", "cards", "topup", "atm", "exchange", "auth")

# First match wins, so the more specific keywords come first.
_FEATURE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("topup", ("top_up", "topping_up")),
    ("atm", ("cash_withdrawal", "atm", "declined_cash", "wrong_amount_of_cash")),
    ("exchange", ("exchange", "fiat")),
    ("transfers", ("transfer", "beneficiary", "receiving_money")),
    (
        "cards",
        ("card_payment", "declined_card", "card_not_working", "contactless", "card_acceptance",
         "charged_twice", "refund", "direct_debit"),
    ),
    ("auth", ("verify", "identity", "passcode", "pin_blocked", "why_verify")),
)

# An intent whose name contains one of these describes something that went wrong with the
# service. "not_recognised" is deliberately absent: an unrecognised payment is a fraud
# concern for one customer, not a sign that a feature is down.
_PROBLEM_MARKERS = (
    "failed", "declined", "not_working", "pending", "reverted", "wrong",
    "unable", "not_updated", "not_showing", "not_received", "charged_twice", "blocked",
)


def feature_of(intent: str) -> str:
    name = intent.lower()
    for feature, keywords in _FEATURE_RULES:
        if any(k in name for k in keywords):
            return feature
    return "general"


def is_problem(intent: str) -> bool:
    name = intent.lower()
    return any(marker in name for marker in _PROBLEM_MARKERS)
