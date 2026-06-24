// `summaries` Edge Function -- orchestration entry point for AI document
// summarization. It validates input, records the request in `document_summaries`
// (status=uploaded), and exposes status/results. The Temporal workflow itself is
// started by the Python worker's intake poller (the Deno runtime has no
// production-grade Temporal client), so this function never talks to Temporal.
//
// Routes (mounted under /functions/v1/summaries):
//   POST   /summaries              -> create a request (returns 201)
//   GET    /summaries              -> list recent requests
//   GET    /summaries/{id}         -> get one request (status/summary)
//   POST   /summaries/{id}/retry   -> requeue a failed request
//
// The routing/handler logic lives in `router.ts` (injectable Supabase client) so
// it can be unit-tested without the Deno.serve loop. See router.test.ts and
// docs/specs/ai-document-summarization.md
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";
import { createRouter } from "./router.ts";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Service-role client: server-side only, bypasses RLS, never exposed to the browser.
const admin = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

Deno.serve(createRouter(admin));
