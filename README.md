# OrgGraph

OrgGraph infers reporting lines from a flat list of employees. The hosted app is available on [GitHub Pages](https://meet2712.github.io/orggraph-python/), with a [browser SQL explorer](https://meet2712.github.io/orggraph-python/data.html) and an interactive [database diagram](https://meet2712.github.io/orggraph-python/schema.html).

The repository contains 500 generated companies and 87,160 employees. Job titles, departments, teams, locations and missing values are deliberately inconsistent so the inference runs against realistic input rather than pre-cleaned records.

## Approach

Python generates two independent datasets:

- `employees_messy.csv` contains the observed employee records used by the app.
- `employees_ground_truth.csv` contains the generated manager answers used only for offline evaluation.

SQLite stores two source tables: `companies` and `employees`. Headcount, company size, role classification, manager candidates, scores, decisions and audit fields are calculated by the views in [`schema.sql`](schema.sql). There is no persisted employee-to-manager mapping, so inserting or changing an employee immediately changes the relevant view results.

The inference is five views in a row:

1. `employee_role_classification` cleans the title text and reads off a level (CEO, C-Suite, VP / Head, Director, Manager, Team Lead, Senior IC, ...) and a function (Engineering, Sales, ...).
2. `employee_reporting_features` adds a role family (`software_engineering`, `data_engineering`, `quality`, `sales_smb`, ...) and, for executives, the portfolio they own. Backend, frontend and general software-development titles share the `software_engineering` family. The label is useful for consistent classification, but it is too broad to accept a reporting line by itself when team evidence is missing.
3. `employee_manager_candidates` pairs each person with everyone in the same company who holds a management title above them and shares a team, a parent team, a portfolio or a specialty.
4. `employee_manager_scores` names the first rule in `reporting_rules` that fits each pair and takes that rule's score.
5. `employee_reporting_decisions` keeps the best two candidates per person and accepts the best only when its score reaches 0.98 and leads the runner-up by 0.04. Everyone else is unresolved, with the rule and a one-line reason attached.

The Flask app reads those SQL results and renders the org chart. A company-scoped query generated from the same view definitions avoids scoring all 500 companies for each page request.

## The rules

Every reporting line in the app comes from one of these rules. The first rule that fits a pair wins, in this order. `select * from reporting_rules` returns the same table from the database.

| Rule | Score | Matches |
|---|---|---|
| `specialty_match` | 0.995 | Team is missing on one side, but the IC and the manager share a specific specialty |
| `vp_to_matching_exec` | 0.99 | VP/Head reports to the executive who owns their portfolio |
| `vp_to_ceo_no_exec` | 0.99 | VP/Head reports to the CEO because no executive owns their portfolio |
| `exec_to_ceo` | 0.995 | Executive reports to the CEO |
| `junior_to_lead` | 0.995 | Junior or intermediate IC reports to the Team Lead of the same team |
| `senior_to_manager` | 0.99 | Senior, Staff or Principal IC reports to the Manager of the same team |
| `lead_to_manager` | 0.995 | Team Lead reports to the Manager of the same team |
| `junior_to_manager` | 0.99 | Junior or intermediate IC reports to the same-team Manager; the function has no Team Lead |
| `director_to_vp` | 0.99 | Director reports to the VP/Head of the same function |
| `manager_to_director` | 0.99 | Manager reports to the Director of the same function; no Senior Manager in between |
| `manager_to_vp` | 0.99 | Manager reports to the VP/Head of the same function; no Director or Senior Manager in between |
| `next_level_up` | 0.99 | Management role reports to the next level up on the same or parent team |
| `ceo_only` | 0.45 | The CEO, who is a candidate for everyone |
| `same_team_only` | 0.90 | Same team, but no rule above applies |
| `parent_team_only` | 0.85 | Parent team, but no rule above applies |
| `same_function_only` | 0.67 | Same function, different team |
| `title_only` | 0.45 | A management title above this person, nothing else |

The last five sit below the 0.98 threshold, so they never create a line on their own. They only decide which candidate is shown as "unconfirmed" for people who stay unresolved. A shared location adds 0.002 to any score as a tie-break. The 0.995 rules outrank the 0.99 rules when both fit, and two candidates on the same rule block each other through the 0.04 margin.

## Key decisions

- Keep the messy source values unchanged and derive normalized features in views.
- Treat people management and individual-contributor seniority as separate tracks. Senior, Staff and Principal ICs do not become managers because of title seniority.
- Vary the C-suite by company size and industry rather than assigning every executive role to every company.
- Use team paths, function, leadership level and location as visible evidence for each candidate.
- Accept a manager only when the top score reaches `0.98` and leads the next candidate by at least `0.04`; otherwise leave the line unresolved.
- Give every rule a name and a fixed score, so each accepted line can be traced to one row of `reporting_rules` and the results can be reported per rule.
- Keep the answer key outside the operational database so evaluation cannot influence inference.
- Use named SQL rules instead of the earlier Python logistic model. The model reached 97.7% precision at 76.6% coverage on the same held-out companies; the rules do slightly better and every decision can be explained in one sentence.

The hierarchy policy is documented in [`docs/HIERARCHY.md`](docs/HIERARCHY.md), and [`docs/DATABASE.md`](docs/DATABASE.md) describes the tables, views and checks.

## How I worked

I built the project over three days in small, focused commits. After changing the generator or `schema.sql`, I rebuilt the database, ran the tests and dataset validation, and then reran the held-out evaluation. I kept a change only when precision remained above 98% and the rest of the pipeline still behaved as expected. GitHub Actions repeats the same checks on every push and publishes the site only after they pass.

The database and inference design were primarily my work. This is my main area of expertise, and I designed roughly 95% of the data side myself, including the schema, SQL views, hierarchy rules, thresholds and evaluation approach. I used an AI coding assistant selectively for the remaining work: reviewing edge cases, suggesting alternatives and speeding up repetitive implementation. I checked every suggestion against the hierarchy policy in [`docs/HIERARCHY.md`](docs/HIERARCHY.md) and reran the evaluation before keeping it. The results in this README come from the scripts in [`scripts/`](scripts), not from manually entered figures.

I relied more heavily on AI for the frontend because that is not my primary area. It helped create the presentation layer and org-chart interactions, while I decided what the app needed to show and reviewed the result against the brief. The frontend stays deliberately thin: it displays the reporting decisions calculated in SQL rather than applying a separate hierarchy algorithm.

The review process also helped me refine two useful additions: a queryable `reporting_rules` view, so the matching policy can be read in one place, and per-rule evaluation, so a weak rule is visible instead of being hidden inside the overall precision figure.

## Measurement

Rules were developed on companies 1–350, checked on companies 351–425, and tested on companies 426–500. The held-out set contains 13,447 employees across 75 companies. SQL accepted 10,235 reporting lines; 10,100 matched the independent answer key and 135 did not. That is **98.68% precision at 76.54% coverage**. These figures measure performance on the generated dataset and should not be treated as real-company accuracy.

Precision is correct accepted lines divided by all accepted lines. Coverage is accepted lines divided by employees who have a manager in the answer key. `scripts/evaluate_sql_inference.py` also reports both per rule; the [results page](https://meet2712.github.io/orggraph-python/results.html) shows that table. The weakest rule is `next_level_up` at 96.7% and the strongest four are at 100%.

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
| [`scripts/quality_checks.sql`](scripts/quality_checks.sql) | Check keys, cardinality, score bounds, decisions, rules and cycles |
| [`scripts/build_erd.py`](scripts/build_erd.py) | Build the database diagram from the SQLite schema |
| [`scripts/export_site.py`](scripts/export_site.py) | Export the app for GitHub Pages |

GitHub Actions runs the tests and publishes the static site. The browser SQL explorer uses a compressed, read-only snapshot of the same database.
