# AI Summarizing ODT File Support Specification

**Status:** Approved  
**Owner:** @bastien-martin  
**Created:** 2026-06-24  
**Last Updated:** 2026-06-24

## Overview

The existing AI document summarization feature supports uploading PDF, DOCX, and
TXT files. Issue #1 asks for the same summarization result when a user works with
OpenOffice/OpenDocument text documents (`.odt`) instead of Microsoft Word
documents (`.docx`).

This spec extends the existing upload, validation, and text-extraction pipeline
to accept `.odt` files while preserving the current summarization behavior:
Supabase Storage upload, Edge Function request creation, Temporal workflow
processing, personal-name redaction, Claude summarization, and English summary
display.

## Goals

- Let users upload `.odt` OpenDocument text files through the existing AI
  summarization UI.
- Treat ODT documents as first-class supported inputs alongside PDF, DOCX, and
  TXT.
- Enforce the existing 512 KB file-size limit for ODT at the client, Edge
  Function, and worker extraction layers.
- Extract readable text from ODT files and feed it into the existing redaction
  and summarization flow.
- Preserve all existing PDF, DOCX, and TXT behavior.
- Add meaningful tests for ODT acceptance, ODT payload contracts, ODT Edge
  Function validation, and ODT text extraction.

## Non-Goals

- No support for non-text OpenDocument formats such as `.ods`, `.odp`, or `.ott`.
- No OCR for scanned/image-only documents.
- No changes to the summarization model, prompt, language pair, redaction rules,
  retry policy, or summary persistence behavior.
- No increase to the 512 KB input size limit.
- No full-document translation; the feature remains summary-only.
- No redesign of the upload UI beyond adding ODT as an accepted file type.
- No update to the original `docs/specs/ai-document-summarization.md` spec as
  part of this ODT-support change.

## User Stories

### As a user with OpenOffice documents, I want to upload an ODT file so that I can receive the same English summary I get for DOCX files

**Acceptance Criteria:**
- [ ] The AI summarization file input accepts `.odt` files.
- [ ] The frontend accepts ODT files even when the browser reports an empty or
      generic MIME type, as long as the filename ends with `.odt`.
- [ ] The UI label and unsupported-file error mention ODT as a supported format.
- [ ] Selecting a valid `.odt` file under 512 KB enables the Summarize action.
- [ ] Uploading an ODT file stores it in Supabase Storage with its original file
      name and content type.
- [ ] The create-summary request sends the ODT MIME type and file size to the
      `summaries` Edge Function.
- [ ] The summarization workflow extracts text from the ODT file and continues
      through the existing `uploaded -> extracting -> summarizing -> completed`
      flow.
- [ ] The final result is an English summary rendered through the existing result
      UI.

### As a developer, I want ODT support to reuse the existing summarization pipeline so that the change stays small and safe

**Acceptance Criteria:**
- [ ] ODT is added to the existing allowed MIME type lists instead of creating a
      separate ODT-specific endpoint or workflow.
- [ ] The worker text extraction helper handles ODT by MIME type and by `.odt`
      filename extension fallback.
- [ ] Malformed or unsupported ODT input fails with a clear non-retryable
      extraction error, consistent with malformed DOCX/PDF handling.
- [ ] Existing tests for PDF, DOCX, and TXT continue to pass unchanged.

## Technical Design

### Architecture

Reuse the existing AI document summarization architecture described in
`docs/specs/ai-document-summarization.md`.

The ODT path should follow the same path as DOCX:

```text
Browser file input
  -> Supabase Storage upload
  -> POST /functions/v1/summaries
  -> document_summaries row with mime_type=application/vnd.oasis.opendocument.text
  -> Temporal worker intake poller
  -> SummarizeDocumentWorkflow
  -> extract_text activity
  -> redact_personal_names
  -> summarize_with_claude
  -> save_summary
  -> frontend polling/result display
```

Expected touched surfaces:

