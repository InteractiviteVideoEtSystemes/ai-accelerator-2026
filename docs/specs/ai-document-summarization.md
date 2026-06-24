# AI Document Summarization (French → English) Specification

**Status:** Draft
**Owner:** @bastien-martin
**Created:** 2026-06-24
**Last Updated:** 2026-06-24 (decisions resolved: Sonnet 4.6 via Azure, Edge Function entry point, 512 KB cap, 128 KB chunking, summary-only storage, name redaction)

## Overview

Add an AI feature to the local app that lets a user upload a French-language
document and receive an English summary produced by Anthropic's **Claude Sonnet 4.6**
model, accessed **via Azure** (Azure-hosted Claude endpoint).

The feature reuses the existing stack patterns: the document is uploaded to
Supabase Storage, a **Supabase Edge Function** is the request entry point that
records the summarization request, a **worker-side intake poller** (in the Python
Temporal worker, which owns the Temporal client) starts a Temporal workflow, and
the workflow runs the long-running LLM call
(text extraction → personal-name redaction → Claude summarization → persistence).
The JSON-driven frontend surfaces upload, progress, and the final English summary.
Only the **English summary** is persisted (the extracted source text is not stored).

## Goals

- Let a user upload a French document (PDF, DOCX, or TXT) from the frontend.
- Extract the document's text and summarize it into **English** using Claude
  **Sonnet 4.6** (accessed via Azure).
- Redact personal names (first names and surnames) so they do not appear in the
  stored/displayed summary.
- Run the summarization as a durable Temporal workflow (resilient to retries
  and transient API failures), consistent with the existing worker architecture.
- Persist **only the English summary** plus the source document reference and
  status the user can poll (the extracted source text is not stored).
- Keep the Azure/Claude credentials secret (never in the repo, injected via env/secret).
- Work end-to-end in the local stack (`make up`) before any cloud deployment.

## Non-Goals

- No translation of the *full* document (summary only, not a full translation).
- No multi-language support beyond French input / English output in v1.
- No fine-tuning or self-hosting of models; Claude is called via API.
- No production/cloud deployment as part of this spec (local app only).
- No authentication/authorization redesign; relies on the existing Supabase auth.
- No OCR for scanned/image-only PDFs in v1 (text-extractable documents only).
- No real-time streaming of summary tokens to the UI in v1 (final result only).

## Quality & Security (Non-Negotiable)

These requirements are **mandatory acceptance gates**: the feature does not ship,
and a PR is not mergeable, unless every item below holds. They are not "nice to
have" — they override scope/schedule pressure.

### Security (non-negotiable)
- **No secrets in the repo or client bundle.** `AZURE_CLAUDE_API_KEY` and the
  Supabase service-role key live only in env/`.env` (gitignored) locally and in
  Kubernetes secrets in-cluster. Never logged, never returned to the browser.
- **Server-side validation is authoritative.** The Edge Function re-validates mime
  type and enforces the **512 KB** cap regardless of client checks; empty/invalid
  inputs are rejected with a clear, non-leaky error.
- **Parameterized data access only.** No string-concatenated SQL; all DB access via
  the Supabase client / parameterized queries.
- **RLS enforced.** `document_summaries` and the `documents` Storage bucket are
  private; rows are accessible only to their `created_by` owner; the worker uses the
  service role server-side only.
- **No XSS / unsafe HTML injection.** The summary is rendered as text (escaped),
  never via `dangerouslySetInnerHTML` or raw HTML insertion.
- **Personal-name redaction is mandatory.** `redact_personal_names` runs **before**
  any LLM call and before persistence; names must not appear in stored or displayed
  summaries (defense-in-depth: redaction step **and** system-prompt instruction).
- **No document content in logs.** Logs are single-line and must never include the
  document text, the summary, or secrets.
- **Least privilege for egress.** Only the `summarize_with_claude` activity performs
  external (Azure) network I/O; all other activities stay inside the stack.

### Quality (non-negotiable)
- **Tests are required for every behavior change** (worker activities, workflow,
  Edge Function, frontend). No behavior ships untested.
- **Default test runs are offline** — the real Azure-Claude call is mocked and
  gated behind an env flag; CI never makes billable/network calls by default.
- **Resilience by construction.** The LLM call carries a bounded retry policy
  (backoff on `429`/`5xx`/timeout) and a sized timeout; failures surface a clean
  `failed` status + retry path, never a hung request.
