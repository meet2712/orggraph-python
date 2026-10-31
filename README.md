# OrgGraph

OrgGraph turns a flat list of employees into an inferred reporting chart. The working app is at [GitHub Pages](https://meet2712.github.io/orggraph-python/). Reviewers can [query the SQLite database](https://meet2712.github.io/orggraph-python/data.html), [follow the view dependencies](https://meet2712.github.io/orggraph-python/schema.html), and read each definition in [`schema.sql`](schema.sql).

The assessment asks for at least 500 companies with at least 100 employees each, messy job titles and missing fields, confidence on reporting lines, a hosted chart, source code and an explanation of how results were checked. This project generates 500 synthetic companies and 87,160 people. It leaves a manager unresolved when the evidence is insufficient.

## Database design

The operational SQLite file has two persisted tables:

- `companies`: company ID, name, industry and headquarters.
- `employees`: one observed row per person, including name, job title, department, team, location and email.

Employee IDs are row keys. No table stores an employee-to-manager answer or prediction mapping. `schema.sql` defines 12 SQL views. Their names describe what each query returns: a company overview, employee roles, possible managers, candidate scores, reporting decisions, and summaries. `reporting_thresholds` holds the score and margin needed to accept a line. These views recalculate when a source row changes. Adding one employee in PyCharm updates that company's headcount and the new employee's inference without editing another table or rerunning Python ETL. The Python loader rebuilds the local database only when the source files or schema change; ordinary local employee edits are preserved.

The generated answer key is [`data/employees_ground_truth.csv`](data/employees_ground_truth.csv). It is kept outside the app database and never used as an inference feature. It supports independent offline evaluation. A new manually inserted employee has no known answer until one is supplied separately; the inference view still produces a decision.

[Database notes](docs/DATABASE.md) explain each table and view. [Hierarchy policy](docs/HIERARCHY.md) explains the title ladder and individual-contributor safeguards.

The database diagram shows the two source tables and all 12 views together,
including every column. A solid line marks the company foreign key; dashed
arrows show which table or view supplies each view. Select a card to follow its
connections. The raw CSVs stay unchanged; matching happens in SQL.

## How inference works

1. Normalize a messy title and infer a function and seniority level.
2. Consider plausible, more-senior leaders within the same company. Team scope and function help distinguish candidates.
3. Score each candidate and compare the best with the second best.
4. Accept the best manager only when the evidence score and the lead over the next candidate both clear the SQL thresholds. Otherwise leave the reporting line unresolved.

The score is an interpretable rule-based evidence score, not a calibrated probability. Senior, Staff and Principal individual contributors are not automatically treated as managers. Junior employees are not automatically assigned to a Senior IC. An explicit Team Lead/Supervisor can lead the appropriate group. The expected management ladder is CEO → optional specialist C-suite → VP/Head → Director → Senior Manager → Manager → optional Team Lead/Supervisor. QA roles should stay within QA ownership when the source supports that.

The SQL for each step is inspectable in [`schema.sql`](schema.sql) or on the schema page. Flask uses [`sql/company_predictions.sql`](sql/company_predictions.sql), a company-scoped query built directly from those view definitions, so one page need not score all 500 companies. Run `python scripts/build_company_query.py` after editing the inference views; a test checks that the two stay in sync. The `employee_reporting_audit` view shows raw input, inferred features, leading candidate, selected manager, score, margin and decision reason in one query.

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

Open <http://127.0.0.1:5000>. The local SQLite database is `instance/orggraph.sqlite3`. The app queries the SQL views at request time. If you edit employees in that local file, refresh the page to see the new result. The static GitHub Pages site is an exported snapshot and changes only after a new build and deployment.

Inspect the source and views directly:

```bash
sqlite3 instance/orggraph.sqlite3 '.tables'
sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql
```

The browser SQL editor opens a read-only copy of the published database. You can [download its compressed snapshot](https://meet2712.github.io/orggraph-python/database/snapshot.sqlite.gz), decompress it and open the SQLite file in PyCharm or another SQLite client.

## Generation and checks

```bash
python pipeline/generate_dataset.py --companies 500 --min-employees 100 --max-employees 250 --seed 20261029 --output-dir data
python -m unittest discover -s tests -p 'test_*.py'
python pipeline/validate_dataset.py --data-dir data
python scripts/check_database_views.py
```

The generator writes messy observations and the separate benchmark CSV. The operational inference reads only the observations. Accuracy must be measured independently against the benchmark CSV; coverage and evidence scores alone do not establish correctness on synthetic or real companies. `pipeline/train_and_infer.py` and the older `public/data/companies/*.json` predictions remain as a historical offline experiment. The current site and SQLite reporting views do not read those prediction files; their manager decisions are calculated in SQL.

On 75 held-out generated companies (13,447 employees), the SQL rules accepted 10,223 reporting lines. Of those, 10,087 matched the separate answer CSV and 136 did not: **98.67% precision at 76.45% coverage**. These figures describe synthetic data, not accuracy on real employee records.

The latest SQL changes reduced review from 29,417 to 20,004 people across all 500 companies (33.75% to 22.95%). Every company improved; 324 are at or below 25% review and 176 are still above it. Nimbus Grid went from 89 to 55 of 234 people needing review. The source files and acceptance thresholds stayed unchanged.

The changes are small: keep a specific function such as Finance in “Financial Analyst”, recognise common abbreviations, use a clear specialist title when a team is missing, and match VPs to an explicit executive portfolio. A possible team lead still blocks a shortcut to a manager. Broad Staff/Principal titles and equally plausible candidates stay unresolved. Rules were developed on companies 1–350, checked on 351–425, then tested on 426–500.

## Hosting and files

GitHub Actions runs the checks, exports the Flask/Jinja pages, and publishes the static app to GitHub Pages. It includes a compressed SQLite snapshot for the browser SQL editor. Render can run the same Flask app, but its database is local to that deployment and is not a shared writable database.

| Path | Purpose |
|---|---|
| [`schema.sql`](schema.sql) | Source tables and all live inference views |
| [`sql/company_predictions.sql`](sql/company_predictions.sql) | Company-scoped SQL inference for app pages |
| [`database.py`](database.py) | Load source records and query the views |
| [`app.py`](app.py), [`templates/`](templates) | Flask pages |
| [`pipeline/generate_dataset.py`](pipeline/generate_dataset.py) | Synthetic source and independent answer key |
| [`scripts/quality_checks.sql`](scripts/quality_checks.sql) | Read-only integrity checks |
| [`scripts/build_erd.py`](scripts/build_erd.py) | ER diagram built from the schema |
| [`scripts/export_site.py`](scripts/export_site.py) | Static GitHub Pages export |
