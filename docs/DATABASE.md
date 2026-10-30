# Database design

The SQLite app database persists only the company directory and observed employee records. Reporting lines, scores, explanations, headcounts and coverage are calculated by SQL views over those two tables. A direct insert or edit in `employees` becomes visible on the next query; no employee-to-manager mapping table needs maintenance.

## Source tables

| Table | Grain | Stored fields |
|---|---|---|
| `companies` | One company | ID, name, industry, headquarters |
| `employees` | One observed person | Company and employee IDs, name, job title, department, team, location, email and source row number |

Employee IDs identify rows and join an employee to their company. They do **not** encode who reports to whom. `companies` has no stored employee count or size band.

## Views

| View | Calculation |
|---|---|
| `company_profiles` | Live employee count and size band |
| `employee_features` | Normalized function and seniority from observed titles and fields |
| `reporting_predictions` | Leading manager candidate, evidence score, lead over second place, and accepted or unresolved decision |
| `prediction_reasons` | Readable signals behind each decision |
| `company_run_metrics` | Accepted and unresolved line counts, coverage and average accepted score |
| `run_metrics` | Current totals across companies and employees |
| `employee_reporting_audit` | Raw input and derived decision side by side |
| `inference_runs` | Current SQL rule version and acceptance thresholds, as a view |

The SQL in [`schema.sql`](../schema.sql) defines all these views. The [schema page](../templates/schema.html) exposes their complete definitions. The Flask page uses [`sql/company_predictions.sql`](../sql/company_predictions.sql), a company-scoped form of the same inference logic so it does not evaluate all 500 companies for one page. Candidate ranking is entirely in SQL. Adding an employee recalculates that employee's match and can change another employee's top candidate. A match is accepted only when the score reaches the threshold **and** its lead over the next candidate is large enough. The score is an interpretable heuristic, not a calibrated probability.

A quick check in PyCharm:

```sql
SELECT company_id, employee_count, size_band
FROM company_profiles
WHERE company_id = 'cmp_0001';

SELECT e.full_name, e.job_title, p.accepted_manager_id, p.confidence, p.margin, p.decision
FROM employees AS e
JOIN reporting_predictions AS p USING (company_id, employee_id)
WHERE e.company_id = 'cmp_0001'
LIMIT 25;
```

After an `INSERT` into `employees`, rerun these queries. Headcount, size band and reporting views update without editing `companies` or running a Python ETL job. A local edit in PyCharm affects the local database only; the published GitHub Pages site remains a fixed exported snapshot until it is rebuilt and deployed.

## Offline answer key and evaluation

[`data/employees_ground_truth.csv`](../data/employees_ground_truth.csv) contains the generated direct-manager answers. This file is an **evaluation fixture**, not an operational table or a feature used by inference. It must stay independent of predictions: deriving an answer from the model's own output would make precision self-confirming. [`scripts/evaluate_sql_inference.py`](../scripts/evaluate_sql_inference.py) compares the SQL decisions for held-out companies with this CSV outside SQLite. When a new employee is inserted, there is no benchmark answer for them until one is independently supplied; they can still receive an inferred manager immediately.

## Constraints and checks

`employees.company_id` has a foreign key to `companies.company_id`; `(company_id, employee_id)` uniquely identifies a person. The SQL inference view restricts candidate managers to the same company and requires a higher leadership level. `scripts/quality_checks.sql` checks source keys, view cardinality, score bounds, decision consistency and reporting cycles. The loader creates a new database atomically if the source files or schema change; ordinary local employee edits are preserved across app restarts.

The downloadable database is a snapshot of the published source rows and SQL views. It is not a live hosted database connection.