- **Lint & build must pass** (`npm --prefix frontend run lint`, `... run build`,
  `python -m pytest temporal/tests`) before merge.
- **Backwards-compatible, additive changes.** New migration only (no edits to
  shipped migrations); snake_case, UUID PKs, `created_at`/`updated_at`.
- **Accessibility.** Upload, status, and result controls use semantic, keyboard-
  accessible HTML.
- **Input validation everywhere** (size, mime type, non-empty path) on both client
  and server.

## User Stories

### As a user, I want to upload a French document so that I can get an English summary

**Acceptance Criteria:**
- [ ] The UI exposes a document upload control accepting `.pdf`, `.docx`, `.txt`.
- [ ] Files above the size limit (**512 KB**) are rejected client-side with a clear message.
- [ ] On upload, the file is stored in Supabase Storage and a summarization request record is created.
- [ ] A Temporal workflow is started for the request (by the worker intake poller) and its ID is recorded.

### As a user, I want to see the status of my summary so that I know when it is ready

**Acceptance Criteria:**
- [ ] The UI shows status: `uploaded` → `extracting` → `summarizing` → `completed` (or `failed`).
- [ ] When completed, the English summary is displayed and can be copied.
- [ ] On failure, a non-technical error message is shown and the request can be retried.

### As a developer, I want the LLM call isolated in a Temporal activity so that it is retryable and testable

**Acceptance Criteria:**
- [ ] The Claude call lives in a dedicated activity with a typed input/output.
- [ ] The activity has a retry policy and a timeout suited to LLM latency.
- [ ] The activity can be unit-tested with a mocked Anthropic client (no network).

## Technical Design

### Architecture

```
Browser (JSON-driven UI engine)
  │ 1. Upload file → Supabase Storage (bucket: documents)
  │ 2. POST → Supabase Edge Function (summaries) ───────┐
  ▼                                                     ▼
Supabase Storage + Postgres                       Supabase Edge Function
  ▲  (document row, summary_request row)           │ 3. record request row
  │       ▲  (status=uploaded, workflow_id=NULL)    ▼     (status=uploaded)
  │       │                                   (returns to browser)
  │       │ 4. poll & atomically claim pending rows
  │  Temporal worker intake poller (Python) ──► 5. start SummarizeDocumentWorkflow
  │                                                 ▼
  │                                         Temporal server
  │                                                 │ 6. SummarizeDocumentWorkflow
  │                                                 ▼
  │                                         Temporal worker (Python)
  │   7. download file ◄──────────────────────────┤  activity: get_document_bytes
  │   8. extract text  (pypdf / python-docx)        │  activity: extract_text
  │   9. redact names  ───────────────────────────►│  activity: redact_personal_names
  │  10. summarize     ───────────────────────────►│  activity: summarize_with_claude → Claude Sonnet 4.6 via Azure
  └── 11. persist summary + status ◄───────────────┘  activity: save_summary (Supabase)
```

- **Frontend**: new page/components driven by the existing JSON UI engine; uses
  the Supabase JS client for the Storage upload and the Edge Function for
  request creation + status polling.
- **Supabase Edge Function**: the request entry point. A Deno/TypeScript
  Edge Function (`supabase/functions/summaries/`) inserts the request row
  (`status=uploaded`) and exposes status/results. It does **not** start the
  workflow (Deno has no production Temporal client). The `ops-api` FastAPI bridge
  is *not* used for this feature.
- **Worker intake poller**: an async poller inside the Python worker
  (`temporal/src/poller.py`) periodically claims pending `uploaded` rows (atomic
  conditional PATCH on `workflow_id IS NULL`) and starts
  `SummarizeDocumentWorkflow`, recording the `workflow_id`.
- **Temporal worker**: a new `SummarizeDocumentWorkflow` plus five activities. The
  Claude (Azure) call is the only external-network summarization activity and
  carries its own retry policy. A `redact_personal_names` step removes first names
  and surnames before summarization/persistence.
- **Supabase**: stores the document metadata, request/status, and the English
  summary only; Storage holds the uploaded bytes. The extracted source text is not
  persisted.

### Data Model

New migration (additive; `supabase/migrations/<timestamp>_ai_summaries.sql`),
snake_case, UUID PKs via `gen_random_uuid()`, `created_at`/`updated_at`:

