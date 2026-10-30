-- Read-only checks for the current source rows and derived inference views.
-- Run with: sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql

PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;

-- Only the two source tables should be persisted.
SELECT type, name FROM sqlite_master
WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
ORDER BY type, name;

SELECT 'companies' AS object_name, count(*) AS row_count FROM companies
UNION ALL SELECT 'employees', count(*) FROM employees
UNION ALL SELECT 'company_profiles', count(*) FROM company_profiles
UNION ALL SELECT 'reporting_predictions', count(*) FROM reporting_predictions;

-- Expected: zero rows. Company count and size band are calculated from employees.
SELECT c.company_id, c.employee_count, count(e.employee_id) AS actual_count
FROM company_profiles AS c LEFT JOIN employees AS e USING (company_id)
GROUP BY c.company_id, c.employee_count
HAVING c.employee_count <> count(e.employee_id);

-- Expected: zero rows. Every observed employee has exactly one live decision.
SELECT e.company_id, e.employee_id, count(p.employee_id) AS prediction_rows
FROM employees AS e LEFT JOIN reporting_predictions AS p USING (company_id, employee_id)
GROUP BY e.company_id, e.employee_id
HAVING count(p.employee_id) <> 1;

-- Expected: zero rows. Accepted edges must name the leading candidate and stay in company.
SELECT p.company_id, p.employee_id, p.accepted_manager_id, p.best_candidate_id,
       p.confidence, p.margin, p.decision
FROM reporting_predictions AS p
LEFT JOIN employees AS m ON m.company_id = p.company_id
    AND m.employee_id = p.accepted_manager_id
WHERE p.confidence NOT BETWEEN 0 AND 1
   OR p.margin NOT BETWEEN 0 AND p.confidence
   OR p.accepted_manager_id = p.employee_id
   OR p.best_candidate_id = p.employee_id
   OR (p.decision = 'accepted' AND (
       p.accepted_manager_id IS NULL OR p.accepted_manager_id <> p.best_candidate_id
       OR m.employee_id IS NULL))
   OR (p.decision <> 'accepted' AND p.accepted_manager_id IS NOT NULL);

-- Expected: zero rows. Every accepted manager has a higher leadership rank.
SELECT p.company_id, p.employee_id, p.accepted_manager_id
FROM reporting_predictions AS p
JOIN employee_features AS report USING (company_id, employee_id)
JOIN employee_features AS manager ON manager.company_id = p.company_id
    AND manager.employee_id = p.accepted_manager_id
WHERE manager.inferred_rank <= report.inferred_rank;

-- Expected: zero rows. Strictly higher rank should prevent cycles.
WITH RECURSIVE walk AS (
    SELECT company_id, employee_id AS start_id, employee_id,
           accepted_manager_id, '|' || employee_id || '|' AS path, 0 AS cycle
    FROM reporting_predictions WHERE accepted_manager_id IS NOT NULL
    UNION ALL
    SELECT w.company_id, w.start_id, p.employee_id, p.accepted_manager_id,
           w.path || p.employee_id || '|',
           instr(w.path, '|' || p.employee_id || '|') > 0
    FROM walk AS w JOIN reporting_predictions AS p
      ON p.company_id = w.company_id AND p.employee_id = w.accepted_manager_id
    WHERE w.cycle = 0
)
SELECT company_id, start_id, path FROM walk WHERE cycle = 1;

-- Source fields remain messy rather than being overwritten by display labels.
SELECT sum(trim(job_title) = '') AS missing_titles,
       sum(trim(location) = '') AS missing_locations,
       sum(lower(trim(raw_department)) IN ('', 'n/a', 'unknown', '-')) AS missing_departments,
       sum(lower(trim(raw_team)) IN ('', 'n/a', 'unknown', '-')) AS missing_teams
FROM employees;

SELECT decision, count(*) AS employees FROM reporting_predictions GROUP BY decision;

-- Expected: zero rows. The published acceptance thresholds come from the SQL view.
SELECT p.company_id, p.employee_id FROM reporting_predictions AS p
CROSS JOIN inference_runs AS r
WHERE p.decision = 'accepted'
  AND (p.confidence < r.probability_threshold OR p.margin < r.margin_threshold);

-- Example: inspect one employee's live manager chain.
WITH RECURSIVE manager_chain AS (
    SELECT company_id, employee_id, accepted_manager_id, 0 AS depth
    FROM reporting_predictions
    WHERE company_id = 'cmp_0001' AND employee_id = 'emp_0000178'
    UNION ALL
    SELECT p.company_id, p.employee_id, p.accepted_manager_id, chain.depth + 1
    FROM manager_chain AS chain JOIN reporting_predictions AS p
      ON p.company_id = chain.company_id AND p.employee_id = chain.accepted_manager_id
    WHERE chain.depth < 12
)
SELECT chain.depth, e.full_name, e.job_title, m.full_name AS inferred_manager
FROM manager_chain AS chain
JOIN employees AS e USING (company_id, employee_id)
LEFT JOIN employees AS m ON m.company_id = chain.company_id
    AND m.employee_id = chain.accepted_manager_id
ORDER BY chain.depth;
