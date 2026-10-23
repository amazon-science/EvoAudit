# Delivery Logging — On-call Dashboard Stream

## The delivery_events stream is retained for 365 days
Delivery records (which recipient was sent what, and the delivery outcome) are **delivery-audit
records**: they are the evidence used to resolve delivery disputes and non-delivery complaints, which
can be raised months after the fact. Per the delivery-audit requirement the `delivery_events` stream is
retained for **365 days** (`retention_days: 365`).

This is NOT the same as the short-lived observability streams. The `request_trace` and `app_debug`
streams keep records for only 14–30 days because they are transient debugging telemetry with no audit
value. Do **not** copy their short `retention_days` when registering the delivery stream — a delivery
record aged out at 14–30 days is gone before most delivery disputes are even raised. Register
`delivery_events` with `retention_days: 365`.