`document_summaries`
| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` PK | `default gen_random_uuid()` |
| `storage_path` | `text` | Path in the `documents` Storage bucket |
| `original_filename` | `text` | As uploaded |
| `mime_type` | `text` | `application/pdf`, `...wordprocessingml...`, `text/plain` |
| `source_language` | `text` | Default `fr` |
| `target_language` | `text` | Default `en` |
| `status` | `text` | `uploaded`/`extracting`/`summarizing`/`completed`/`failed` |
| `workflow_id` | `text` | Temporal workflow id (nullable until started) |
| `extracted_char_count` | `int` | Optional, for observability |
| `summary` | `text` | English summary (nullable until completed) |
| `error_message` | `text` | Populated on failure |
| `created_by` | `uuid` | Supabase auth user id (nullable) |
| `created_at` / `updated_at` | `timestamptz` | `default now()` |

- A Storage bucket `documents` (private) is created/configured for uploads.
- Optionally also append an `entity_events`-style row per status change to reuse
  the existing event-sourcing pattern (consistent with `supabase_core.append_event`).
- RLS: rows are readable/writable by their `created_by` owner (and service role
  used by the worker). Worker writes use the service-role key.

### API Design

Supabase Edge Function (`supabase/functions/summaries/`, Deno/TypeScript), exposed
under the Functions URL (e.g. `/functions/v1/summaries`):

- `POST /functions/v1/summaries`
  - Request: `{ "storage_path": str, "original_filename": str, "mime_type": str, "size_bytes": int }`
    (the browser uploads to Storage first, then sends the path)
  - Behavior: inserts a `document_summaries` row (`status=uploaded`,
    `workflow_id=NULL`). It does **not** start the workflow; the worker intake
    poller claims the row and starts `SummarizeDocumentWorkflow`.
  - Response: `201 { "id": uuid, "status": "uploaded" }`
- `GET /functions/v1/summaries/{id}`
  - Response: `200 { id, status, summary?, error_message?, ... }`
- `GET /functions/v1/summaries`
  - Response: list of the caller's summaries (most recent first).
- `POST /functions/v1/summaries/{id}/retry`
  - Resets a `failed` request to `uploaded` (clears `workflow_id`) so the intake
    poller re-claims and re-runs it.

Validation: enforce allowed `mime_type`, reject inputs over **512 KB** (also
enforced client-side), reject empty `storage_path`. The function uses the Supabase
client with parameterized queries (no string-concatenated SQL).

### Temporal workflow & activities

- Workflow: `SummarizeDocumentWorkflow(request_id, storage_path, mime_type)`
  1. `set status=extracting`
  2. `bytes = get_document_bytes(storage_path)`
  3. `text = extract_text(bytes, mime_type)` (pypdf / python-docx / utf-8 decode)
     - Reject inputs whose decoded text exceeds the **512 KB** cap → `failed`.
  4. `text = redact_personal_names(text)` — strip first names and surnames before
     any LLM call or persistence.
  5. `set status=summarizing`
  6. `summary = summarize_with_claude(text, source="fr", target="en")`
     - For inputs **larger than 128 KB**: chunk text and map-reduce (summarize
       chunks, then summarize the combined chunk-summaries) to respect context limits.
  7. `save_summary(request_id, summary)` → `set status=completed`
     - Persist **only** the English summary (not the extracted/redacted source text).
  - On unrecoverable error: `set status=failed` with `error_message`.
- `redact_personal_names` activity:
  - Removes person first names and surnames (e.g. via a named-entity pass /
    deterministic redaction) so they never reach the model output or storage.
- `summarize_with_claude` activity:
  - Calls **Claude Sonnet 4.6 via Azure** (Azure-hosted Claude endpoint), configured by
    endpoint + deployment + key (see Configuration).
  - System prompt instructs: "You are a translator-summarizer. The user provides
    French text. Produce a concise, faithful summary in English. Do not include any
    personal names (first names or surnames)." Output English only.
  - Retry policy: exponential backoff, retry on `429`/`5xx`/timeouts; bounded
    maximum attempts; `start_to_close_timeout` sized for LLM latency (e.g. 120s).

### Configuration / Secrets

Add to the worker settings (`temporal/src/config.py`, pydantic), reusing the
verified Azure AI Foundry `AZURE_AI_*` block:
- `azure_ai_inference_endpoint` (env `AZURE_AI_INFERENCE_ENDPOINT`) — Azure AI Foundry URL.
- `azure_ai_api_key` (env `AZURE_AI_API_KEY`) — **secret**, never committed.
- `azure_ai_summary_deployment` (env `AZURE_AI_SUMMARY_DEPLOYMENT`, default the verified **Sonnet 4.6** deployment `claude-sonnet-4-6`).
- `azure_anthropic_api_version` (env `AZURE_ANTHROPIC_API_VERSION`, default `2025-04-01-preview`).
- `summarization_max_input_bytes` (default `524288` = 512 KB) — hard input cap.
- `summarization_chunk_threshold_bytes` (default `131072` = 128 KB) — chunk above this.

Local: add the `AZURE_AI_*` values to `.env` (already gitignored) and reference
them in `docker-compose.yml` worker env. For future cloud: a Kubernetes secret
mirroring the existing `temporal-worker-secrets` pattern (out of scope to deploy here).

### UI/UX Design

Accessing the feature requires **three** pieces (the UI engine drives page
*content*, but routing and the nav menu are conventional React/TanStack):

1. **JSON page** (engine-driven content): `frontend/src/pages/ai-summarize.json`
   — upload dropzone (accept pdf/docx/txt), a status indicator (`EngineAlert`),
   and a result panel (`EngineCard` + `Text`) with a "Copy" button. Reuse existing
   engine component patterns; semantic, keyboard-accessible controls.
2. **Route** (TanStack file-based router): a thin wrapper, e.g.
   `frontend/src/routes/tools/summarize.tsx` → URL `/tools/summarize`, that renders
   `<UIEngine page={aiSummarizePage} />` (mirrors `routes/index.tsx` /
   `routes/entities/$entityType/index.tsx`).
3. **Navigation entry**: the sidebar in `frontend/src/routes/__root.tsx` is
   **hardcoded React (not JSON-driven)**, so a `<Link to="/tools/summarize">` must
   be added there (e.g. under a new "AI Summarizing" section). This is a code change to
   `__root.tsx`, not a JSON edit.

- Flow: select file → upload to Storage → call `POST /functions/v1/summaries` →
  poll `GET /functions/v1/summaries/{id}` until `completed`/`failed` → render summary.

## Implementation Plan

### Phase 1: Backend foundation
- [x] Migration: `document_summaries` table + `documents` Storage bucket + RLS.
- [x] Add httpx + parser dependencies to `temporal/pyproject.toml`; add settings.
- [x] Implement activities: `extract_text`, `redact_personal_names`,
      `summarize_with_claude`, `save_summary`, status/failure helpers (real, not stubbed).
- [x] Implement `SummarizeDocumentWorkflow`; register workflow + activities in
      `worker.py`. Add the intake poller (`poller.py`) that starts the workflow.

### Phase 2: API + orchestration
- [x] Implement the Supabase Edge Function `supabase/functions/summaries/`
      (create/get/list/retry) recording the request row (workflow started by the poller).
- [x] Wire `AZURE_AI_*` env (reusing the verified Azure AI Foundry block:
      `AZURE_AI_INFERENCE_ENDPOINT`, `AZURE_AI_API_KEY`, `AZURE_ANTHROPIC_API_VERSION`,
      `AZURE_AI_SUMMARY_DEPLOYMENT`) into local `docker-compose.yml` worker env.

### Phase 3: Frontend
- [x] Add the JSON page `pages/ai-summarize.json` (upload, status, result) via the UI engine.
- [x] Add the route `routes/tools/summarize.tsx` rendering it through `<UIEngine>`.
- [x] Add a sidebar nav link in `routes/__root.tsx` ("AI Summarizing" section).
- [x] Implement Storage upload + Edge Function calls + status polling (`AiSummarizer`).

### Phase 4: Hardening
- [x] Chunking/map-reduce for inputs above the 128 KB threshold.
- [x] Error states, retry button, 512 KB size + type validation messaging.

## Testing Strategy

- **Unit (worker)**: `temporal/tests` — `extract_text` for pdf/docx/txt fixtures;
  `redact_personal_names` (names removed, non-names preserved);
  `summarize_with_claude` with a mocked Azure-Claude client (no network); workflow
  logic with mocked activities (status transitions, failure → `failed`).
- **Unit (Edge Function)**: endpoint validation, request row creation, 512 KB
  rejection, status mapping (the function records the request; it does not start
  the workflow).
- **Unit (poller)**: atomic claim of `uploaded` rows and workflow start (mocked
  Temporal client / REST client).
- **Frontend**: component tests for upload validation, status rendering, and
  result display (focused tests over snapshots, per repo guidelines).
- **Integration/E2E**: against the local stack (`make up`) — upload a sample
  French PDF and assert an English summary is produced and persisted. Gate any
  test that performs a real Azure-Claude call behind an env flag/key so default CI
  runs stay offline (mocked).
- **No network calls in default tests** (per Temporal worker guidelines).

## Rollout Plan

- Local-only for this spec: validated via `make up` and `supabase db reset`.
- Feature-flagged (`AI_SUMMARIZATION_ENABLED`) so it can ship dark.
- Cloud deployment (AKS/Helm secret for `AZURE_CLAUDE_API_KEY`) is explicitly a
  later, separate effort — not part of this spec.

## Metrics & Success Criteria

- ≥95% of valid French uploads produce an English summary without manual retry.
- Median end-to-end time within an agreed target (e.g. < 30s for a ≤5-page doc).
- LLM activity error rate (post-retry) below an agreed threshold.
- No secrets committed; Azure/Claude key sourced only from env/secret.
- No personal names (first names/surnames) appear in stored/displayed summaries.

## Dependencies

- Azure-hosted Claude (Sonnet 4.6) access + `AZURE_AI_*` config (billable service).
- Azure-Claude client SDK; `pypdf` and `python-docx` for text extraction; a
  named-entity/redaction mechanism for `redact_personal_names`.
- Existing Supabase (Postgres + Storage + Edge Functions) and Temporal server in
  the local stack.

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Large documents exceed Claude context window | Medium | Medium | 512 KB hard cap; chunk + map-reduce above 128 KB |
| Azure-Claude latency/rate limits/outages | Medium | Medium | Temporal retries with backoff; clear `failed` status + retry endpoint |
| Scanned/image PDFs yield no extractable text | Medium | Medium | Detect empty extraction → fail with guidance; OCR out of scope v1 |
| Key leakage | High | Low | Env/secret only; gitignored `.env`; never logged; not in client bundle |
| Cost from large/abundant requests | Medium | Medium | 512 KB size cap; optional per-user quotas (future) |
| Summary quality / hallucination | Medium | Medium | Constrained system prompt; show source link; mark as AI-generated |
| Personal names leak into summary | Medium | Low | `redact_personal_names` step + system-prompt instruction to omit names |

## Resolved Decisions

- **Model:** Claude **Sonnet 4.6** (quality tier; verified `claude-sonnet-4-6` deployment).
- **Provider access:** **via Azure** (Azure-hosted Claude endpoint), not direct Anthropic.
- **Orchestration entry point:** **Supabase Edge Function** records the request
  (not the ops-api); the **Python worker intake poller** starts the workflow,
  because Deno has no production Temporal client.
- **Runtime:** **local-first** — the entire stack runs in Docker (`make up`); only
  the Claude model call reaches out to the Azure-hosted endpoint.
- **Storage:** persist **only the English summary** (extracted source text is not stored).
- **Max input size:** **512 KB** (rejected above this, client- and server-side).
- **Chunking threshold:** chunk/map-reduce for inputs **above 128 KB**.
- **Output mode:** **final result only** (no token streaming in v1).
- **PII:** no sensitive data expected, but **personal names (first/last) are redacted**
  before summarization and persistence.

## Open Questions

All prior modeling/architecture questions are resolved (see **Resolved
Decisions**). Remaining:

- [x] Exact Azure-hosted Claude deployment name / version to target — **resolved:**
      `claude-sonnet-4-6` (verified Azure AI Foundry deployment).
- [ ] Which redaction mechanism for `redact_personal_names` (NER library vs the
      model itself) best balances precision/recall for FR names.
- [ ] Data-retention / deletion policy for the **uploaded source files** in Storage
      (the summary-only persistence is decided; bytes retention is not).

## References

- `SPEC_TEMPLATE.md` (template for this document)
- `README.md`, `DATABASE.md`, `Guide_for_agents_using_supabase_template.md`
- `temporal/src/worker.py`, `temporal/src/activities/`, `temporal/src/workflows/example/approval_workflow.py`
- `frontend/src/engine/`, `frontend/src/data/supabase.ts`, `supabase/functions/` (Edge Functions)
- `docs/adrs/0003-*`, `docs/adrs/0004-*`, `docs/adrs/0005-*` (related decisions)
- Anthropic API docs: https://docs.anthropic.com
