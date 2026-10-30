-- Inspect the current imported snapshot.
-- Run with: sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql

PRAGMA foreign_keys = ON;

-- Expected: no foreign-key violations.
PRAGMA foreign_key_check;

-- Source lineage, model thresholds, and the immutable source population for the run.
SELECT
    run_id,
    source_hash,
    model_version,
    pipeline_version,
    probability_threshold,
    margin_threshold,
    source_company_count,
    source_employee_count,
    load_status,
    loaded_at
FROM inference_runs;

-- Physical tables and calculated views are visible as separate row counts.
SELECT 'table: companies' AS object_name, COUNT(*) AS row_count FROM companies
UNION ALL SELECT 'employees', COUNT(*) FROM employees
UNION ALL SELECT 'inference_runs', COUNT(*) FROM inference_runs
UNION ALL SELECT 'inference_outputs', COUNT(*) FROM inference_outputs
UNION ALL SELECT 'benchmark_labels', COUNT(*) FROM benchmark_labels
UNION ALL SELECT 'view: benchmark_truth', COUNT(*) FROM benchmark_truth
UNION ALL SELECT 'benchmark_comparison', COUNT(*) FROM benchmark_comparison
UNION ALL SELECT 'view: company_profiles', COUNT(*) FROM company_profiles
UNION ALL SELECT 'employee_features', COUNT(*) FROM employee_features
UNION ALL SELECT 'reporting_predictions', COUNT(*) FROM reporting_predictions
UNION ALL SELECT 'company_run_metrics', COUNT(*) FROM company_run_metrics
UNION ALL SELECT 'run_metrics', COUNT(*) FROM run_metrics
UNION ALL SELECT 'prediction_reasons', COUNT(*) FROM prediction_reasons
UNION ALL SELECT 'employee_noise', COUNT(*) FROM employee_noise
UNION ALL SELECT 'employee_reporting_audit', COUNT(*) FROM employee_reporting_audit;

-- Expected: the checked source population was fully scored when the run was loaded.
SELECT r.run_id
FROM inference_runs AS r
WHERE r.source_company_count <> (SELECT COUNT(*) FROM companies)
   OR r.source_employee_count <> (
       SELECT COUNT(*) FROM inference_outputs AS output WHERE output.run_id = r.run_id
   );

-- Expected: headcount is derived from employees, with at least 100 per company.
SELECT company_id, employee_count
FROM company_profiles
WHERE employee_count < 100;

-- Expected: each employee is represented once; new rows appear as pending inference.
SELECT run_id, company_id, employee_id, COUNT(*) AS prediction_count
FROM reporting_predictions
GROUP BY run_id, company_id, employee_id
HAVING COUNT(*) <> 1;

-- Expected: dynamic company metrics reconcile to live employee decisions.
SELECT metrics.run_id, metrics.company_id
FROM company_run_metrics AS metrics
JOIN company_profiles AS profile USING (company_id)
JOIN reporting_predictions AS prediction
  ON prediction.run_id = metrics.run_id
 AND prediction.company_id = metrics.company_id
GROUP BY metrics.run_id, metrics.company_id, profile.employee_count,
         metrics.resolved_count, metrics.unresolved_count
HAVING metrics.resolved_count + metrics.unresolved_count
       + sum(prediction.decision = 'company_root') <> profile.employee_count;

-- Expected: no accepted/abstained decision contradictions or invalid scores.
SELECT run_id, company_id, employee_id, decision, accepted_manager_id, best_candidate_id
FROM reporting_predictions
WHERE confidence NOT BETWEEN 0 AND 1
   OR margin NOT BETWEEN 0 AND confidence
   OR accepted_manager_id = employee_id
   OR best_candidate_id = employee_id
   OR (decision = 'accepted' AND (
       accepted_manager_id IS NULL
       OR best_candidate_id IS NULL
       OR accepted_manager_id <> best_candidate_id
   ))
   OR (decision <> 'accepted' AND accepted_manager_id IS NOT NULL)
   OR decision NOT IN ('accepted', 'unresolved', 'company_root', 'pending_inference');

-- Expected: every accepted manager has higher inferred seniority.
SELECT p.run_id, p.company_id, p.employee_id, p.accepted_manager_id
FROM reporting_predictions AS p
JOIN employee_features AS report
    ON report.run_id = p.run_id
   AND report.company_id = p.company_id
   AND report.employee_id = p.employee_id
JOIN employee_features AS manager
    ON manager.run_id = p.run_id
   AND manager.company_id = p.company_id
   AND manager.employee_id = p.accepted_manager_id
WHERE manager.inferred_rank <= report.inferred_rank;

