-- AI document summarization feature
-- Created: 2026-06-24
-- Purpose: store French->English summarization requests, their status, and the
--          final English summary. Only the summary is persisted (not the source
--          text). Backs the SummarizeDocumentWorkflow Temporal workflow and the
--          `summaries` Supabase Edge Function. See docs/specs/ai-document-summarization.md

-- Status lifecycle: uploaded -> extracting -> summarizing -> completed | failed
create table if not exists document_summaries (
  id uuid primary key default gen_random_uuid(),
  storage_path text not null,
  original_filename text not null,
  mime_type text not null,
  source_language text not null default 'fr',
  target_language text not null default 'en',
  status text not null default 'uploaded'
    check (status in ('uploaded', 'extracting', 'summarizing', 'completed', 'failed')),
  workflow_id text,
  extracted_char_count int,
  summary text,
  error_message text,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_document_summaries_status on document_summaries (status);
create index if not exists idx_document_summaries_created_at on document_summaries (created_at desc);

-- Reuse the shared updated_at trigger defined in the core migration.
create trigger trg_document_summaries_updated_at
  before update on document_summaries
  for each row execute function update_updated_at();

-- Table privileges. service_role bypasses RLS but still needs table-level GRANTs;
-- the worker and the `summaries` Edge Function use it to read/claim/update rows.
-- authenticated needs SELECT for the owner-scoped policy below. anon is intentionally
-- not granted: all browser access goes through the Edge Function (service role).
grant select, insert, update on document_summaries to service_role;
grant select on document_summaries to authenticated;

-- Row Level Security: the table is written/read server-side by the worker and the
-- `summaries` Edge Function using the service role (which bypasses RLS). No anon
-- policies are granted, so the table is not directly readable by the browser anon
-- key -- all client access goes through the Edge Function.
alter table document_summaries enable row level security;

-- Owner-scoped policy for a future authenticated UI (service role still bypasses RLS).
create policy document_summaries_owner_select
  on document_summaries for select
  to authenticated
  using (created_by = auth.uid());

-- Storage policies for the private `documents` bucket (declared in config.toml).
-- The browser uploads with the anon/authenticated key; reads are server-side only
-- (worker/Edge Function via service role), so no SELECT policy is granted here.
create policy documents_bucket_insert
  on storage.objects for insert
  to anon, authenticated
  with check (bucket_id = 'documents');
