// Unit tests for the `summaries` Edge Function routing/handlers (router.ts).
// Runs fully offline: the Supabase client is replaced by a chainable fake that
// returns preconfigured results, so no network or database is touched.
//
// Run with: deno test supabase/functions/summaries/router.test.ts
import {
  assertEquals,
  assertStringIncludes,
} from "https://deno.land/std@0.224.0/assert/mod.ts";
import { createRouter, MAX_INPUT_BYTES, type SummariesDb } from "./router.ts";

type Result = { data?: unknown; error?: unknown };

// Builds a fake supabase-js-like client. Terminal calls (`single`, `limit`)
// resolve to the next preconfigured result, in order. Captures insert/update
// payloads and the tables touched for assertions.
function makeFakeDb(results: Result[]) {
  const calls = {
    inserts: [] as unknown[],
    updates: [] as unknown[],
    from: [] as string[],
    selects: [] as unknown[],
    eqs: [] as Array<[string, unknown]>,
    orders: [] as unknown[],
    limits: [] as number[],
  };
  let i = 0;
  const next = (): Result =>
    results[i++] ?? { data: null, error: { message: "no result configured" } };

  const builder: Record<string, unknown> = {};
  Object.assign(builder, {
    insert(v: unknown) {
      calls.inserts.push(v);
      return builder;
    },
    update(v: unknown) {
      calls.updates.push(v);
      return builder;
    },
    select(cols?: unknown) {
      calls.selects.push(cols ?? null);
      return builder;
    },
    eq(col: string, val: unknown) {
      calls.eqs.push([col, val]);
      return builder;
    },
    order(col: unknown, opts: unknown) {
      calls.orders.push([col, opts]);
      return builder;
    },
    limit: (n: number) => {
      calls.limits.push(n);
      return Promise.resolve(next());
    },
    single: () => Promise.resolve(next()),
  });

  const db: SummariesDb = {
    from(table: string) {
      calls.from.push(table);
      return builder;
    },
  };
  return { db, calls };
}

const BASE = "http://localhost/functions/v1/summaries";
const VALID_MIME = "text/plain";

function postCreate(body: unknown): Request {
  return new Request(BASE, {
    method: "POST",
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

Deno.test("POST create: valid payload returns 201 and inserts the full row", async () => {
  const { db, calls } = makeFakeDb([{ data: { id: "abc", status: "uploaded" } }]);
  const handle = createRouter(db);
  const res = await handle(
    postCreate({
      storage_path: "documents/abc.txt",
      original_filename: "abc.txt",
      mime_type: VALID_MIME,
      size_bytes: 1024,
    }),
  );
  assertEquals(res.status, 201);
  const json = await res.json();
  assertEquals(json.id, "abc");
  assertEquals(calls.from, ["document_summaries"]);
  // The whole insert contract matters, not just status: a regression dropping
  // storage_path/original_filename/mime_type must fail this test.
  assertEquals(calls.inserts[0], {
    storage_path: "documents/abc.txt",
    original_filename: "abc.txt",
    mime_type: VALID_MIME,
    status: "uploaded",
  });
});

Deno.test("POST create: missing size_bytes returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({
      storage_path: "documents/a.txt",
      original_filename: "a.txt",
      mime_type: VALID_MIME,
    }),
  );
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "size_bytes is required");
});

Deno.test("POST create: non-numeric size_bytes returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({
      storage_path: "documents/a.txt",
      original_filename: "a.txt",
      mime_type: VALID_MIME,
      size_bytes: "not-a-number",
    }),
  );
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "size_bytes must be a non-negative number");
});

Deno.test("POST create: negative size_bytes returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({
      storage_path: "documents/a.txt",
      original_filename: "a.txt",
      mime_type: VALID_MIME,
      size_bytes: -1,
    }),
  );
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "non-negative");
});

Deno.test("POST create: size_bytes exactly at the cap is accepted", async () => {
  const { db } = makeFakeDb([{ data: { id: "edge", status: "uploaded" } }]);
  const res = await createRouter(db)(
    postCreate({
      storage_path: "documents/edge.txt",
      original_filename: "edge.txt",
      mime_type: VALID_MIME,
      size_bytes: MAX_INPUT_BYTES,
    }),
  );
  assertEquals(res.status, 201);
});

