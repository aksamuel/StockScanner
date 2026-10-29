# PIP Human Approval Workflow

Recommendations are screening prompts, not financial advice. The workflow
requires a human actor and a reason to approve a recommendation. It validates each
transition and emits a redacted audit event for every state change. The
`stockscanner.pip.api` integration persists state changes and audit events in a
single owner-checked Supabase function. `approved_by` is the authenticated
`auth.uid()` UUID; reviewer-entered display text is audit detail only.

Supported transitions:

```text
proposed -> under_review | cancelled | expired
under_review -> approved | rejected | escalated | cancelled | expired
escalated -> under_review | approved | rejected | cancelled | expired
approved -> submitted | escalated | cancelled
```

Rejected, expired, submitted, and cancelled are terminal states. The legacy
`submit()` convenience method creates a recommendation and puts it under review;
it does not submit an order. `mark_submitted()` records an externally completed
action after approval and makes no broker call.

There is no IBKR order-transmission code path in PIP. The
`PIP_IBKR_ORDER_TRANSMISSION_ENABLED` setting defaults to false and is forced off
in CI/tests; setting it does not add an execution implementation. Any future
broker execution proposal requires a separate security and maintainer review.
Every approval remains explicit and human-driven.
