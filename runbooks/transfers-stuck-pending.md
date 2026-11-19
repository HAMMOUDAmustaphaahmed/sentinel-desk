---
title: Transfers accepted but never completed
service: transfers
trigger: tickets
action: restart_service
cause: The settlement worker has stopped consuming its queue: transfers are accepted, then never settled, and nothing is logged.
keywords: transfer pending not received recipient stuck no exception silent
---

## What you see
No exception at all. Customers report that a transfer shows as pending for a long time, or that the recipient never received it.

## Likely cause
The API accepts the transfer and puts it on the settlement queue, but the settlement worker has stopped consuming. Accepting succeeds, so nothing is logged as an error.

## What to do
1. Restart the transfer service (`restart_service`). The worker reconnects and drains the queue in order.
2. Check the queue depth afterwards. It should fall steadily.
3. Tell the affected customers their transfer will complete; they must not send it again.
