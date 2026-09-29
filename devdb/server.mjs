/** Development database server: PostgreSQL (WASM) + pgvector behind a real
 *  PG wire protocol on 127.0.0.1:5432.
 *
 *  This exists ONLY because this machine has no Docker/WSL/PostgreSQL.
 *  It is full PostgreSQL compiled to WebAssembly (PGlite) with the pgvector
 *  extension — the same SQL semantics the app uses (HNSW cosine index,
 *  FOR UPDATE SKIP LOCKED). Production deployments should use a real
 *  PostgreSQL + pgvector (docker compose up -d db).
 *
 *  Usage:  node server.mjs    (Ctrl+C to stop; data persists in ./data-dir)
 */

import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite-pgvector';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';

const PORT = Number(process.env.DEV_PG_PORT ?? 5432);

const db = new PGlite(new URL('./data-dir', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), {
  extensions: { vector },
});

await db.waitReady;
await db.exec('CREATE EXTENSION IF NOT EXISTS vector;');

const server = new PGLiteSocketServer({
  db,
  port: PORT,
  host: '127.0.0.1',
  maxConnections: 10,
});

await server.start();
console.log(`[devdb] PostgreSQL(WASM)+pgvector listening on 127.0.0.1:${PORT}`);
console.log('[devdb] connect with: postgresql://postgres:postgres@127.0.0.1:5432/postgres');

const shutdown = async () => {
  console.log('\n[devdb] shutting down…');
  try {
    await server.stop();
  } catch { /* ignore */ }
  try {
    await db.close();
  } catch { /* ignore */ }
  process.exit(0);
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
