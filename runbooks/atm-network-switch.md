---
title: Cash withdrawals failing at the ATM network
service: atm
trigger: logs
action: restart_service
cause: The connection to the ATM network switch is hung: requests are sent and no response comes back.
keywords: AtmNetworkError ATM network switch no response cash withdrawal declined
---

## What you see
`AtmNetworkError` on `POST /atm/withdraw`. Customers report declined cash withdrawals.

## Likely cause
The connection to the network switch is half-open: we send, nothing comes back.

## What to do
1. Restart the ATM service (`restart_service`) to drop the hung connection.
2. If withdrawals still fail, the switch operator has an outage: turn the feature off (`disable_feature`) and call them.