- `frontend/src/components/engine/ai/AiSummarizer.tsx`
- `frontend/src/components/engine/ai/AiSummarizer.test.tsx`
- `supabase/functions/summaries/router.ts`
- `supabase/functions/summaries/router.test.ts`
- `temporal/src/activities/summarization.py`
- `temporal/tests/test_extract_text.py`
- Inline comments or user-facing strings touched by the implementation if they
  enumerate supported file types.

### Data Model

No schema change is expected.

The existing `document_summaries.mime_type` field should store:

```text
application/vnd.oasis.opendocument.text
```

for ODT uploads. Existing status, summary, error, and workflow fields remain
unchanged.

### API Design

Extend `supabase/functions/summaries/router.ts` so `ALLOWED_MIME_TYPES` includes:

```text
application/vnd.oasis.opendocument.text
```

The existing create request contract remains unchanged:

```json
{
  "storage_path": "uuid/document.odt",
  "original_filename": "document.odt",
  "mime_type": "application/vnd.oasis.opendocument.text",
  "size_bytes": 12345
}
```

The Edge Function should continue to reject:

- missing or empty `storage_path`,
- missing `original_filename`,
- unsupported MIME types,
- missing, non-numeric, negative, or over-limit `size_bytes`.

No new endpoint is required.

### UI/UX Design

Update the existing `AiSummarizer` component:

- Add ODT to the `ALLOWED` map.
- Add `.odt` to the file input `accept` attribute.
- Update the file label from `PDF, DOCX, or TXT` to include `ODT`.
- Update the unsupported-file error to include `ODT`.
- Accept files whose browser-reported MIME type is empty or generic when the
  filename ends with `.odt`; when this fallback is used, send the canonical ODT
  MIME type to Storage and the Edge Function.

No new screen or workflow is required. The status badge, retry behavior, copy
button, and summary display remain unchanged.

### Worker Text Extraction

Add ODT extraction to `temporal/src/activities/summarization.py`.

Preferred implementation: use Python standard library ZIP/XML parsing rather
than adding a new runtime dependency unless implementation proves a dependency is
necessary.

ODT extraction should:

- Recognize MIME type `application/vnd.oasis.opendocument.text`.
- Also route by `.odt` filename extension when MIME type is generic or missing.
- Open the ODT as a ZIP archive.
- Read `content.xml`.
- Extract human-readable text from text paragraph/heading elements.
- Preserve paragraph boundaries with newline separators.
- Ignore metadata and style definitions.
- Raise an error for malformed ZIP/XML or missing extractable content so the
  existing activity can mark the request failed cleanly.

The existing `extract_text` Temporal activity already enforces raw byte and
decoded text size caps; ODT must remain subject to those caps.

## Implementation Plan

### Phase 1: Frontend ODT acceptance
- [ ] Add `application/vnd.oasis.opendocument.text` to `ALLOWED` in
      `AiSummarizer.tsx`.
- [ ] Add `.odt` to the input `accept` list.
- [ ] Add filename-extension fallback so `.odt` files with empty or generic
      browser MIME types are accepted and normalized to
      `application/vnd.oasis.opendocument.text`.
- [ ] Update UI label and unsupported-file error text to mention ODT.
- [ ] Add or update frontend tests proving ODT files are accepted and included in
      the upload/create request payload with the correct MIME type.

### Phase 2: Edge Function ODT validation
- [ ] Add the ODT MIME type to `ALLOWED_MIME_TYPES` in
      `supabase/functions/summaries/router.ts`.
- [ ] Add router tests proving ODT payloads are accepted and inserted with the
      correct `mime_type`.
- [ ] Keep existing unsupported MIME and size validation behavior unchanged.

### Phase 3: Worker ODT extraction
- [ ] Add ODT MIME constant and extraction branch in
      `temporal/src/activities/summarization.py`.
- [ ] Implement ODT text extraction from `content.xml`.
- [ ] Add tests that build a minimal ODT fixture in memory and assert paragraph
      text extraction.
