# OrgGraph

OrgGraph turns a flat employee list into a possible org chart. Pick a company,
look through its reporting lines, and check the confidence behind each one.
When the evidence is weak, the manager stays unresolved.

Live app: <https://orggraph-python.onrender.com>.

The results below describe the generated files in this checkout. The hosted
app may show an earlier build until it is redeployed.

The app is written in Python with Flask, SQLite, and Jinja templates. A small
JavaScript file handles search, filters, and person details in the browser.
There is no React build or Node dependency.

## Task coverage

| Requirement | What to inspect |
|---|---|
| At least 500 companies, 100+ employees each | 500 companies, 88,367 employees; size range 100–250. The dataset validator checks every company. |
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
again with unchanged source, model, schema, and importer files reuses the
checked database and compressed download. File digests, ready counts, and a
SQLite quick check are verified once at startup, outside request handling.

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

The package script refreshes both the dataset and source ZIP downloads.

Open <http://127.0.0.1:5000>. The first start imports the included employee CSVs
and predictions into `instance/orggraph.sqlite3`. Later starts reuse that
checked snapshot; stale or damaged files trigger a fresh staged import. It
does not generate data or train a model. Each request reads the selected
company using its own read-only connection. This version does not save edits.

The main routes are `/`, `/companies/cmp_0001.html`, `/results.html`,
`/approach.html`, and `/data.html`. `/health` checks that the app and database
are ready. `/database/snapshot.sqlite.gz` provides the synthetic database copy
used by the browser SQL editor.

## Deploy the Python app on Render

The source repository is <https://github.com/meet2712/orggraph-python>.
Create a Python web service in Render and connect that repository. The included
`render.yaml` records the service settings. For a manual setup, use:

```text
Build command: pip install -r requirements.txt && python scripts/build_database.py && python scripts/package-source.py
Start command: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --preload
Health check path: /health
```

The build prepares SQLite and its compressed download before Gunicorn starts.
Preloading verifies and reuses those checked files before workers serve
requests. Render's free services sleep when idle and use an ephemeral
filesystem. If the files are absent or stale, the app rebuilds them from the
committed sources. The first visit after sleeping may take longer.

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
`dist/`, then copies the browser assets and downloads. It creates fresh dataset
and source downloads before exporting, including when run from an extracted source ZIP.
Filtering, person details, and read-only SQL work in the browser. The full
Flask source is included separately.

For GitHub Pages, export under the repository path:

```bash
python scripts/export_site.py --base-path /orggraph-python
```

The Pages workflow validates the data and app, exports the site, then publishes
`dist/` when `main` is pushed. Set the repository's Pages source to **GitHub
Actions** before its first deployment. The published Pages site is a static
copy; the Render service above runs the Python app.

## How the inference works

The dataset is synthetic: 500 companies, 88,367 employees, ten industries, and
100–250 people per company. Names, email addresses, and reporting lines are
made up. The `.example` email addresses cannot receive mail.

The generator first creates a clean company structure. The observed team field
can show a path such as `Engineering / Platform / Core Services`, which gives
the model evidence about team scope. It then adds abbreviated titles, typos,
conflicting departments, and missing or incorrect teams and other fields.
The clean manager IDs and canonical fields stay in a separate answer key.

The inference pipeline has four main steps:

1. Normalize case, punctuation, common abbreviations, and regional suffixes in
   titles; infer each person's function and seniority. Titles such as Product
   Manager and Account Manager remain individual contributor roles.
2. Shortlist more-senior people in the same company with a management title or
   equivalent rank. Senior individual contributors are not assumed to manage
   people. Team paths help identify a same-team manager or a parent unit when
   that field is present.
3. Score each employee–manager pair with a small logistic model. Inputs include
   the observed team and department, seniority gap, missing-field signals, and
   location.
4. Keep a reporting line only when its confidence is high enough and the best
   candidate is clearly ahead of the next one.

The model learns from candidate pairs in training companies. It then calibrates
the leading candidate's score using one top-choice example per employee in the
validation companies. Confidence and lead-over-runner-up thresholds are chosen
to reach at least 95% precision there, with at least 50 accepted examples. The
selected cutoffs are 45% calibrated confidence and a 10 percentage-point lead;
both must pass. If no pair of thresholds meets the precision target, the
pipeline accepts no links.

Every accepted employee has one manager. Managers must be more senior and
belong to the same company, which also prevents cycles. The chart uses only
accepted predictions. A leading candidate or a generated answer never becomes
a chart edge on its own.

## How it was measured

Companies are split into 350 for training, 75 for validation, and 75 for the
final test. Everyone from a company stays in the same split. The model sees
only the observed messy fields when scoring a pair. The answer key supplies
training labels and evaluation, never manager IDs or canonical fields as
scoring features.

These results are from the 75 test companies:

| Method | Precision | Coverage | Recall | F1 |
|---|---:|---:|---:|---:|
| Rules alone | 92.00% | 23.10% | 21.25% | 34.53% |
| Learned pair scores | 95.43% | 67.71% | 64.61% | 77.06% |

Precision asks: of the reporting lines we accepted, how many were right?
Coverage asks: for how many employees who have a manager did we accept one?
Recall asks: how many of all the true reporting lines did we recover?

The learned scores accept about 2.9 times as many links as the rules baseline
while keeping precision above 95% on the test split. The shortlist contains the
true manager for 99.23% of test employees who have a manager. Across all 500
companies, 58,672 reporting lines are accepted and 29,195 remain unresolved.
For Nimbus Grid, 159 of 233 possible lines are accepted, 74 are unresolved,
and 97.48% of accepted lines match the generated answer. The stricter threshold
leaves more people without a manager rather than adding weak reporting lines.
All exported charts pass checks for cycles, cross-company links, and links to
someone with the same or lower inferred seniority.

These figures measure recovery of generated reporting lines. They do not
establish accuracy on real companies. Two managers can look identical when
team or title information is missing, so some lines remain unresolved.

## Source files

```text
app.py                       Flask routes, SQLite import, and chart context
database.py                  Relational load, validation, and SQL reads
schema.sql                   Tables, keys, checks, and indexes
scripts/build_database.py     Prepares checked database files during deployment
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
