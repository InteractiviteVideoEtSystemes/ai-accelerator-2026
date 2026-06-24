# ADR-0005: Use a Supabase Edge Function as the summarization entry point

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** @bastien-martin
**Technical Story:** docs/specs/ai-document-summarization.md

## Context

The summarization feature needs a server-side entry point that the browser calls
after uploading a file to Supabase Storage. This entry point inserts the request
row and exposes status/results for polling. Two candidates existed: extend the
`ops-api` FastAPI bridge referenced by `charts/app`, or use a **Supabase Edge
Function**. The `ops-api` is not yet implemented, while Supabase (including Edge
Functions) is already part of the stack and owns auth, Storage, and the database
the feature uses.

A constraint shapes the design: Edge Functions run on **Deno**, which has no
production-grade Temporal client. The entry point therefore cannot itself start
the `SummarizeDocumentWorkflow`. The Temporal client lives in the Python worker,
so workflow start is delegated to a worker-side intake step (see Decision).

## Decision

We implement the entry point as a **Supabase Edge Function**
(`supabase/functions/summaries/`, Deno/TypeScript) exposing
create/get/list/retry operations under the Functions URL. The function uses the
Supabase client (parameterized queries, RLS-aware) and **only records the
request** (inserts/updates the `document_summaries` row, status `uploaded`). It
does **not** start the Temporal workflow.

Workflow start is handled by an **intake poller inside the Python worker** (which
owns the Temporal client). The poller atomically claims pending `uploaded` rows
(conditional PATCH on `workflow_id IS NULL`) and starts
`SummarizeDocumentWorkflow`. The `ops-api` FastAPI component is **not** used for
this feature.

## Consequences

### Positive
- Reuses Supabase's existing auth, RLS, and Storage context — no new service.
- Avoids standing up and operating the not-yet-implemented `ops-api`.
- Co-located with the database/Storage the feature reads and writes.

### Negative
- Edge Functions run on Deno/TypeScript, a different runtime from the Python
  worker — and Deno lacks a production Temporal client, so the function cannot
  start the workflow directly.
- Workflow start is therefore decoupled into a worker-side intake poller, which
  adds a small polling latency between request creation and workflow start.

### Neutral
- The workflow and activities remain unchanged regardless of entry point; the
  function only records the request and reads status, and the worker poller
  starts the workflow.

## Options Considered

### Option 1: Supabase Edge Function (chosen)
- **Pros:** no new service; native Supabase auth/RLS/Storage; quick to ship.
- **Cons:** Deno/TS runtime with no Temporal client, so workflow start is
  delegated to a worker-side intake poller.

### Option 2: ops-api (FastAPI) bridge
- **Pros:** Python (same as worker); one place for future ops endpoints.
- **Cons:** component not implemented yet; extra service to build/deploy/operate.

### Option 3: Call Temporal directly from the browser
- **Pros:** fewest hops.
- **Cons:** exposes Temporal to clients; no server-side auth/validation boundary.

## Quality & Security (Non-Negotiable)

- **Server-side validation is authoritative.** The function re-validates mime type
  and enforces the 512 KB cap regardless of client checks; invalid input is rejected
  with a clear, non-leaky error.
- **Parameterized, RLS-aware access only.** All DB access goes through the Supabase
  client (no string-concatenated SQL); rows respect RLS ownership.
- **No secrets to the client.** The service-role key is used server-side only and is
  never returned to the browser or logged.
- **Auth boundary preserved.** Clients never talk to Temporal directly; the function
  is the validated entry point.

## Related Decisions

- ADR-0003 (Temporal workflow this function starts).
- ADR-0004 (Claude Sonnet 4.6 via Azure used inside the workflow).

## Notes

Accepted per explicit user decision (entry point = Supabase Edge). Inputs are
validated server-side (allowed mime types, 512 KB cap) in addition to client-side
checks. Because Deno has no production Temporal client, the function records the
request only; a Python-worker intake poller starts the workflow (atomic claim on
`workflow_id IS NULL`). This local-first design runs entirely in Docker and calls
the Azure-hosted Claude model from the worker.
