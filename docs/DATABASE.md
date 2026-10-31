# Database design

The SQLite app database persists only the company directory and observed employee records. Reporting lines, scores, explanations, headcounts and coverage are calculated by SQL views over those two tables. A direct insert or edit in `employees` becomes visible on the next query; no employee-to-manager mapping table needs maintenance.

## Source tables

| Table | Grain | Stored fields |
|---|---|---|
| `companies` | One company | ID, name, industry, headquarters |
| `employees` | One observed person | Company and employee IDs, name, job title, department, team, location and email |

Employee IDs identify rows and join an employee to their company. They do **not** encode who reports to whom. `companies` has no stored employee count or size band.

There is no `run_id` in the live views. The former value `live` was only a fixed label: it did not identify a stored run or change a join. Removing it leaves the same reporting decisions and makes the schema easier to read.

## Views

| View | Calculation |
|---|---|
| `reporting_thresholds` | Minimum evidence score and lead over the next candidate needed to accept a manager |
| `company_overview` | Company details with current employee count and size band |
| `employee_role_classification` | Cleaned title and team text, inferred function and seniority |
| `employee_reporting_features` | Role specialty, executive portfolio and seniority rank used for matching |
| `employee_manager_candidates` | Possible employee–manager pairs within the same company |
| `employee_manager_scores` | Evidence score for each possible manager |
| `employee_top_manager_candidates` | Best manager and the second-best score for each employee |
| `employee_reporting_decisions` | Accepted manager or unresolved decision for each employee |
| `employee_reporting_reasons` | Readable explanation of each decision |
| `company_reporting_summary` | Accepted lines, unresolved people and coverage by company |
| `dataset_reporting_summary` | Reporting totals across all companies |
| `employee_reporting_audit` | Observed record, inferred manager and decision evidence together |

The SQL in [`schema.sql`](../schema.sql) defines all 12 views. The [schema page](../templates/schema.html) shows their columns and dependencies. The Flask page uses [`sql/company_predictions.sql`](../sql/company_predictions.sql), a company-scoped form generated from the same view definitions by `scripts/build_company_query.py`. It materializes each stage once for that company rather than repeating title parsing for every candidate. Candidate ranking is entirely in SQL. Adding an employee recalculates that employee's match and can change another employee's top candidate. A match is accepted only when the score reaches `reporting_thresholds.score_threshold` **and** its lead over the next candidate reaches `reporting_thresholds.margin_threshold`. The score is an interpretable heuristic, not a calibrated probability.

The combined diagram includes both tables and every view, with all columns.
Solid lines are foreign keys. Dashed arrows are direct SQL inputs; they are not
database constraints. Select a card to highlight the objects it reads and the
objects that read it. The dependency list is built from the saved view SQL.

Team paths are compared as literal text. A `%` or `_` in a team name is not a
wildcard, and blank or missing-team labels do not create a same-team match.
These rules apply to both the public views and the company-scoped query.
They do not edit the original job title, team or department.

A missing team can sometimes be recovered from a specific specialty: for example, a Data Engineer and the company’s Data Engineering Manager. Junior/Intermediate employees still need the closer Team Lead when that layer is visible. If two managers fit, the score gap fails and the manager stays unresolved. A broad Principal People Partner title does not identify one delivery team. Executive titles such as CTO can identify a portfolio even when their team field is missing. All of this happens in views; no cleaned field is written back to `employees`.

A quick check in PyCharm:

```sql
SELECT company_id, employee_count, size_band
FROM company_overview
WHERE company_id = 'cmp_0001';

SELECT e.full_name, e.job_title, p.accepted_manager_id, p.confidence, p.margin, p.decision
FROM employees AS e
JOIN employee_reporting_decisions AS p USING (company_id, employee_id)
WHERE e.company_id = 'cmp_0001'
LIMIT 25;
```

After an `INSERT` into `employees`, rerun these queries. Headcount, size band and reporting views update without editing `companies` or running a Python ETL job. A local edit in PyCharm affects the local database only; the published GitHub Pages site remains a fixed exported snapshot until it is rebuilt and deployed.

## Offline answer key and evaluation

[`data/employees_ground_truth.csv`](../data/employees_ground_truth.csv) contains the generated direct-manager answers. This file is an **evaluation fixture**, not an operational table or a feature used by inference. It must stay independent of predictions: deriving an answer from the model's own output would make precision self-confirming. [`scripts/evaluate_sql_inference.py`](../scripts/evaluate_sql_inference.py) compares the SQL decisions for held-out companies with this CSV outside SQLite. When a new employee is inserted, there is no benchmark answer for them until one is independently supplied; they can still receive an inferred manager immediately.

## Constraints and checks

`employees.company_id` has a foreign key to `companies.company_id`; `(company_id, employee_id)` uniquely identifies a person. The SQL inference view restricts candidate managers to the same company and requires a higher leadership level. `scripts/quality_checks.sql` checks source keys, view cardinality, score bounds, decision consistency and reporting cycles. The loader creates a new database atomically if the source files or schema change; ordinary local employee edits are preserved across app restarts.

The downloadable database is a snapshot of the published source rows and SQL views. It is not a live hosted database connection.

The summary views parse titles and score candidates in batches. Each intermediate result is calculated once per query, then the shortlist is ranked once per employee. `scripts/check_database_views.py` checks that the summaries finish within the SQL workspace’s 20-second limit and agree with the employee decisions. The company page reuses the same scoped features, so it does not parse the whole dataset for one company.
