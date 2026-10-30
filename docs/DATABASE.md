# Database design

SQLite is enough for this read-only assessment: one portable file, explicit SQL,
foreign-key constraints and the same snapshot in the Flask app and browser SQL
workspace. The design keeps persisted facts small and puts deterministic
transformations in views so their logic is inspectable.

## Persisted tables

| Table | One row represents | Why it is persisted |
|---|---|---|
| `companies` | One company master record. | Name, industry and headquarters are source attributes. |
| `employees` | One observed employee in a company. | These are the messy input fields used by inference. |
| `benchmark_labels` | One generated source label per employee. | Known answers and injected-noise metadata are fixed source facts, separate from model input and output. |
| `inference_runs` | One checked source/model run. | Hashes and thresholds are immutable lineage for a reproducible run. |
| `inference_outputs` | One model decision per employee/run. | Features, candidate scores and explanations are the durable output of model execution. |

`companies` intentionally has no `employee_count` or `size_band` column. Both
depend on the current employee population and therefore belong in a view.

## Dynamic views

| View | What it calculates |
|---|---|
| `benchmark_truth` | The answer-key shape from source labels; `is_root` is calculated from whether the known manager is null. |
| `benchmark_comparison` | A live side-by-side comparison of each prediction and its known answer, with `correct`, `incorrect`, `not_accepted` or `unlabeled` status. |
| `company_profiles` | Current employee count and size band from `employees`. |
| `employee_features` | Inferred function, seniority and processing status for every employee/ready run. |
| `reporting_predictions` | Accepted manager, leading candidate, confidence, margin and decision. |
| `prediction_reasons` | One ordered reason per decision by expanding `reasons_json`. |
| `employee_noise` | One noise label per generated employee by expanding the benchmark metadata. |
| `company_run_metrics` | Resolved/unresolved counts, coverage, precision and average accepted confidence. |
| `run_metrics` | Current company, employee, accepted, unresolved, pending and average-confidence totals for a run. |
| `employee_reporting_audit` | Raw fields, features, manager choices, thresholds and an auditable decision reason. |

The complete `CREATE VIEW` queries are in [`schema.sql`](../schema.sql) and are
also displayed on the portal's Database schema page.

### Example: live company headcount

```sql
CREATE VIEW company_profiles AS
SELECT
    c.company_id,
    c.company_name,
    c.industry,
    CASE
        WHEN count(e.employee_id) < 130 THEN 'Small'
        WHEN count(e.employee_id) < 180 THEN 'Growth'
        ELSE 'Mid-market'
    END AS size_band,
    count(e.employee_id) AS employee_count,
    c.headquarters
FROM companies AS c
LEFT JOIN employees AS e USING (company_id)
GROUP BY c.company_id, c.company_name, c.industry, c.headquarters;
```

If one employee is inserted, `employee_count` and `size_band` immediately
recalculate. No company row or saved metric needs to be updated.

### Example: live company metrics

`company_run_metrics` aggregates employee-level decisions. Resolved count is
the number of accepted edges. Unresolved count includes explicit abstentions and
new employees still waiting for inference. Coverage divides accepted edges by
non-root employees. Precision counts only accepted edges with a generated label,
using `benchmark_comparison`; an unlabeled new employee is not counted as wrong.
Average confidence uses accepted edges only.

This distinction is important: the view is dynamic, but it does not pretend to
run a Python model inside SQLite. A new employee appears immediately with
`processing_status = 'pending_inference'`; the inference pipeline must still
produce that employee's scored output before an edge can be accepted.

## Input, model output and benchmark remain separate

Blank titles, departments, teams and locations stay blank in `employees`.
Display labels such as “Title unavailable” are added when the page payload is
constructed, never written over the raw fields. `source_row_number` preserves
the original CSV order.

`inference_outputs` is imported from the checked prediction files. A decision
can be `accepted`, `unresolved` or `company_root`; only an accepted manager
creates a chart edge. The views add `pending_inference` when a raw employee has
no output for a ready run.

`benchmark_labels` imports the generator's separate answer file. These labels
must stay fixed: deriving the "truth" from the model's own prediction would
make accuracy self-confirming. `benchmark_truth` and `benchmark_comparison` are
views, so root status and prediction-versus-answer mapping are calculated in
inspectable SQL. The model never uses benchmark labels to choose a manager.

## Constraints and validation

- Composite employee keys include `company_id`; manager and candidate foreign
  keys cannot cross companies.
- `inference_outputs` permits one output per employee/run.
- Confidence and margin are constrained to `[0, 1]`, with margin no greater than
  confidence. Self-management is rejected.
- An accepted decision must use its leading candidate as the accepted manager.
- Startup validates foreign keys, row counts, threshold compliance, reporting
  cycles, seniority and dynamic-view reconciliation before replacing the prior
  snapshot.
- The import runs in a staging file inside a transaction. Failure leaves the
  previous database untouched.

The current checked source contains 500 companies, 87,160 employees, 66,793
accepted reporting lines and 19,883 unresolved decisions. Data-shape checks are
separate from model quality: a valid foreign key does not prove that an inferred
reporting line is correct.

## Lineage and rebuilding

`inference_runs` stores the source hash, model hash, pipeline hash, thresholds,
source population, status and load time. The stable run key is derived from the
full source fingerprint. Source counts describe what the model saw; live counts
come from the views.

`scripts/build_database.py` prepares the checked database and compressed
download. Unchanged startup verifies and reuses the snapshot. Changed or damaged
artifacts trigger an atomic rebuild. This take-home publishes one current
snapshot; retaining changing source versions would require a dataset/version key.

## Inspect it

The `/data.html` page runs read-only SQL in the browser. The `/schema.html` page
shows the physical ER diagram, every derived view and the complete SQL definition
for each view. The downloadable snapshot is `/database/snapshot.sqlite.gz`.

From the repository:

```bash
sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql
```

The quality script checks lineage, row grains, foreign keys, dynamic headcounts,
decision cardinality, metric reconciliation, score bounds, seniority, cycles and
threshold compliance. Queries that look for invalid records should return no
rows.
