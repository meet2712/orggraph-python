# Dataset columns

Start with `employees_messy.csv` for inference. The other employee file is the
answer key: it lets us measure whether a suggested manager is right.

## `companies.csv`

| Column | Meaning |
|---|---|
| `company_id` | Stable synthetic company key. |
| `company_name` | Synthetic company name. |
| `industry` | Industry used to vary the department mix. |
| `size_band` | Generation-time size category used to shape the synthetic hierarchy. In SQLite, the current value is recalculated by `company_overview`. |
| `employee_count` | Generation-time reconciliation count. It is not stored on the SQLite `companies` table; `company_overview` counts current employee rows. |
| `headquarters` | Synthetic headquarters location. |

## `employees_messy.csv`

This is the employee list the model uses. Titles and other fields contain
inconsistent formatting, abbreviations, typos, and missing values. Blank
values and labels such as `N/A`, `Unknown`, or `-` mean information is missing.

| Column | Meaning |
|---|---|
| `employee_id` | Stable employee key. |
| `company_id` | Employee's company. |
| `full_name` | Synthetic name. |
| `job_title` | Noisy title; can be blank. |
| `department` | Department; may be abbreviated, wrong, or missing. |
| `team` | Observed team path, such as `Engineering / Platform / Core Services`; may have inconsistent case or spacing, be wrong, or be missing. A slash-separated path can reveal parent-unit scope without naming a manager. |
| `location` | Location; can be missing. |
| `work_email` | Synthetic `.example` address, never a real contact. |

## `employees_ground_truth.csv`

This is the clean answer key used for training and evaluation. The model sees
the noisy `team` value from `employees_messy.csv`, not this file's canonical
team or manager ID. Its manager and canonical fields are never input features
when the model scores a reporting line.

| Column | Meaning |
|---|---|
| `employee_id` | Stable employee key. |
| `company_id` | Employee's company. |
| `full_name` | Synthetic name. |
| `canonical_title` | Clean generated title. |
| `canonical_department` | True department. |
| `canonical_team` | Clean team label, kept in the answer key. |
| `canonical_level` | True level on the management or IC track; see `docs/HIERARCHY.md`. |
| `manager_employee_id` | True direct manager; blank only for the CEO/root. |
| `is_people_manager` | `1` when the employee has direct reports. |
| `noise_profile` | Changes applied to the title, used to compare results for different kinds of messy input. |

## `reporting_edges.csv`

The answer key as one row per true reporting line. CEOs have no manager, so
there is no row for them in this file.

| Column | Meaning |
|---|---|
| `company_id` | Company key. |
| `employee_id` | Direct report. |
| `manager_employee_id` | True direct manager. |

