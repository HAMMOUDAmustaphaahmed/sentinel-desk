---
title: Sign-in failing at the identity provider
service: auth
trigger: logs
action: restart_service
cause: The auth service is using an expired signing key and the identity provider rejects every token refresh.
keywords: IdentityProviderError identity provider token refresh sign-in login verify
---

## What you see
`IdentityProviderError` on `POST /auth/login`. Customers cannot sign in or are asked to verify again and again.

## Likely cause
The signing keys were rotated and the auth service still holds the old one in memory.

## What to do
1. Restart the auth service (`restart_service`). It loads the current key at startup.
2. Never turn sign-in off behind a flag: that locks every customer out.
