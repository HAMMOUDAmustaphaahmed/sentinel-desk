---
title: Top-ups paid but balance not updated
service: topup
trigger: tickets
action: clear_cache
cause: Top-ups are confirmed, but the balance cache is not being refreshed, so customers see an old balance.
keywords: top-up balance not updated pending credited silent
---

## What you see
No exception. Customers report that a top-up went through but the balance has not changed.

## Likely cause
The payment succeeded and the ledger is correct. The balance shown in the app comes from a cache that is no longer being invalidated.

## What to do
1. Clear the top-up service cache (`clear_cache`). Balances are recomputed from the ledger.
2. Confirm with one affected customer that the balance is now right.
