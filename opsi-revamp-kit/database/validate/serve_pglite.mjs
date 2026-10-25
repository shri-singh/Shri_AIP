// Throwaway PostgreSQL-compatible server for integration tests - no Docker, no real DB.
// Applies all migrations (+ optional synthetic seed) into an in-memory PGlite and serves the
// PostgreSQL wire protocol on 127.0.0.1 only.
//
//   cd database/validate && npm ci
//   node serve_pglite.mjs --port 55432 --seed
//   export TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable'
//   pytest -m integration
//
// Limitations: PGlite is single-process; the socket server multiplexes connections. Fine for tests,
// never for anything real. Data disappears when the process exits.
import { PGlite } from "@electric-sql/pglite";
import { vector } from "@electric-sql/pglite-pgvector";
import { PGLiteSocketServer } from "@electric-sql/pglite-socket";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const port = Number(args[args.indexOf("--port") + 1] || 55432);
const seed = args.includes("--seed");
const root = fileURLToPath(new URL("../..", import.meta.url));
const migDir = join(root, "database", "migrations");

const db = new PGlite({ extensions: { vector } });
for (const f of readdirSync(migDir).filter((n) => n.endsWith(".sql")).sort()) {
  await db.exec(readFileSync(join(migDir, f), "utf8"));
}
if (seed) await db.exec(readFileSync(join(root, "database", "samples", "synthetic_seed.sql"), "utf8"));

const server = new PGLiteSocketServer({ db, port, host: "127.0.0.1", maxConnections: 8 });
await server.start();
console.log(`READY postgresql://postgres@127.0.0.1:${port}/postgres (migrations applied${seed ? ", seeded" : ""})`);
const stop = async () => { await server.stop(); await db.close(); process.exit(0); };
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
