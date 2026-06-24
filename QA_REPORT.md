# AI Summarizing QA Report

Date: 2026-06-24
Target: `http://localhost:3000/tools/summarize`
Role: QA tester looking for missing edge cases and breakage paths.

## Executive summary

The core happy path works: a small French `.txt` document uploaded through the UI completed successfully and produced an English summary that did not include the title-prefixed source name `Monsieur Jean Dupont`. The summary rendering is also XSS-safe in the tested path: mocked HTML/script content was displayed as text and did not execute.

The largest risks are in the public Edge Function contract, not the React rendering. A browser-visible anon key can create summary jobs for nonexistent storage paths and list summary rows, including the `summary` field, because the function uses a service-role client without binding rows to a caller. There are also several UX/state edge cases that can leave users stuck, misled, or without a retry path.

## Test coverage performed

| Area | Result |
| --- | --- |
| Page load | `GET /tools/summarize` returned 200 and rendered the upload UI. |
| Happy path | Small French `.txt` completed and rendered an English summary. |
| Name redaction smoke | The live summary did not include `Jean`, `Dupont`, or `Monsieur`. |
| Client validation | Exercised unsupported MIME, oversize, exact-size boundary, empty file, blank MIME, and extension/MIME mismatch. |
| Direct API probing | Exercised `/functions/v1/summaries` with the public anon key, without a user session. |
| Mocked rare backend states | Forced XSS summary, poll 500s, failed-without-message, completed-with-empty-summary, and stale state after changing files. |

## Positive findings

1. Unsupported `image/png` was rejected client-side with `Unsupported file type. Use a PDF, DOCX, or TXT document.`
2. A `text/plain` file of `512 KB + 1 byte` was rejected client-side with `File is larger than the 512 KB limit.`
3. A `text/plain` file exactly at `512 KB` was accepted, matching the documented cap.
4. The live happy path completed and produced English output.
5. The summary output is rendered as escaped text. A mocked summary containing `<img onerror=...>` and `<script>...` did not create DOM `img`/`script` nodes and did not set the injected JavaScript flag.

## Findings

### 1. High: public anon key can create and list summary records

**Evidence**

- A direct `POST http://localhost:54321/functions/v1/summaries` using only the browser-visible anon key returned `201` for a fake, nonexistent storage path.
- A direct `GET http://localhost:54321/functions/v1/summaries` using the same anon key returned the created probe in the list.
- The list response fields included `summary`, `error_message`, `original_filename`, and timestamps.
- Code path: `supabase/functions/summaries/router.ts` inserts with the service-role client and no `created_by` assignment, then `handleList` and `handleGetOne` read rows without caller filtering.

**Impact**

Any client that can read the public frontend bundle can use the anon key to create jobs and list available summary records. If real summaries contain sensitive business content, this becomes a data exposure issue. It also lets a client create junk jobs without using the UI.

**Expected**

Rows should be scoped to an authenticated caller or to a server-issued anonymous session. List/get endpoints should only return rows owned by the caller, and direct public callers should not be able to enumerate all summaries.

**Recommended fix**

- Authenticate requests at the Edge Function and derive `created_by` from the verified JWT.
- Insert `created_by` on create.
- Filter `GET /summaries` and `GET /summaries/{id}` by caller.
- Avoid returning `summary` in list responses unless the caller is authorized.
- Add tests proving one caller cannot read another caller's row.

### 2. High: Edge Function accepts nonexistent or arbitrary storage paths

**Evidence**

- The public create request accepted `storage_path = qa/nonexistent/...` and returned `status = uploaded`.
- The worker later marked it failed after trying to download the nonexistent object.
- The exposed `error_message` included an internal local URL: `http://host.docker.internal:54321/storage/v1/object/documents/...`.
- Code path: `handleCreate` validates only non-empty `storage_path`, MIME type, and the caller-provided `size_bytes`; it does not verify object existence, object owner, object metadata, extension, or actual size.

**Impact**

A caller can enqueue work for arbitrary paths and create noisy failed workflows. The returned failure details leak internal topology (`host.docker.internal`) and backend implementation details. If storage paths ever overlap with other users' objects, this pattern could become an authorization boundary problem.

**Expected**

The server should only create a summary request for a verified object in the expected private bucket and owned by the caller/session.

**Recommended fix**

- Check Storage metadata server-side before inserting the request.
- Reject paths with traversal-like segments, unexpected prefixes, or missing objects.
- Compare actual object size/content type with the submitted metadata.
- Return a generic failure message to the browser and log detailed backend errors server-side only.

### 3. Medium: polling errors can leave the UI stuck forever

**Evidence**

- Mocked flow: `POST /summaries` returned `status = summarizing`; every `GET /summaries/{id}` returned 500.
- After 6.5 seconds and two failed polls, the UI still showed `Working... Summarizing`; the file input and submit button remained disabled.
- Code path: `AiSummarizer.tsx` silently returns on non-OK poll responses and silently catches polling exceptions.

**Impact**

A transient or persistent status endpoint outage can trap the user in an active state with no visible error, no cancel button, and no retry path.

**Expected**

After bounded retries or elapsed time, the UI should show a recoverable error and let the user retry, cancel, or select another file.

**Recommended fix**

- Track consecutive poll failures.
- Use bounded retries/backoff and a maximum elapsed time.
- Surface a non-technical "Could not refresh status" message.
- Re-enable controls or provide a cancel/retry action.

### 4. Medium: failed status without `error_message` hides the retry control

**Evidence**

- Mocked `GET /summaries/{id}` returned `{ id, status: "failed" }`.
- The UI showed only the `Failed` badge. It did not show `Summarization failed` and did not show `Retry`.
- Code path: the failure alert and retry button render only when `status === "failed" && record?.error_message`.

