// Routing + request handling for the `summaries` Edge Function, extracted from
// the Deno.serve bootstrap so it can be unit-tested with an injected Supabase
// client (no network, no Deno runtime serve loop). `index.ts` wires the real
// service-role client into `createRouter`.
//
// See docs/specs/ai-document-summarization.md
import { corsHeaders } from "../_shared/cors.ts";

export const MAX_INPUT_BYTES = 512 * 1024; // 512 KB hard cap (also enforced by Storage + worker)
export const ALLOWED_MIME_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "application/vnd.oasis.opendocument.text",
]);

// Minimal structural type for the slice of the supabase-js client we use. This
// lets tests inject a lightweight fake without pulling the full SDK types.
export interface SummariesDb {
  from(table: string): any;
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

// Returns the path segments after the function name, e.g.
// /functions/v1/summaries/<id>/retry -> ["<id>", "retry"].
export function subPath(url: URL): string[] {
  const parts = url.pathname.split("/").filter(Boolean);
  const idx = parts.indexOf("summaries");
  return idx === -1 ? [] : parts.slice(idx + 1);
}

async function handleCreate(admin: SummariesDb, req: Request): Promise<Response> {
  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const storagePath = String(payload.storage_path ?? "").trim();
  const originalFilename = String(payload.original_filename ?? "").trim();
  const mimeType = String(payload.mime_type ?? "").trim();

  if (!storagePath) return json({ error: "storage_path is required" }, 400);
  if (!originalFilename) {
    return json({ error: "original_filename is required" }, 400);
  }
  if (!ALLOWED_MIME_TYPES.has(mimeType)) {
    return json({ error: `Unsupported mime_type: ${mimeType}` }, 400);
  }
  // `size_bytes` is part of the documented payload and gates the 512 KB cap
  // server-side; reject missing/non-numeric/negative values rather than coercing
  // them to 0 (which would silently bypass the limit).
  if (payload.size_bytes === undefined || payload.size_bytes === null) {
    return json({ error: "size_bytes is required" }, 400);
  }
  const sizeBytes = Number(payload.size_bytes);
  if (!Number.isFinite(sizeBytes) || sizeBytes < 0) {
    return json({ error: "size_bytes must be a non-negative number" }, 400);
  }
  if (sizeBytes > MAX_INPUT_BYTES) {
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

async function handleGetOne(admin: SummariesDb, id: string): Promise<Response> {
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

async function handleList(admin: SummariesDb): Promise<Response> {
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

async function handleRetry(admin: SummariesDb, id: string): Promise<Response> {
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

// Builds the request handler bound to a given Supabase client.
export function createRouter(admin: SummariesDb): (req: Request) => Promise<Response> {
  return async (req: Request): Promise<Response> => {
    if (req.method === "OPTIONS") {
      return new Response("ok", { headers: corsHeaders });
    }

    const url = new URL(req.url);
    const segments = subPath(url);

    try {
      if (req.method === "POST" && segments.length === 0) {
        return await handleCreate(admin, req);
      }
      if (req.method === "GET" && segments.length === 0) {
        return await handleList(admin);
      }
      if (req.method === "GET" && segments.length === 1) {
        return await handleGetOne(admin, segments[0]);
      }
      if (
        req.method === "POST" && segments.length === 2 && segments[1] === "retry"
      ) {
        return await handleRetry(admin, segments[0]);
      }
      return json({ error: "Not found" }, 404);
    } catch (err) {
      console.error(`summaries unhandled error: ${String(err)}`);
      return json({ error: "Internal error" }, 500);
    }
  };
}
