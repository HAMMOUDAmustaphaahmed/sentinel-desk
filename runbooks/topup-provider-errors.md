---
title: Top-ups failing at the payment provider
service: topup
trigger: logs
action: disable_feature
cause: The external payment provider is returning errors when confirming top-ups. The fault is on their side.
keywords: PaymentProviderError provider 502 top-up failed topup
---

## What you see
`PaymentProviderError` with a 502 from the provider on `POST /topup`. Customers report failed or pending top-ups.

## Likely cause
The payment provider is degraded. Restarting our service does not help, because the error comes from them.

## What to do
1. Turn top-ups off behind the flag (`disable_feature`). Customers then see a clear "temporarily unavailable" notice instead of a failed payment and a possible hold on their card.
2. Check the provider's status page and open a ticket with them.
3. Turn the feature back on when their confirmations succeed again.