- [ ] Add tests for `.odt` extension fallback when MIME type is generic.
- [ ] Add tests for malformed ODT input raising a clear extraction error.

### Phase 4: Comments and validation
- [ ] Update touched inline comments or user-facing strings that enumerate
      supported summarization file types.
- [ ] Do not update the original `docs/specs/ai-document-summarization.md` spec.
- [ ] Run relevant frontend, Edge Function, and Temporal tests.
- [ ] Confirm existing PDF, DOCX, and TXT tests still pass.

## Testing Strategy

- Frontend unit tests:
  - ODT file selection under 512 KB enables the Summarize button.
  - `.odt` file selection works when the browser reports an empty or generic
    MIME type, and the request is normalized to
    `application/vnd.oasis.opendocument.text`.
  - ODT upload sends Storage `contentType` as
    `application/vnd.oasis.opendocument.text`.
  - ODT create request sends `storage_path`, `original_filename`, `mime_type`,
    and `size_bytes`.
  - Unsupported file error lists supported types including ODT.
- Edge Function tests:
  - `POST /summaries` accepts ODT MIME type and inserts the full row.
  - Existing rejection tests still reject unsupported MIME types and invalid
    sizes.
- Temporal worker tests:
  - Minimal ODT document extracts expected paragraph text.
  - ODT extraction works when MIME type is generic but filename ends with `.odt`.
  - Malformed ODT raises instead of silently returning empty text.
  - Existing PDF, DOCX, and TXT extraction tests still pass.
- Validation commands:
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run build`
  - `npm --prefix frontend test -- --run`
  - `python -m pytest temporal/tests`
  - If Deno is available: `deno test supabase/functions/summaries/router.test.ts`

## Rollout Plan

This is a backward-compatible additive change. Deploy with the normal application
release path after tests pass. Existing uploaded PDF, DOCX, and TXT summaries are
unaffected because no schema, status, or API response changes are required.

Rollback is straightforward: remove ODT from allowed MIME lists and the worker
extractor branch. Existing non-ODT behavior should continue to work.

## Metrics & Success Criteria

- A valid ODT file under 512 KB can be uploaded from the frontend.
- The Edge Function accepts ODT create requests and persists the ODT MIME type.
- The worker extracts ODT text and completes the existing summarization workflow.
- Existing PDF, DOCX, and TXT tests continue to pass.
- No document contents, summaries, or secrets are logged.

## Dependencies

- Existing AI summarization feature and `document_summaries` table.
- Existing Supabase Storage `documents` bucket.
- Existing Temporal worker and `SummarizeDocumentWorkflow`.
- Existing frontend test setup and Temporal pytest suite.
- Optional: no new parser dependency is expected if standard library ZIP/XML
  extraction is sufficient.

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| ODT files can contain complex formatting that simple XML extraction may flatten. | Summaries may omit formatting nuance. | Medium | Extract paragraph/heading text only and document that summarization uses readable text content, not layout fidelity. |
| Browser-provided MIME type may be generic for some ODT files. | Valid ODT files may be rejected client-side or server-side. | Medium | Support `.odt` extension fallback in the worker and consider frontend tests for the expected browser MIME; keep server authoritative on known ODT MIME. |
| Malformed ODT files may raise parser errors. | User sees failed summary request. | Medium | Convert unsupported/malformed extraction into clear non-retryable failure, consistent with malformed DOCX/PDF behavior. |
| ODT support could regress existing file types. | Existing summarization users are affected. | Low | Keep changes additive and run existing PDF/DOCX/TXT tests. |

## Open Questions

None.

## References

- GitHub issue: https://github.com/InteractiviteVideoEtSystemes/ai-accelerator-2026/issues/1
- Existing feature spec: `docs/specs/ai-document-summarization.md`
- Frontend component: `frontend/src/components/engine/ai/AiSummarizer.tsx`
- Edge Function router: `supabase/functions/summaries/router.ts`
- Worker extraction helper: `temporal/src/activities/summarization.py`
