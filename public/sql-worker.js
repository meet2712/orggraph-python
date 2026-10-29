/* SQLite stays in this worker so a slow query can be stopped without freezing the page. */
importScripts("/vendor/sql-wasm.js");

let database = null;
const MAX_ROWS = 200;
const MAX_QUERY_LENGTH = 20000;
const BLOCKED_WORDS = new Set([
  "ALTER", "ANALYZE", "ATTACH", "BEGIN", "COMMIT", "CREATE", "DELETE", "DETACH",
  "DROP", "INSERT", "PRAGMA", "REINDEX", "RELEASE", "ROLLBACK", "SAVEPOINT",
  "UPDATE", "VACUUM", "LOAD_EXTENSION", "READFILE", "WRITEFILE",
]);

function quoteIdentifier(name) {
  return `"${name.replaceAll('"', '""')}"`;
}

function nextSqlCharacter(sql, start) {
  let position = start;
  while (position < sql.length) {
    if (/\s/.test(sql[position])) { position += 1; continue; }
    if (sql.startsWith("--", position)) {
      const nextLine = sql.indexOf("\n", position + 2);
      position = nextLine < 0 ? sql.length : nextLine + 1;
      continue;
    }
    if (sql.startsWith("/*", position)) {
      const end = sql.indexOf("*/", position + 2);
      if (end < 0) throw new Error("The SQL comment is not closed.");
      position = end + 2;
      continue;
    }
    return sql[position];
  }
  return "";
}

function validateQuery(query) {
  if (typeof query !== "string" || !query.trim()) throw new Error("Enter a SELECT query first.");
  if (query.length > MAX_QUERY_LENGTH) throw new Error("Keep the query below 20,000 characters.");

  // Read only SQL outside quoted values and comments. A semicolon can only end the query.
  const words = [];
  let position = 0;
  let ended = false;
  while (position < query.length) {
    const character = query[position];
    if (/\s/.test(character)) { position += 1; continue; }
    if (query.startsWith("--", position)) {
      const nextLine = query.indexOf("\n", position + 2);
      position = nextLine < 0 ? query.length : nextLine + 1;
      continue;
    }
    if (query.startsWith("/*", position)) {
      const end = query.indexOf("*/", position + 2);
      if (end < 0) throw new Error("The SQL comment is not closed.");
      position = end + 2;
      continue;
    }
    if (ended) throw new Error("Run one query at a time.");
    if (character === ";") { ended = true; position += 1; continue; }
    if (["'", '"', "`", "["].includes(character)) {
      const closing = character === "[" ? "]" : character;
      position += 1;
      let closed = false;
      while (position < query.length) {
        if (query[position] !== closing) { position += 1; continue; }
        if (closing !== "]" && query[position + 1] === closing) { position += 2; continue; }
        position += 1;
        closed = true;
        break;
      }
      if (!closed) throw new Error("A quoted value or name is not closed.");
      continue;
    }
    const word = query.slice(position).match(/^[A-Za-z_][A-Za-z_0-9$]*/);
    if (word) {
      const value = word[0].toUpperCase();
      words.push(value);
      if (BLOCKED_WORDS.has(value)) throw new Error("This workspace only allows read-only SELECT queries.");
      position += word[0].length;
      if (value === "REPLACE" && nextSqlCharacter(query, position) !== "(") {
        throw new Error("This workspace only allows read-only SELECT queries.");
      }
      continue;
    }
    position += 1;
  }
  if (!["SELECT", "WITH", "EXPLAIN"].includes(words[0])) {
    throw new Error("Use SELECT, a read-only WITH query, or EXPLAIN SELECT.");
  }
  return query;
}

function readRows(sql, limit = MAX_ROWS) {
  const statement = database.prepare(sql);
  try {
    const columns = statement.getColumnNames();
    const rows = [];
    let truncated = false;
    while (statement.step()) {
      if (rows.length === limit) { truncated = true; break; }
      rows.push(statement.get());
    }
    return { columns, rows, truncated };
  } finally {
    statement.free();
  }
}

function inspectTables() {
  const tables = readRows("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").rows;
  return tables.map(([name, sql]) => ({
    name,
    sql,
    rowCount: readRows(`SELECT COUNT(*) FROM ${quoteIdentifier(name)}`).rows[0][0],
    columns: readRows(`PRAGMA table_info(${quoteIdentifier(name)})`).rows,
    foreignKeys: readRows(`PRAGMA foreign_key_list(${quoteIdentifier(name)})`).rows,
  }));
}

async function openDatabase() {
  self.postMessage({ type: "status", message: "Loading the SQLite query engine…" });
  const SQL = await initSqlJs({ locateFile: (file) => `/vendor/${file}` });
  self.postMessage({ type: "status", message: "Downloading the read-only database snapshot…" });
  const response = await fetch("/database/snapshot.sqlite.gz");
  if (!response.ok) throw new Error("The database snapshot could not be loaded.");
  let bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    if (typeof DecompressionStream === "undefined") {
      throw new Error("This browser cannot open the compressed snapshot. Try a current browser.");
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  }
  if (new TextDecoder().decode(bytes.slice(0, 15)) !== "SQLite format 3") {
    throw new Error("The snapshot is not a valid SQLite database.");
  }
  database = new SQL.Database(bytes);
  database.run("PRAGMA query_only = ON");
  self.postMessage({ type: "ready", tables: inspectTables(), snapshotBytes: bytes.length });
}

self.addEventListener("message", async (event) => {
  const { type, id, query } = event.data;
  if (type === "open") {
    try { await openDatabase(); }
    catch (error) { self.postMessage({ type: "error", id, message: error.message || String(error) }); }
    return;
  }
  if (type !== "query") return;
  const started = performance.now();
  try {
    if (!database) throw new Error("The database has not finished loading.");
    validateQuery(query);
    database.run("PRAGMA query_only = ON");
    const result = readRows(query);
    self.postMessage({ type: "result", id, ...result, elapsedMs: performance.now() - started });
  } catch (error) {
    const message = error.message || String(error);
    self.postMessage({ type: "error", id, message: /readonly|read.only|write/i.test(message) ? "This workspace only allows read-only SELECT queries." : message });
  }
});
