const queryEditor = document.querySelector("#sql-query");

if (queryEditor) {
  const runButton = document.querySelector("#run-query");
  const resetButton = document.querySelector("#reset-database");
  const examplePicker = document.querySelector("#sql-example");
  const status = document.querySelector("#query-status");
  const errorMessage = document.querySelector("#query-error");
  const tableList = document.querySelector("#database-tables");
  const resultArea = document.querySelector("#query-results");
  const resultCount = document.querySelector("#query-result-count");
  const schemaInspector = document.querySelector("#schema-inspector");
  let worker = null;
  let ready = false;
  let nextQueryId = 0;
  let activeQueryId = null;
  let queryTimer = null;
  let loadingTimer = null;
  let tables = [];

  function waitForLoadingProgress() {
    clearTimeout(loadingTimer);
    loadingTimer = setTimeout(() => stopWorker("The database download stopped responding. Reload it to try again."), 60000);
  }

  const examples = {
    audit: `SELECT full_name, job_title, inferred_manager, leading_candidate,
       ROUND(confidence * 100, 1) AS evidence_score_pct,
       ROUND(margin * 100, 1) AS lead_pct, decision, decision_reason
FROM employee_reporting_audit
WHERE company_id = 'cmp_0004'
  AND employee_id IN ('emp_0000542', 'emp_0000543')
ORDER BY employee_id;`,
    profiles: `SELECT company_name, employee_count AS people, size_band
FROM company_profiles
WHERE company_id IN ('cmp_0001', 'cmp_0002', 'cmp_0003')
ORDER BY company_name;`,
    counts: `SELECT 'companies' AS dataset, COUNT(*) AS rows FROM companies
UNION ALL
SELECT 'employees', COUNT(*) FROM employees;`,
    classification: `SELECT e.full_name, e.job_title,
       f.inferred_department, f.inferred_level
FROM employees AS e
JOIN employee_features AS f USING (company_id, employee_id)
WHERE e.company_id = 'cmp_0004'
  AND e.employee_id IN ('emp_0000542', 'emp_0000543')
ORDER BY e.employee_id;`,
    matches: `SELECT c.company_name, e.full_name AS employee,
       m.full_name AS inferred_manager,
       ROUND(p.confidence * 100, 1) AS evidence_score_pct
FROM reporting_predictions AS p
JOIN companies AS c USING (company_id)
JOIN employees AS e
  ON e.company_id = p.company_id AND e.employee_id = p.employee_id
JOIN employees AS m
  ON m.company_id = p.company_id AND m.employee_id = p.accepted_manager_id
WHERE p.company_id = 'cmp_0004'
  AND p.employee_id IN ('emp_0000542', 'emp_0000545')
  AND p.decision = 'accepted'
ORDER BY e.employee_id;`,
    chain: `WITH RECURSIVE manager_chain AS (
  SELECT e.company_id, e.employee_id, e.full_name, e.job_title,
         p.accepted_manager_id, 0 AS depth
  FROM employees AS e
  JOIN reporting_predictions AS p USING (company_id, employee_id)
  WHERE e.company_id = 'cmp_0001' AND e.employee_id = 'emp_0000018'
  UNION ALL
  SELECT e.company_id, e.employee_id, e.full_name, e.job_title,
         p.accepted_manager_id, chain.depth + 1
  FROM manager_chain AS chain
  JOIN employees AS e ON e.company_id = chain.company_id
    AND e.employee_id = chain.accepted_manager_id
  JOIN reporting_predictions AS p ON p.company_id = e.company_id
    AND p.employee_id = e.employee_id
  WHERE chain.depth < 12
)
SELECT depth, full_name, job_title, accepted_manager_id
FROM manager_chain ORDER BY depth;`,
    quality: `SELECT COUNT(*) AS employees,
       SUM(CASE WHEN TRIM(job_title) = '' THEN 1 ELSE 0 END) AS missing_titles,
       SUM(CASE WHEN TRIM(raw_department) = '' THEN 1 ELSE 0 END) AS missing_departments,
       SUM(CASE WHEN TRIM(raw_team) = '' THEN 1 ELSE 0 END) AS missing_teams,
       SUM(CASE WHEN TRIM(location) = '' THEN 1 ELSE 0 END) AS missing_locations
FROM employees;`,
    thresholds: `SELECT score_threshold, margin_threshold
FROM inference_settings;`,
  };

  function placeholder(text) {
    resultArea.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.className = "result-placeholder";
    paragraph.textContent = text;
    resultArea.append(paragraph);
  }

  function showError(text) {
    errorMessage.textContent = text;
    errorMessage.hidden = false;
  }

  function setBusy(busy) {
    runButton.disabled = busy || !ready;
    examplePicker.disabled = busy;
    for (const button of tableList.querySelectorAll("button")) button.disabled = busy;
  }

  function stopWorker(message) {
    if (worker) worker.terminate();
    worker = null;
    ready = false;
    activeQueryId = null;
    clearTimeout(queryTimer);
    clearTimeout(loadingTimer);
    setBusy(false);
    resetButton.hidden = false;
    status.textContent = "The database copy is closed.";
    showError(message);
  }

  function renderResult(message) {
    resultArea.replaceChildren();
    const table = document.createElement("table");
    table.className = "sql-result-table";
    const caption = document.createElement("caption");
    caption.className = "sr-only";
    caption.textContent = "SQL query results";
    table.append(caption);
    const header = document.createElement("thead");
    const headerRow = document.createElement("tr");
    for (const column of message.columns) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = column;
      headerRow.append(cell);
    }
    header.append(headerRow);
    table.append(header);
    const body = document.createElement("tbody");
    for (const row of message.rows) {
      const tableRow = document.createElement("tr");
      for (const value of row) {
        const cell = document.createElement("td");
        if (value === null) {
          cell.textContent = "NULL";
          cell.className = "null-value";
        } else if (ArrayBuffer.isView(value)) {
          cell.textContent = `Binary value (${value.length} bytes)`;
        } else {
          cell.textContent = String(value);
          cell.title = String(value).slice(0, 2000);
        }
        tableRow.append(cell);
      }
      body.append(tableRow);
    }
    table.append(body);
    resultArea.append(table);
    if (!message.rows.length) {
      const empty = document.createElement("p");
      empty.className = "result-placeholder";
      empty.textContent = "The query returned no rows.";
      resultArea.append(empty);
    }
    const rows = message.rows.length;
    const timing = `${Math.max(1, Math.round(message.elapsedMs))} ms`;
    resultCount.textContent = `${rows} ${rows === 1 ? "row" : "rows"} · ${timing}`;
    status.textContent = message.truncated
      ? "Showing the first 200 rows. Add a filter or LIMIT to narrow the result."
      : `Query finished. ${rows} ${rows === 1 ? "row returned" : "rows returned"}.`;
  }

  function runQuery() {
    if (!ready || activeQueryId !== null) return;
    activeQueryId = ++nextQueryId;
    errorMessage.hidden = true;
    resultCount.textContent = "";
    status.textContent = "Running query…";
    setBusy(true);
    queryTimer = setTimeout(() => {
      placeholder("The query was stopped before a result was returned.");
      stopWorker("The query exceeded the 20 second limit. Reload the database to try a smaller query.");
    }, 20000);
    worker.postMessage({ type: "query", id: activeQueryId, query: queryEditor.value });
  }

  function inspectTable(table) {
    document.querySelector("#schema-heading").textContent = `${table.name} · ${table.type === "view" ? "read-only view" : "table"} · columns and relationships`;
    const columns = document.querySelector("#schema-columns");
    columns.replaceChildren();
    for (const [, name, type, required, , primaryKey] of table.columns) {
      const row = document.createElement("tr");
      for (const value of [name, type || "Not specified", [primaryKey ? `Primary key ${primaryKey}` : "", required ? "Required" : ""].filter(Boolean).join(" · ") || "—"]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      columns.append(row);
    }
    const relations = document.querySelector("#schema-relations");
    relations.replaceChildren();
    const groups = new Map();
    for (const [id, sequence, target, from, to] of table.foreignKeys) {
      if (!groups.has(id)) groups.set(id, { target, columns: [] });
      groups.get(id).columns.push({ sequence, from, to });
    }
    for (const relation of groups.values()) {
      const pairs = relation.columns.sort((left, right) => left.sequence - right.sequence);
      const paragraph = document.createElement("p");
      paragraph.textContent = `${pairs.map((item) => item.from).join(" + ")} → ${relation.target} (${pairs.map((item) => item.to).join(" + ")})`;
      relations.append(paragraph);
    }
    if (!groups.size) {
      const paragraph = document.createElement("p");
      paragraph.textContent = table.type === "view" ? "This view joins existing tables; it stores no additional rows or foreign keys." : "This table has no foreign keys.";
      relations.append(paragraph);
    }
    schemaInspector.hidden = false;
    schemaInspector.open = true;
  }

  function renderTables() {
    tableList.replaceChildren();
    document.querySelector("#database-table-count").textContent = tables.length;
    for (const table of tables) {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", "false");
      const name = document.createElement("span");
      name.className = "table-name";
      table.name.split("_").forEach((part, index) => {
        if (index) name.append("_", document.createElement("wbr"));
        name.append(part);
      });
      button.title = table.type === "view" ? `${table.name} · read-only view` : table.name;
      const count = document.createElement("span");
      count.className = "table-row-count";
      count.textContent = table.rowCount === null ? "view" : table.rowCount.toLocaleString("en-US");
      button.append(name, count);
      button.addEventListener("click", () => {
        for (const other of tableList.querySelectorAll("button")) other.setAttribute("aria-pressed", String(other === button));
        inspectTable(table);
        queryEditor.value = `SELECT * FROM "${table.name.replaceAll('"', '""')}"\nLIMIT 100;`;
        runQuery();
      });
      tableList.append(button);
    }
  }

  function openDatabase(autorun = true) {
    if (worker) worker.terminate();
    ready = false;
    activeQueryId = null;
    errorMessage.hidden = true;
    resetButton.hidden = true;
    setBusy(true);
    status.textContent = "Loading the read-only database…";
    worker = new Worker("/sql-worker.js?v=2");
    waitForLoadingProgress();
    worker.addEventListener("message", (event) => {
      const message = event.data;
      if (message.type === "status") {
        status.textContent = message.message;
        waitForLoadingProgress();
        return;
      }
      if (message.type === "ready") {
        clearTimeout(loadingTimer);
        ready = true;
        tables = message.tables;
        renderTables();
        setBusy(false);
        if (autorun) runQuery();
        else status.textContent = "Database reloaded. Select Run query when you’re ready.";
        return;
      }
      if (message.type === "error" && !ready) { stopWorker(message.message); return; }
      if (message.id !== activeQueryId) return;
      clearTimeout(queryTimer);
      activeQueryId = null;
      setBusy(false);
      if (message.type === "result") renderResult(message);
      if (message.type === "error") {
        if (!ready) { stopWorker(message.message); return; }
        placeholder("This query did not return a result.");
        status.textContent = "The query could not run.";
        showError(message.message);
      }
    });
    worker.addEventListener("error", () => stopWorker("The query engine could not continue. Reload the database to try again."));
    worker.postMessage({ type: "open" });
  }

  examplePicker.addEventListener("change", () => {
    queryEditor.value = examples[examplePicker.value];
    for (const button of tableList.querySelectorAll("button")) button.setAttribute("aria-pressed", "false");
    schemaInspector.hidden = true;
    status.textContent = "Example ready. Select Run query to see its result.";
    errorMessage.hidden = true;
  });
  queryEditor.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); runQuery(); }
  });
  runButton.addEventListener("click", runQuery);
  resetButton.addEventListener("click", () => openDatabase(false));
  queryEditor.value = examples.counts;
  openDatabase();
}