**Impact**

If the backend ever writes `failed` with a null/empty error message, the user loses the retry affordance and receives no actionable explanation.

**Expected**

Every failed status should show a generic failure message and a retry button, even if the backend omitted details.

**Recommended fix**

Render the failed alert whenever `status === "failed"`, using a generic fallback message when `error_message` is empty.

### 5. Medium: empty files are accepted by the UI and fail later with a technical message

**Evidence**

- A zero-byte `empty.txt` was accepted client-side and enabled the `Summarize` button.
- Live submission failed after about 6 seconds with: `No extractable text found (scanned/image documents are not supported)`.

**Impact**

Users can submit obviously invalid input and wait for the workflow to fail. The error is understandable to developers, but it is still a backend extraction detail rather than a client-side validation message.

**Expected**

Empty files should be rejected immediately. Whitespace-only text files should also be considered for rejection before creating a workflow.

**Recommended fix**

- Reject `selected.size === 0` client-side.
- In the worker, keep the authoritative extracted-text check.
- Return/display a user-friendly message such as "The document does not contain readable text."

### 6. Medium: client and API trust caller-provided MIME/filename metadata too much

**Evidence**

- A synthetic browser file named `payload.exe` with MIME `text/plain` was accepted by the UI and enabled `Summarize`.
- A `.txt` file with blank MIME was rejected, even though the extension was valid.
- The Edge Function accepts any `original_filename` as long as `mime_type` is one of the allow-listed values.

**Impact**

The UI can reject valid files on platforms that provide blank MIME types, while accepting misleading filenames if the MIME value is manipulated. The server trusts browser-supplied metadata and does not prove that the uploaded object really matches it.

**Expected**

Client checks should be helpful but not authoritative. Server checks should validate the actual stored object metadata/content, not just the submitted JSON fields.

**Recommended fix**

- Client: allow extension fallback for valid `.pdf`, `.docx`, and `.txt` when `File.type` is blank.
- Server: verify actual Storage metadata and reject extension/MIME mismatches.
- Worker: avoid filename-overrides-MIME behavior unless it has already been server-normalized.

### 7. Low: changing files after completion leaves the old summary visible

**Evidence**

- Mocked flow completed with a visible summary.
- Selecting `second.txt` changed the selected filename but left the previous `Completed` badge and summary visible.

**Impact**

The user can see a new filename next to an old summary and mistakenly believe the summary belongs to the newly selected file.

**Expected**

Changing the selected file should clear the prior record, copied state, and visible summary.

**Recommended fix**

In `onFileChange`, clear `record` and `copied` whenever the selected file changes.

### 8. Low: completed status with an empty summary gives no useful output

**Evidence**

- Mocked `GET /summaries/{id}` returned `{ id, status: "completed", summary: "" }`.
- The UI showed `Completed` but no copy button, no summary block, and no error.

**Impact**

The user sees a successful terminal state with no result and no explanation.

**Expected**

An empty completed summary should be treated as an invalid backend response or displayed with a clear fallback message.

**Recommended fix**

If `status === "completed"` and `summary` is empty, render an error/fallback state and log/report the bad backend response.

### 9. Low: retry request failures are swallowed

**Evidence**

- Code path: `onRetry` returns silently when the retry response is not OK and catches exceptions without setting `clientError`.

**Impact**

If retry fails because of a network/API problem, the user receives no feedback.

**Expected**

Retry failures should show a recoverable, non-technical error message.

**Recommended fix**

Set `clientError` on non-OK retry responses and exceptions, and keep the Retry button visible.

### 10. Low: progress changes are not announced to assistive tech

**Evidence**

- The status badge changes visually, but there is no `role="status"`/`aria-live` region around the queued/extracting/summarizing/completed state.

**Impact**

Screen-reader users may not be notified that a long-running job changed state or completed.

**Expected**

Progress and terminal states should be announced through a polite live region.

**Recommended fix**

Wrap status updates in an accessible live region, for example `role="status" aria-live="polite"`.

## Reproduction notes

### Live happy path

1. Open `http://localhost:3000/tools/summarize`.
2. Upload a small French text file containing `Monsieur Jean Dupont`.
3. Click `Summarize`.
4. Observe `Completed` and an English summary that omits the original personal name.

### Public API create/list probe

1. Use the frontend anon key as `apikey` and `Authorization: Bearer <anon key>`.
2. `POST /functions/v1/summaries` with:

```json
{
  "storage_path": "qa/nonexistent/probe.txt",
  "original_filename": "probe.txt",
  "mime_type": "text/plain",
  "size_bytes": 1
}
```

3. Observe `201` and `status = uploaded`.
4. `GET /functions/v1/summaries` with the same public key.
5. Observe that the created row is listed and that list fields include `summary` and `error_message`.

### UI polling hang probe

1. Mock Storage upload as 200.
2. Mock `POST /summaries` as `201 { "id": "mock", "status": "summarizing" }`.
3. Mock every `GET /summaries/mock` as HTTP 500.
4. Observe that the UI remains on `Working... Summarizing` with controls disabled and no error.

## Priority recommendations

1. Fix the Edge Function authorization/data isolation first: bind rows to callers, filter reads, and avoid public enumeration.
2. Verify Storage object existence, ownership, actual size, and content type before creating a summary job.
3. Add bounded polling failure handling and always provide a retry/cancel path.
4. Harden client validation for empty files, blank MIME valid extensions, and stale-state clearing.
5. Add regression tests for the failed-without-message, poll-error, empty-summary, stale-summary, and public API authorization cases.
