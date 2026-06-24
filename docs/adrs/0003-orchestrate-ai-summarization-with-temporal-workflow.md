# ADR-0003: Orchestrate AI document summarization with a Temporal workflow

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** @bastien-martin
**Technical Story:** docs/specs/ai-document-summarization.md

## Context

The new AI feature lets a user upload a French document and receive an English
summary produced by an LLM. The LLM call is slow, can fail transiently (rate
limits, timeouts, 5xx), and is part of a multi-step process (download → extract
text → summarize → persist). The codebase already runs a Temporal worker with a
workflow/activity pattern (`temporal/src/worker.py`,
`workflows/example/approval_workflow.py`, `activities/`). We need a reliable,
retryable, observable way to run this long task without blocking the request path.

## Decision

We orchestrate summarization as a **Temporal workflow** (`SummarizeDocumentWorkflow`)
started by a **Supabase Edge Function** (see ADR-0005), with the external LLM call
**isolated in a dedicated activity** (`summarize_with_claude`) that carries its own
retry policy and timeout. A `redact_personal_names` activity strips personal names
before summarization/persistence. Status is persisted in Supabase and surfaced to
the frontend via polling.

## Consequences

### Positive
- Durable execution with built-in retries/backoff for the flaky LLM call.
- Reuses the existing worker architecture and testing patterns.
- The LLM activity is independently unit-testable with a mocked client.

### Negative
- More moving parts than a single synchronous request handler.
- Requires status plumbing (DB row + polling endpoint) for the async result.

### Neutral
- Token streaming to the UI is deferred; v1 returns the final summary only.

## Options Considered

### Option 1: Temporal workflow + isolated activity (chosen)
- **Pros:** retries, durability, fits existing architecture, testable.
- **Cons:** async UX (polling); workflow/activity boilerplate.

### Option 2: Synchronous call in the API/edge function
- **Pros:** simplest path; immediate response.
- **Cons:** long request held open; no durable retries; poor resilience to LLM
  latency/outages; risks gateway timeouts.

### Option 3: Generic background job queue (e.g. Celery/RQ)
- **Pros:** decouples the long task.
- **Cons:** introduces a second orchestration system next to Temporal.

## Quality & Security (Non-Negotiable)

- **Tests required.** Workflow status transitions and each activity are unit-tested
  with mocked dependencies; default test runs make no network calls.
- **Resilience by construction.** The LLM activity has a bounded retry policy and a
  sized timeout; unrecoverable errors yield a clean `failed` status + retry path —
  never a hung request.
- **Redaction before processing.** `redact_personal_names` runs before the LLM call
  and before persistence; document content and secrets are never logged.
- **Least-privilege egress.** Only `summarize_with_claude` makes external network
  calls; all other activities stay inside the stack.

## Related Decisions

- ADR-0004 (Claude Sonnet 4.6 via Azure as the summarization provider).
- ADR-0005 (Supabase Edge Function as the orchestration entry point).

## Notes

Accepted: the spec's modeling/architecture decisions are resolved. Inputs are
capped at 512 KB; inputs above 128 KB use chunking + map-reduce summarization to
respect context limits (see spec). Output is final-only (no streaming) in v1.
