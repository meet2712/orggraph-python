# OrgGraph

OrgGraph turns a flat employee list into a possible org chart. Pick a company,
look through its reporting lines, and check the confidence behind each one.
When the evidence is weak, the manager stays unresolved.

Live app: <https://orggraph-python.onrender.com>.

The app is written in Python with Flask, SQLite, and Jinja templates. A small
JavaScript file handles search, filters, and person details in the browser.
There is no React build or Node dependency.

## Task coverage

| Requirement | What to inspect |
|---|---|
| At least 500 companies, 100+ employees each | 500 companies, 87,873 employees; size range 100–250. The dataset validator checks every company. |
| Realistic titles, functions, industries, and messy fields | Ten industries; abbreviated and misspelled titles, missing fields, and conflicting labels. Raw fields are preserved in `employees`. |
| Infer reporting lines with confidence | `reporting_predictions` stores the accepted manager, leading candidate, confidence, margin, and decision for each person and run. |
| Leave uncertain managers unresolved | The model uses both confidence and candidate separation. Unknown links remain disconnected in the chart. |
| Working hosted company explorer | The live app lets a reviewer choose a company, navigate its chart, and inspect each decision. |
| Source, generator, and a short account of decisions and measurement | The generator and inference pipeline are in `pipeline/`; this README covers the approach and results; `docs/DATABASE.md` covers the data model. |

## Inspect the data

The Database & SQL page shows the real tables, their keys, row counts, and
relationships. Examples cover dataset counts, accepted matches, unresolved
people, missing source fields, manager chains, and load lineage.

Queries run on a downloaded SQLite copy inside a browser worker. The editor
accepts one read-only query at a time, returns at most 200 rows, and stops a
query after five seconds. Writes and schema changes are blocked. There is no
server endpoint that accepts user SQL, and ordinary app connections use
SQLite read-only mode. This keeps a public demo separate from data loading.

## Database design

SQLite stores the data in relational tables rather than one JSON document per
company. Raw employee records, inferred features, manager predictions, and the
generated answer key stay separate. Composite foreign keys keep employee,
manager, and candidate links inside the same company and inference run.

Each load records source and model hashes, thresholds, row counts, and a ready
status. The importer builds and checks a staging database before replacing the
previous snapshot. Failed loads leave the previous database intact. Starting
again with the same files preserves the same keys, run ID, and query results.

The app reconstructs its company pages with SQL joins. Request connections are
read-only. The database page lets reviewers inspect tables and run read-only
SQL against a downloaded browser copy; it cannot change the server database.

See [the database notes](docs/DATABASE.md) for the table grains, relationship
diagram, load checks, and limitations. To run the inspection queries locally:

```bash
sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql
```

## Run it locally

