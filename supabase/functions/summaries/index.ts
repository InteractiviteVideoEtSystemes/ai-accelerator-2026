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
// See docs/specs/ai-document-summarization.md
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";
import { corsHeaders } from "../_shared/cors.ts";

const MAX_INPUT_BYTES = 512 * 1024; // 512 KB hard cap (also enforced by Storage + worker)
const ALLOWED_MIME_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
]);

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Service-role client: server-side only, bypasses RLS, never exposed to the browser.
const admin = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

// Returns the path segments after the function name, e.g.
// /functions/v1/summaries/<id>/retry -> ["<id>", "retry"].
function subPath(url: URL): string[] {
  const parts = url.pathname.split("/").filter(Boolean);
  const idx = parts.indexOf("summaries");
  return idx === -1 ? [] : parts.slice(idx + 1);
}

async function handleCreate(req: Request): Promise<Response> {
  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const storagePath = String(payload.storage_path ?? "").trim();
  const originalFilename = String(payload.original_filename ?? "").trim();
  const mimeType = String(payload.mime_type ?? "").trim();
  const sizeBytes = Number(payload.size_bytes ?? 0);

  if (!storagePath) return json({ error: "storage_path is required" }, 400);
  if (!originalFilename) {
    return json({ error: "original_filename is required" }, 400);
  }
  if (!ALLOWED_MIME_TYPES.has(mimeType)) {
    return json({ error: `Unsupported mime_type: ${mimeType}` }, 400);
  }
  if (Number.isFinite(sizeBytes) && sizeBytes > MAX_INPUT_BYTES) {
    return json(
      { error: `File exceeds the ${MAX_INPUT_BYTES} byte limit` },
      413,
    );
  }

  const { data, error } = await admin
    .from("document_summaries")
    .insert({
      storage_path: storagePath,
      original_filename: originalFilename,
      mime_type: mimeType,
      status: "uploaded",
    })
    .select()
    .single();

  if (error) {
    console.error(`summaries.create failed: ${error.message}`);
    return json({ error: "Could not create summary request" }, 500);
  }
  return json(data, 201);
}

async function handleGetOne(id: string): Promise<Response> {
  const { data, error } = await admin
    .from("document_summaries")
    .select(
      "id, status, original_filename, summary, error_message, workflow_id, created_at, updated_at",
    )
    .eq("id", id)
    .single();

  if (error || !data) return json({ error: "Not found" }, 404);
  return json(data);
}

async function handleList(): Promise<Response> {
  const { data, error } = await admin
    .from("document_summaries")
    .select(
      "id, status, original_filename, summary, error_message, created_at, updated_at",
    )
    .order("created_at", { ascending: false })
    .limit(50);

  if (error) return json({ error: "Could not list summaries" }, 500);
  return json(data ?? []);
}

async function handleRetry(id: string): Promise<Response> {
  const { data: existing, error: fetchErr } = await admin
    .from("document_summaries")
    .select("id, status")
    .eq("id", id)
    .single();

  if (fetchErr || !existing) return json({ error: "Not found" }, 404);
  if (existing.status !== "failed") {
    return json({ error: "Only failed requests can be retried" }, 409);
  }

  const { data, error } = await admin
    .from("document_summaries")
    .update({
      status: "uploaded",
      workflow_id: null,
      summary: null,
      error_message: null,
    })
    .eq("id", id)
    .select()
    .single();

  if (error) return json({ error: "Could not retry request" }, 500);
  return json(data);
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const url = new URL(req.url);
  const segments = subPath(url);

  try {
    if (req.method === "POST" && segments.length === 0) {
      return await handleCreate(req);
    }
    if (req.method === "GET" && segments.length === 0) {
      return await handleList();
    }
    if (req.method === "GET" && segments.length === 1) {
      return await handleGetOne(segments[0]);
    }
    if (
      req.method === "POST" && segments.length === 2 && segments[1] === "retry"
    ) {
      return await handleRetry(segments[0]);
    }
    return json({ error: "Not found" }, 404);
  } catch (err) {
    console.error(`summaries unhandled error: ${String(err)}`);
    return json({ error: "Internal error" }, 500);
  }
});