Deno.test("POST create: missing storage_path returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({ original_filename: "a.txt", mime_type: VALID_MIME }),
  );
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "storage_path is required");
});

Deno.test("POST create: missing original_filename returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({ storage_path: "documents/a.txt", mime_type: VALID_MIME }),
  );
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "original_filename is required");
});

Deno.test("POST create: unsupported mime_type returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({
      storage_path: "documents/a.png",
      original_filename: "a.png",
      mime_type: "image/png",
    }),
  );
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "Unsupported mime_type");
});

Deno.test("POST create: oversized file returns 413", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    postCreate({
      storage_path: "documents/big.txt",
      original_filename: "big.txt",
      mime_type: VALID_MIME,
      size_bytes: MAX_INPUT_BYTES + 1,
    }),
  );
  assertEquals(res.status, 413);
  assertStringIncludes((await res.json()).error, "byte limit");
});

Deno.test("POST create: invalid JSON body returns 400", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(postCreate("{ not json"));
  assertEquals(res.status, 400);
  assertStringIncludes((await res.json()).error, "Invalid JSON body");
});

Deno.test("GET list returns 200 with the rows", async () => {
  const rows = [{ id: "1" }, { id: "2" }];
  const { db } = makeFakeDb([{ data: rows }]);
  const res = await createRouter(db)(new Request(BASE, { method: "GET" }));
  assertEquals(res.status, 200);
  assertEquals(await res.json(), rows);
});

Deno.test("GET one: found returns 200", async () => {
  const { db } = makeFakeDb([{ data: { id: "abc", status: "completed" } }]);
  const res = await createRouter(db)(
    new Request(`${BASE}/abc`, { method: "GET" }),
  );
  assertEquals(res.status, 200);
  assertEquals((await res.json()).status, "completed");
});

Deno.test("GET one: not found returns 404", async () => {
  const { db } = makeFakeDb([{ data: null, error: { message: "no rows" } }]);
  const res = await createRouter(db)(
    new Request(`${BASE}/missing`, { method: "GET" }),
  );
  assertEquals(res.status, 404);
});

Deno.test("POST retry: non-failed request returns 409", async () => {
  const { db } = makeFakeDb([{ data: { id: "abc", status: "completed" } }]);
  const res = await createRouter(db)(
    new Request(`${BASE}/abc/retry`, { method: "POST" }),
  );
  assertEquals(res.status, 409);
  assertStringIncludes((await res.json()).error, "Only failed requests");
});

Deno.test("POST retry: failed request returns 200 and resets the full row", async () => {
  const { db, calls } = makeFakeDb([
    { data: { id: "abc", status: "failed" } },
    { data: { id: "abc", status: "uploaded" } },
  ]);
  const res = await createRouter(db)(
    new Request(`${BASE}/abc/retry`, { method: "POST" }),
  );
  assertEquals(res.status, 200);
  // The update must target this id only (not every failed row)...
  assertEquals(calls.eqs, [["id", "abc"], ["id", "abc"]]);
  // ...and must clear the previous run's fields, not just flip status.
  assertEquals(calls.updates[0], {
    status: "uploaded",
    workflow_id: null,
    summary: null,
    error_message: null,
  });
});

Deno.test("POST retry: unknown id returns 404", async () => {
  const { db } = makeFakeDb([{ data: null, error: { message: "no rows" } }]);
  const res = await createRouter(db)(
    new Request(`${BASE}/missing/retry`, { method: "POST" }),
  );
  assertEquals(res.status, 404);
});

Deno.test("unknown route returns 404", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(
    new Request(`${BASE}/a/b/c/d`, { method: "DELETE" }),
  );
  assertEquals(res.status, 404);
});

Deno.test("OPTIONS preflight returns CORS headers", async () => {
  const { db } = makeFakeDb([]);
  const res = await createRouter(db)(new Request(BASE, { method: "OPTIONS" }));
  assertEquals(res.status, 200);
  assertEquals(res.headers.get("Access-Control-Allow-Origin"), "*");
  await res.text();
});