Use Python 3.11 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/package-source.py
python app.py
```

Open <http://127.0.0.1:5000>. On startup, the app imports the included employee
CSVs and prediction files into `instance/orggraph.sqlite3`. It does not generate
data or train a model. Each request reads the selected company from SQLite
using its own connection. The database is rebuilt from the saved source files
when the app starts; this version does not save user edits.

The main routes are `/`, `/companies/cmp_0001.html`, `/results.html`,
`/approach.html`, and `/data.html`. `/health` checks that the app and database
are ready. `/database/snapshot.sqlite.gz` provides the synthetic database copy
used by the browser SQL editor.

## Deploy the Python app on Render

The source repository is <https://github.com/meet2712/orggraph-python>.
Create a Python web service in Render and connect that repository. The included
`render.yaml` records the service settings. For a manual setup, use:

```text
Build command: pip install -r requirements.txt && python scripts/package-source.py
Start command: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --preload
Health check path: /health
```

Preloading initializes SQLite before Gunicorn starts serving requests. Render's
free services sleep when idle and use an ephemeral filesystem. That is fine
for this read-only app: startup rebuilds SQLite from the committed prediction
files. The first visit after sleeping may take longer.

Render's setup guide: <https://render.com/docs/deploy-flask>.
Free service behavior: <https://render.com/docs/free>.

## Export static pages

The same Flask templates can be exported as HTML for static hosting. This
export includes the chart and a compressed database snapshot for browser SQL.
It does not run a Python server; use the deployment instructions above for
the full Flask app. To create the static pages:

```bash
python scripts/export_site.py
```

This renders the home page, all 500 company pages, results, approach, and database explorer into
`dist/`, then copies the browser assets and downloads. It creates a fresh source
download before exporting, including when run from an extracted source ZIP.
Filtering, person details, and read-only SQL work in the browser. The full
Flask source is included separately.

## How the inference works

The dataset is synthetic: 500 companies, 87,873 employees, ten industries, and
100–250 people per company. Names, email addresses, and reporting lines are
made up. The `.example` email addresses cannot receive mail.

The generator first creates a clean company structure. It then adds abbreviated
titles, typos, conflicting departments, and missing titles, teams, or locations.
The clean structure is kept separately as an answer key.

The inference pipeline has four main steps:

1. Read the messy titles and infer each person's function and seniority.
2. Shortlist more-senior people in the same company, using team and department
   matches where available.
3. Score each employee–manager pair with a small logistic model. Inputs include
   team, department, seniority gap, and location.
4. Keep a reporting line only when its confidence is high enough and the best
   candidate is clearly ahead of the next one.

Confidence is adjusted against validation examples so the scores better match
observed correctness. The acceptance threshold is chosen to reach at least
92% precision on validation companies. If no threshold meets that target with
at least 50 accepted examples, the pipeline accepts no links.

Every accepted employee has one manager. Managers must be more senior and
belong to the same company, which also prevents cycles. The chart uses only
accepted predictions. A leading candidate or a generated answer never becomes
a chart edge on its own.

## How it was measured

Companies are split into 350 for training, 75 for validation, and 75 for the
final test. Everyone from a company stays in the same split. The model sees
only the messy fields when scoring a pair; the answer key is used for training
labels and evaluation.

These results are from the 75 test companies:

| Method | Precision | Coverage | Recall | F1 |
|---|---:|---:|---:|---:|
| Rules alone | 90.81% | 12.66% | 11.49% | 20.41% |
| Learned pair scores | 91.63% | 37.37% | 34.24% | 49.85% |

Precision asks: of the reporting lines we accepted, how many were right?
Coverage asks: for how many employees who have a manager did we accept one?
Recall asks: how many of all the true reporting lines did we recover?

The learned scores accept nearly three times as many links while keeping
precision above 90% on the test split. The shortlist contains the true manager
for 89.39% of test employees who have a manager. All exported charts pass checks
for cycles, cross-company links, and links to someone with the same or lower
inferred seniority.

These figures measure recovery of generated reporting lines. They do not
establish accuracy on real companies. Two managers can look identical when
team or title information is missing, so some lines remain unresolved.

## Source files

```text
app.py                       Flask routes, SQLite import, and chart context
database.py                  Relational load, validation, and SQL reads
schema.sql                   Tables, keys, checks, and indexes
requirements.txt             Python dependencies
templates/index.html         Pages and reusable person/chart markup
public/style.css             Page styles
public/app.js                Browser search, filters, and dialogs
public/data/                 Saved predictions for each company
public/downloads/            Downloadable data and source
scripts/export_site.py       Exports Flask pages as static HTML
tests/test_app.py             Backend and no-guessing checks
scripts/quality_checks.sql    Data-quality and exploration queries
docs/DATABASE.md              Table grains, relationships, and lineage
data/                        Generated employee lists and answer key
model/model.json             Fitted weights and acceptance thresholds
pipeline/generate_dataset.py Dataset generator
pipeline/train_and_infer.py  Inference, training, and evaluation
pipeline/validate_dataset.py Checks the generated dataset
pipeline/validate_outputs.py Checks every exported chart
pipeline/test_thresholds.py  Checks that weak evidence stays unresolved
DATA_DICTIONARY.md           What each dataset column means
```

## Run the checks

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s pipeline -p 'test_*.py'
python pipeline/validate_dataset.py --data-dir data
python pipeline/validate_outputs.py --output-dir public/data
```

To regenerate the dataset and predictions, run:

```bash
python pipeline/generate_dataset.py --companies 500 --min-employees 100 --max-employees 250 --seed 20261029 --output-dir data
python pipeline/train_and_infer.py --data-dir data --output-dir public/data --model-dir model
```

For real employee data, useful next additions would be verified manager
examples, changes over time, and a way for reviewers to correct a reporting
line. Those would add evidence the current title-based system does not have.
