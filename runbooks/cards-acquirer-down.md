---
title: Card payments refused by the acquirer gateway
service: cards
trigger: logs
action: restart_service
cause: The card service has lost its session with the acquirer gateway and does not reconnect by itself.
keywords: AcquirerConnectionError acquirer gateway refused card payment declined
---

## What you see
`AcquirerConnectionError` on `POST /cards/pay`. Customers report declined card payments with money still in the account.

## Likely cause
The long-lived session with the acquirer gateway dropped and the client did not reconnect.

## What to do
1. Restart the card service (`restart_service`) to open a new session.
2. If the gateway still refuses connections, the acquirer is down on their side: turn card payments off behind the flag (`disable_feature`) so customers get a clear notice, and contact the acquirer.
