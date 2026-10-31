# OrgGraph

OrgGraph infers reporting lines from a flat list of employees. The hosted app is available on [GitHub Pages](https://meet2712.github.io/orggraph-python/), with a [browser SQL explorer](https://meet2712.github.io/orggraph-python/data.html) and an interactive [database diagram](https://meet2712.github.io/orggraph-python/schema.html).

The repository contains 500 generated companies and 87,160 employees. Job titles, departments, teams, locations and missing values are deliberately inconsistent so the inference runs against realistic input rather than pre-cleaned records.

## Approach

Python generates two independent datasets:

- `employees_messy.csv` contains the observed employee records used by the app.
- `employees_ground_truth.csv` contains the generated manager answers used only for offline evaluation.

SQLite stores two source tables: `companies` and `employees`. Headcount, company size, role classification, manager candidates, scores, decisions and audit fields are calculated by the views in [`schema.sql`](schema.sql). There is no persisted employee-to-manager mapping, so inserting or changing an employee immediately changes the relevant view results.

The Flask app reads those SQL results and renders the org chart. A company-scoped query generated from the same view definitions avoids scoring all 500 companies for each page request.

## Key decisions

- Keep the messy source values unchanged and derive normalized features in views.
- Treat people management and individual-contributor seniority as separate tracks. Senior, Staff and Principal ICs do not become managers because of title seniority.
- Vary the C-suite by company size and industry rather than assigning every executive role to every company.
- Use team paths, function, leadership level and location as visible evidence for each candidate.
- Accept a manager only when the top score reaches `0.98` and leads the next candidate by at least `0.04`; otherwise leave the line unresolved.
- Keep the answer key outside the operational database so evaluation cannot influence inference.
- Use transparent SQL rules instead of the retired Python candidate model, leaving one implementation to explain and test.

The hierarchy policy is documented in [`docs/HIERARCHY.md`](docs/HIERARCHY.md), and [`docs/DATABASE.md`](docs/DATABASE.md) describes the tables, views and checks.

## Measurement

Rules were developed on companies 1–350, checked on companies 351–425, and tested on companies 426–500. The held-out set contains 13,447 employees across 75 companies. SQL accepted 10,223 reporting lines; 10,087 matched the independent answer key and 136 did not. That is **98.67% precision at 76.45% coverage**. These figures measure performance on the generated dataset and should not be treated as real-company accuracy.

The evidence score is a rule-based ranking value, not a probability. Precision measures correct accepted lines divided by all accepted lines. Coverage measures accepted lines divided by employees who have a manager in the answer key.

Run the checks with:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python pipeline/validate_dataset.py --data-dir data
python scripts/check_database_views.py
python scripts/evaluate_sql_inference.py
```

## Run locally

Use Python 3.11 or later:

```bash
git clone https://github.com/meet2712/orggraph-python.git
cd orggraph-python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_database.py
python app.py
```

Open <http://127.0.0.1:5000>. The local database is `instance/orggraph.sqlite3`. The app queries its views at request time. The GitHub Pages version is a static export and changes only when the site is rebuilt and deployed.

Regenerate the dataset with:

```bash
python pipeline/generate_dataset.py --companies 500 --min-employees 100 --max-employees 250 --seed 20261029 --output-dir data
```

## Repository map

| Path | Purpose |
|---|---|
| [`pipeline/generate_dataset.py`](pipeline/generate_dataset.py) | Generate the messy source data and independent answer key |
| [`pipeline/validate_dataset.py`](pipeline/validate_dataset.py) | Validate company size, hierarchy, keys and source messiness |
| [`schema.sql`](schema.sql) | Define the source tables and live inference views |
| [`sql/company_predictions.sql`](sql/company_predictions.sql) | Run the same inference for one company |
| [`database.py`](database.py) | Load source records and query company results |
| [`app.py`](app.py), [`templates/`](templates) | Serve the Flask pages |
| [`scripts/evaluate_sql_inference.py`](scripts/evaluate_sql_inference.py) | Compare held-out SQL decisions with the answer key |
| [`scripts/quality_checks.sql`](scripts/quality_checks.sql) | Check keys, cardinality, score bounds, decisions and cycles |
| [`scripts/build_erd.py`](scripts/build_erd.py) | Build the database diagram from the SQLite schema |
| [`scripts/export_site.py`](scripts/export_site.py) | Export the app for GitHub Pages |

GitHub Actions runs the tests and publishes the static site. The browser SQL explorer uses a compressed, read-only snapshot of the same database.
