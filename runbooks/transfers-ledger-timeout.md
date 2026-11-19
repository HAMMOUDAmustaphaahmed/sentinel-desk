---
title: Transfers failing with ledger timeouts
service: transfers
trigger: logs
action: restart_service
cause: The transfer workers hold stale connections to the ledger database and every write times out.
keywords: LedgerTimeoutError ledger write timed out transfer pending failed
---

## What you see
`LedgerTimeoutError` on `POST /transfers`, rising within a minute or two. Customers report transfers that fail or stay pending.

## Likely cause
The connection pool between the transfer workers and the ledger database has gone stale, usually after a database failover or a network blip. New writes wait on dead connections until they time out.

## What to do
1. Restart the transfer workers (`restart_service`). This rebuilds the pool. Transfers that timed out were never written, so nothing is duplicated.
2. Watch the exception rate for five minutes. It should fall to zero.
3. If it does not, the ledger database itself is unhealthy: page the database on-call. Do not restart again.

## What not to do
Do not clear the cache. Transfers do not read from it, so it changes nothing.
