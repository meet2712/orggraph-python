# OrgGraph

A flat employee list rarely tells you who reports to whom. OrgGraph uses job
titles, departments, team names and location to infer those reporting lines.
Each accepted line has a confidence score. If two managers look equally
plausible, the person stays unresolved.

[Open the app](https://meet2712.github.io/orggraph-python/) ·
[Browse the database and run SQL](https://meet2712.github.io/orggraph-python/data.html) ·
[Database ER diagram](https://meet2712.github.io/orggraph-python/schema.html)

The dataset is generated: 500 companies, 88,367 employees and ten industries.
Every company has 100–250 employees. Names, emails and reporting lines are made
up; the clean hierarchy is kept separately so the predictions can be measured.

## What to look at

Pick a company and open a person in the chart. Their details show the accepted
manager, confidence, candidate gap and reasons for the match. **Needs review**
shows people without an accepted manager. **All people** includes everyone,
with accepted managers named alongside unresolved decisions.

The database page is there to make the decisions inspectable. You can look at
raw input fields, follow a manager chain, check missing data or query
`employee_reporting_audit` to see why a manager was accepted or rejected. The
ER diagram includes every column, its SQL type, primary and foreign keys, and
relationship cardinality.

The pages use the available window width. The chart can be panned and zoomed;
Fit keeps it fitted as the window changes. The ER diagram fits the page by
default, with an actual-size option for reading its columns on a small screen.

## Database choices

I used SQLite because this version has one published dataset and no editing
workflow. It keeps the app easy to run locally and lets a reviewer download the
same data they see in the portal.

There are nine tables and one read-only audit view. The main separation is:

- `companies` and `employees` hold the observed input, including messy values.
- `inference_runs` records the source and model hashes, thresholds and load counts.
- `employee_features` stores the inferred function and seniority for each run.
- `reporting_predictions` stores the accepted manager, leading candidate, scores
  and decision. A candidate is not automatically a reporting line.
- `prediction_reasons` and `company_run_metrics` hold explanations and summaries.
- `benchmark_truth` and `employee_noise` hold the generated answers and noise
  labels used to evaluate the pipeline.

Composite keys stop employee and manager references crossing companies or
runs. Score bounds, self-management, missing predictions, cycles and company
counts are checked before a load is accepted. The importer builds a staging
database and replaces the working snapshot only after the checks pass. If the
inputs have not changed, startup verifies and reuses the existing files.

`employee_reporting_audit` joins the source fields, inferred features, manager
choices and run metadata. It does not include the generated answer key.
[Database notes](docs/DATABASE.md) cover the table grains, constraints and load
process in more detail. [DATA_DICTIONARY.md](DATA_DICTIONARY.md) describes the CSVs.

The public SQL editor runs on a downloaded SQLite copy in a browser worker.
The first download is about 15 MB; progress is shown while it loads.
It accepts one read-only query, returns up to 200 rows and stops after five
seconds. There is no public server endpoint that accepts SQL. You can also
[download the snapshot](https://meet2712.github.io/orggraph-python/database/snapshot.sqlite.gz),
extract the `.gz` file and open it in a local SQLite client. That copy does not
sync changes back to the site.

## How the inference works

The generator creates a clean company structure, then adds abbreviated and
misspelled titles, conflicting department labels, missing fields and incorrect
team values. Some observed team names contain a hierarchy such as
`Engineering / Platform / Core Services`. The clean manager IDs and canonical
fields stay in a separate answer key.

The pipeline normalizes titles and infers function and seniority. It considers
more-senior management candidates in the same company, then scores each pair
with a small logistic model. Department, team scope, seniority gap, location
and missing-field signals contribute to the score. Titles such as Product
Manager and Account Manager are treated as individual contributor roles.

Training uses generated manager labels. Calibration and threshold selection
use separate validation companies. At scoring time, the model uses only the
messy observed fields; it cannot read the answer key as an input feature.

A line needs at least 45% calibrated confidence and a 10 percentage-point lead
over the next candidate. Both checks must pass. These cutoffs were chosen to
reach 95% validation precision with at least 50 accepted examples. If no pair
of cutoffs meets that target, the pipeline accepts no lines.

A person has at most one accepted manager. Managers must be more senior, which
prevents cycles. Unresolved people remain disconnected; their leading
candidate is shown only as an unconfirmed possibility.

## Results

Companies are split into 350 for training, 75 for validation and 75 for the
final test. All employees from a company stay in the same split.

| Method, on the 75 test companies | Precision | Coverage | Recall | F1 |
|---|---:|---:|---:|---:|
| Rules baseline | 92.00% | 23.10% | 21.25% | 34.53% |
| Learned pair scores | 95.43% | 67.71% | 64.61% | 77.06% |

Precision measures how many accepted lines are correct. Coverage measures how
many employees with a true manager received an accepted prediction. Recall
measures how many true reporting lines were recovered correctly.

Across all 500 companies, the published run has 58,672 accepted lines, 29,204
unresolved decisions and 491 people identified as company roots from their
observed titles. These operational counts are kept separate from the test
metrics above.

These results are for synthetic data. They do not establish accuracy on real
companies. Missing team information can leave two managers indistinguishable,
and missing titles can cause errors even at the top of a company. The app
keeps those mistakes visible in the comparison with generated answers. It
currently stores one checked snapshot; retained dataset versions and comparisons
between past runs would need a further schema change.

## Run locally

Use Python 3.11 or later.

```bash
git clone https://github.com/meet2712/orggraph-python.git
cd orggraph-python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/package-source.py
python app.py
```

Open <http://127.0.0.1:5000>. The first start imports the committed CSVs and
predictions into `instance/orggraph.sqlite3`. It does not generate a new dataset
or train a model. Request connections are read-only. The package script
refreshes the source and dataset downloads and builds the ER diagram from
`schema.sql`.

To inspect the database checks from a terminal:

```bash
sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql
```

## Hosting

The main app is on GitHub Pages. Python renders the Flask/Jinja templates at
build time and exports the company pages, browser assets and compressed SQLite
snapshot. Search, filters, person details and SQL then run in the browser.
Python is still used for generation, training, validation and page rendering;
GitHub Pages does not run a Python server.

```bash
python scripts/export_site.py --base-path /orggraph-python
```

The workflow in `.github/workflows/pages.yml` runs the checks, exports 505
pages into `dist/` and publishes them when `main` is pushed. The repository's
Pages source needs to be set to GitHub Actions.

Render is an optional way to run the same source as a Flask server.
`render.yaml` contains the settings:

```text
Build: pip install -r requirements.txt && python scripts/build_database.py && python scripts/package-source.py
Start: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --preload
Health check: /health
```

The current read-only demo does not need that server. A future upload or
inference API would need a backend. Render's free instance may sleep when idle;
its database files can be rebuilt from the committed inputs after a restart.

## Checks and regeneration

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s pipeline -p 'test_*.py'
python pipeline/validate_dataset.py --data-dir data
python pipeline/validate_outputs.py --output-dir public/data
```

The checks cover relational integrity, safe database replacement, read-only
connections, decision counts and inference thresholds. A reproducibility test
regenerates the input CSVs and compares them with the committed files.

To replace the generated inputs and fit a new model:

```bash
python pipeline/generate_dataset.py --companies 500 --min-employees 100 --max-employees 250 --seed 20261029 --output-dir data
python pipeline/train_and_infer.py --data-dir data --output-dir public/data --model-dir model
```

## Main files

| File or directory | Purpose |
|---|---|
| `app.py`, `templates/` | Flask routes and rendered pages |
| `database.py`, `schema.sql` | Import, validation, tables and SQL reads |
| `pipeline/` | Dataset generation, inference and evaluation |
| `data/`, `model/`, `public/data/` | Inputs, fitted model and published predictions |
| `public/app.js`, `public/style.css` | Browser interactions and layout |
| `public/sql-worker.js` | Browser SQLite execution and query limits |
| `scripts/build_erd.py` | ER diagram generated from the actual schema |
| `scripts/export_site.py` | Static export for hosting |
| `scripts/quality_checks.sql` | Database inspection queries |
| `tests/` | App, import and reproducibility checks |