-- Expected: no reporting cycles. Stop each walk as soon as it repeats a person.
WITH RECURSIVE reporting_walk AS (
    SELECT
        run_id, company_id, employee_id AS starting_employee_id,
        employee_id, accepted_manager_id,
        '|' || employee_id || '|' AS visited,
        0 AS cycle_found
    FROM reporting_predictions
    WHERE accepted_manager_id IS NOT NULL

    UNION ALL

    SELECT
        walk.run_id, walk.company_id, walk.starting_employee_id,
        manager.employee_id, manager.accepted_manager_id,
        walk.visited || manager.employee_id || '|',
        INSTR(walk.visited, '|' || manager.employee_id || '|') > 0
    FROM reporting_walk AS walk
    JOIN reporting_predictions AS manager
        ON manager.run_id = walk.run_id
       AND manager.company_id = walk.company_id
       AND manager.employee_id = walk.accepted_manager_id
    WHERE walk.cycle_found = 0
)
SELECT run_id, company_id, starting_employee_id, visited
FROM reporting_walk
WHERE cycle_found = 1;

-- Raw blanks/sentinels remain queryable rather than becoming display labels.
SELECT
    SUM(TRIM(job_title) = '') AS missing_titles,
    SUM(TRIM(location) = '') AS missing_locations,
    SUM(LOWER(TRIM(raw_department)) IN ('', 'n/a', 'unknown', '-')) AS missing_departments,
    SUM(LOWER(TRIM(raw_team)) IN ('', 'n/a', 'unknown', '-')) AS missing_teams
FROM employees;

-- Decisions use inferred CEO status. Benchmark roots are a separate answer key.
SELECT decision, COUNT(*) AS employees
FROM reporting_predictions
GROUP BY decision;

SELECT COUNT(*) AS generated_roots
FROM benchmark_truth
WHERE is_root = 1;

-- Example: walk the accepted manager chain for one employee.
-- Change cmp_0001 / emp_0000178 to inspect a different person.
WITH RECURSIVE manager_chain AS (
    SELECT
        run_id, company_id, employee_id, accepted_manager_id,
        0 AS depth, '|' || employee_id || '|' AS visited
    FROM reporting_predictions
    WHERE company_id = 'cmp_0001' AND employee_id = 'emp_0000178'

    UNION ALL

    SELECT
        chain.run_id, chain.company_id, manager.employee_id,
        manager.accepted_manager_id, chain.depth + 1,
        chain.visited || manager.employee_id || '|'
    FROM manager_chain AS chain
    JOIN reporting_predictions AS manager
        ON manager.run_id = chain.run_id
       AND manager.company_id = chain.company_id
       AND manager.employee_id = chain.accepted_manager_id
    WHERE INSTR(chain.visited, '|' || manager.employee_id || '|') = 0
)
SELECT chain.depth, person.full_name, person.job_title, manager.full_name AS inferred_manager
FROM manager_chain AS chain
JOIN employees AS person
    ON person.company_id = chain.company_id AND person.employee_id = chain.employee_id
LEFT JOIN employees AS manager
    ON manager.company_id = chain.company_id AND manager.employee_id = chain.accepted_manager_id
ORDER BY chain.run_id, chain.depth;

-- Example: inspect unresolved people without turning the best candidate into a manager.
SELECT
    p.company_id, person.full_name, person.job_title,
    candidate.full_name AS leading_candidate, p.confidence, p.margin
FROM reporting_predictions AS p
JOIN employees AS person
    ON person.company_id = p.company_id AND person.employee_id = p.employee_id
LEFT JOIN employees AS candidate
    ON candidate.company_id = p.company_id AND candidate.employee_id = p.best_candidate_id
WHERE p.company_id = 'cmp_0001' AND p.decision = 'unresolved'
ORDER BY p.confidence DESC, person.full_name;

-- Example: team counts using the raw input label and inferred department.
SELECT
    features.inferred_department,
    COALESCE(NULLIF(TRIM(person.raw_team), ''), '[missing]') AS input_team,
    COUNT(*) AS employees
FROM employees AS person
JOIN employee_features AS features
    ON features.company_id = person.company_id AND features.employee_id = person.employee_id
WHERE person.company_id = 'cmp_0001'
GROUP BY features.run_id, features.inferred_department, input_team
ORDER BY features.inferred_department, employees DESC, input_team;

-- Expected: accepted decisions clear the thresholds saved on their own run.
SELECT p.run_id, p.company_id, p.employee_id
FROM reporting_predictions AS p
JOIN inference_runs AS r USING (run_id)
WHERE p.decision = 'accepted'
  AND (p.confidence < r.probability_threshold OR p.margin < r.margin_threshold);
