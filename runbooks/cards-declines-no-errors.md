---
title: Card payments declined with nothing in the logs
service: cards
trigger: tickets
action: clear_cache
cause: The card limits cache holds stale spending limits, so valid payments are declined as over the limit.
keywords: card declined payment not working limit stale cache silent
---

## What you see
No exception. Several customers report card payments declined although they have funds.

## Likely cause
Declines are a normal business result, so they are not logged as errors. A wave of them usually means the limits cache is serving stale spending limits.

## What to do
1. Clear the card service cache (`clear_cache`). Limits are reloaded from the source on the next payment.
2. Ask one affected customer to retry before closing.
