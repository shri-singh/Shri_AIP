// Applies the kit's migrations to PGlite (real PostgreSQL 18 compiled to WASM) and checks RLS behaviour.
// No database server or Docker needed:   cd database/validate && npm ci && node validate_migrations.mjs
// This proves SQL syntax, idempotency, RLS isolation and rollback guards. It does NOT replace a DBA
// review or a dry run against a restored snapshot of the real Opsi database (version/extension differences).
import { PGlite } from "@electric-sql/pglite";
import { vector } from "@electric-sql/pglite-pgvector";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = process.argv[2] ?? fileURLToPath(new URL("../..", import.meta.url));
const migDir = join(root, "database", "migrations");
const db = new PGlite({ extensions: { vector } });
const version = (await db.query("select version()")).rows[0].version;
console.log("server:", version.split(",")[0]);

let failures = 0;
const check = (label, cond, detail = "") => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? "  -> " + detail : ""}`);
  if (!cond) failures++;
};

for (const f of readdirSync(migDir).filter((n) => n.endsWith(".sql")).sort()) {
  try {
    await db.exec(readFileSync(join(migDir, f), "utf8"));
    check(`apply ${f}`, true);
  } catch (e) {
    check(`apply ${f}`, false, e.message);
  }
}
// idempotency: re-apply everything once more
for (const f of readdirSync(migDir).filter((n) => n.endsWith(".sql")).sort()) {
  try { await db.exec(readFileSync(join(migDir, f), "utf8")); } catch (e) { check(`re-apply ${f}`, false, e.message); }
}
check("migrations are re-runnable (idempotent)", true);

await db.exec(readFileSync(join(root, "database", "samples", "synthetic_seed.sql"), "utf8"));
check("seed applied", true);

async function asApp(tenant, user, sql, params = []) {
  await db.exec("BEGIN; SET LOCAL ROLE opsi_app;");
  if (tenant !== null) await db.query("select set_config('opsi.tenant_id', $1, true)", [tenant]);
  if (user !== null) await db.query("select set_config('opsi.user_id', $1, true)", [user]);
  try {
    const r = await db.query(sql, params);
    await db.exec("COMMIT");
    return r;
  } catch (e) {
    await db.exec("ROLLBACK");
    throw e;
  }
}
const count = async (t, u, table) => Number((await asApp(t, u, `select count(*)::int as n from ${table}`)).rows[0].n);

check("owner sees own thread", (await count("tenant-demo", "demo-user", "opsi_chat.threads")) === 1);
check("owner sees thread messages", (await count("tenant-demo", "demo-user", "opsi_chat.messages")) === 2);
check("other user in same tenant cannot see private thread", (await count("tenant-demo", "other-user", "opsi_chat.threads")) === 0);
check("other user cannot see its messages", (await count("tenant-demo", "other-user", "opsi_chat.messages")) === 0);
check("other user cannot see its citations", (await count("tenant-demo", "other-user", "opsi_chat.evidence_refs")) === 0);
check("tenant-wide ontology visible to tenant members", (await count("tenant-demo", "other-user", "opsi_knowledge.entities")) === 7);
check("other tenant sees no ontology", (await count("tenant-x", "demo-user", "opsi_knowledge.entities")) === 0);
check("other tenant sees no problems", (await count("tenant-x", "demo-user", "opsi_ingest.problems")) === 0);
check("no session tenant => zero rows (fail closed)", (await count(null, null, "opsi_knowledge.entities")) === 0);
check("hourly view respects tenant", (await count("tenant-x", "u", "opsi_ingest.error_signatures_hourly")) === 0 &&
      (await count("tenant-demo", "u", "opsi_ingest.error_signatures_hourly")) === 1);

await db.exec("UPDATE opsi_chat.threads SET visibility='tenant'");
check("tenant-visible thread readable by colleague", (await count("tenant-demo", "other-user", "opsi_chat.threads")) === 1);
let denied = false;
try {
  await asApp("tenant-demo", "other-user", "insert into opsi_chat.messages (tenant_id, thread_id, message_id, role, content_json, author_id) values ('tenant-demo','00000000-0000-4000-9000-000000000001','x','user','{}','other-user')");
} catch (e) { denied = /row-level security/.test(e.message); }
check("colleague cannot write into someone else's shared thread", denied);
await db.exec("UPDATE opsi_chat.threads SET visibility='private'");

denied = false;
try {
  await asApp("tenant-demo", "demo-user", "insert into opsi_chat.threads (id, tenant_id, owner_id) values (gen_random_uuid(), 'tenant-x', 'demo-user')");
} catch (e) { denied = /row-level security/.test(e.message); }
check("cannot insert a row for another tenant", denied);

denied = false;
try {
  await asApp("tenant-demo", "demo-user", "insert into opsi_chat.threads (id, tenant_id, owner_id) values (gen_random_uuid(), 'tenant-demo', 'someone-else')");
} catch (e) { denied = /row-level security/.test(e.message); }
check("cannot create a thread owned by someone else", denied);

denied = false;
try { await asApp("tenant-demo", "demo-user", "update opsi_audit.events set action='x'"); } catch (e) { denied = /permission denied/.test(e.message); }
check("audit events are append-only for opsi_app", denied);

const hood = await asApp("tenant-demo", "demo-user",
  "select * from opsi_knowledge.neighborhood('00000000-0000-4000-8000-000000000006', '2026-10-25Z', 2, 50)");
check("neighborhood traversal returns bounded graph", hood.rows.length >= 3, `${hood.rows.length} edges`);
const hoodX = await asApp("tenant-x", "demo-user",
  "select * from opsi_knowledge.neighborhood('00000000-0000-4000-8000-000000000006', '2026-10-25Z', 2, 50)");
check("neighborhood traversal respects RLS", hoodX.rows.length === 0);

denied = false;
try {
  await asApp("tenant-demo", "demo-user", "insert into opsi_knowledge.edges (tenant_id, src_id, dst_id, relation, valid_from, source_system, created_by, confidence) values ('tenant-demo','00000000-0000-4000-8000-000000000006','00000000-0000-4000-8000-000000000001','caused_by', now(), 'agent', 'agent:x', 1.0)");
} catch (e) { denied = /check constraint/.test(e.message); }
check("agent edges require evidence and confidence < 1", denied);

const vec = await asApp("tenant-demo", "demo-user",
  `insert into opsi_knowledge.documents (tenant_id, doc_type, title, source_ref, content_excerpt, content_sha256, embedding, embedding_model)
   values ('tenant-demo','runbook','r','kb://r','text','abc', array_fill(0.01, array[1024])::vector, 'test-model') returning id`);
check("pgvector document insert (1024 dims)", vec.rows.length === 1);
const knn = await asApp("tenant-demo", "demo-user",
  "select title from opsi_knowledge.documents order by embedding <=> array_fill(0.01, array[1024])::vector limit 1");
check("pgvector cosine search", knn.rows.length === 1);

let guarded = false;
try { await db.exec(readFileSync(join(migDir, "rollback", "0003_down.sql"), "utf8")); } catch (e) { guarded = /Refusing destructive rollback/.test(e.message); }
check("rollback refuses without opsi.allow_destructive", guarded);

for (const f of ["0007_down.sql", "0006_down.sql", "0005_down.sql", "0004_down.sql", "0003_down.sql", "0002_down.sql", "0001_down.sql"]) {
  try {
    await db.exec("SET opsi.allow_destructive = 'yes';" + readFileSync(join(migDir, "rollback", f), "utf8"));
    check(`rollback ${f}`, true);
  } catch (e) { check(`rollback ${f}`, false, e.message); }
}
const left = await db.query("select nspname from pg_namespace where nspname in ('opsi_chat','opsi_knowledge','opsi_ingest','opsi_audit')");
check("full rollback leaves no opsi schemas", left.rows.length === 0);
for (const f of readdirSync(migDir).filter((n) => n.endsWith(".sql")).sort()) {
  try { await db.exec(readFileSync(join(migDir, f), "utf8")); } catch (e) { check(`re-apply after rollback ${f}`, false, e.message); }
}
check("migrations re-apply cleanly after full rollback", true);

console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
