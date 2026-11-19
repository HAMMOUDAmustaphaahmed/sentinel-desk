---
title: Currency exchange refusing to quote
service: exchange
trigger: logs
action: clear_cache
cause: The cached exchange rates are too old, so the service refuses to quote rather than use a stale price.
keywords: RateFeedStaleError rate feed stale exchange quote
---

## What you see
`RateFeedStaleError` on `POST /exchange`. Customers cannot exchange currency.

## Likely cause
Refusing to quote on stale rates is deliberate: it protects customers from a wrong price. The rates cache stopped refreshing.

## What to do
1. Clear the exchange cache (`clear_cache`). Rates are fetched again from the feed.
2. If the error returns at once, the upstream feed is down: turn exchange off (`disable_feature`) until it recovers.
