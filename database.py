"""Build the SQLite file from the CSVs and read company pages out of the views."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parent
COMPANY_PREDICTIONS_SQL = (ROOT / "sql" / "company_predictions.sql").read_text(
    encoding="utf-8"
).strip().removesuffix(";")
# Everything up to the final select, so read_company can add its own CTEs.
COMPANY_INFERENCE_CTES = COMPANY_PREDICTIONS_SQL.removesuffix(
    "\nselect * from employee_reporting_decisions"
)


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("pragma query_only = on")
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


def write_compressed_snapshot(database: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".snapshot-", dir=destination.parent, delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        with database.open("rb") as source, gzip.open(staging, "wb") as target:
            shutil.copyfileobj(source, target)
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def read_employee_csv(path: Path) -> dict:
    records = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            key = (row["company_id"], row["employee_id"])
            if key in records:
                raise ValueError(f"Duplicate employee in {path.name}: {key}")
            records[key] = row
    return records


def read_company_csv(path: Path) -> list[dict[str, str]]:
    records = []
    seen = set()
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            company_id = row["company_id"]
            if company_id in seen:
                raise ValueError(f"Duplicate company in {path.name}: {company_id}")
            seen.add(company_id)
            records.append(row)
    return records


def source_fingerprint(raw_dir: Path) -> str:
    """Hash of the two source CSVs and schema.sql; a change to any of them rebuilds the database."""
    digest = hashlib.sha256()
    for path in (raw_dir / "companies.csv", raw_dir / "employees_messy.csv", ROOT / "schema.sql"):
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def database_is_current(database: Path, fingerprint: str) -> bool:
    """True when the file was built from these sources and still passes a quick check."""
    try:
        manifest = read_json(database.with_suffix(".manifest.json"))
        if manifest["source_hash"] != fingerprint:
            return False
        with closing(connect(database, readonly=True)) as connection:
            return connection.execute("pragma quick_check(1)").fetchone()[0] == "ok"
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return False


def prepare_database(database: Path, snapshot: Path, raw_dir: Path,
                     companies: list[dict[str, str]], employee_count: int) -> bool:
    """Build the database if the sources changed, then refresh the gzipped copy
    if the database is newer than it. Returns True when the file was reused."""
    fingerprint = source_fingerprint(raw_dir)
    reused = database_is_current(database, fingerprint)
    if not reused:
        build_database(database, raw_dir, companies, employee_count)
        manifest = database.with_suffix(".manifest.json")
        manifest.write_text(json.dumps({"source_hash": fingerprint}), encoding="utf-8")
    if not snapshot.exists() or snapshot.stat().st_mtime < database.stat().st_mtime:
        write_compressed_snapshot(database, snapshot)
    return reused


def build_database(database: Path, raw_dir: Path, companies: list[dict[str, str]],
                   employee_count: int) -> None:
    """Load the CSVs and schema.sql into a new file, then swap it into place."""
    raw = read_employee_csv(raw_dir / "employees_messy.csv")
    if len(raw) != employee_count:
        raise ValueError("Raw employee count does not match the dataset summary")
    company_ids = [company["company_id"] for company in companies]
    database.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".orggraph-load-", suffix=".sqlite3", dir=database.parent, delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        with closing(connect(staging)) as connection:
            connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
            with connection:
                connection.executemany(
                    "insert into companies values (?, ?, ?, ?)",
                    [(row["company_id"], row["company_name"], row["industry"],
                      row["headquarters"]) for row in companies],
                )
                connection.executemany(
                    "insert into employees values (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(row["company_id"], row["employee_id"], row["full_name"], row["job_title"],
                      row["department"], row["team"], row["location"], row["work_email"])
                     for row in raw.values()],
                )
                check_loaded_database(connection, len(company_ids), len(raw))
        os.replace(staging, database)
    finally:
        staging.unlink(missing_ok=True)


def check_loaded_database(connection, company_count, employee_count):
    counts = [connection.execute(f"select count(*) from {table}").fetchone()[0]
              for table in ("companies", "employees")]
    if counts != [company_count, employee_count]:
        raise ValueError("Loaded table counts do not match the source")
    if connection.execute("pragma foreign_key_check").fetchone():
        raise ValueError("Foreign-key validation failed")
    required_views = {
        "reporting_thresholds", "reporting_rules", "company_overview",
        "employee_role_classification", "employee_reporting_features",
        "employee_manager_candidates", "employee_manager_scores",
        "employee_top_manager_candidates", "employee_reporting_decisions",
        "company_reporting_summary", "dataset_reporting_summary",
        "employee_reporting_audit",
    }
    views = {row[0] for row in connection.execute(
        "select name from sqlite_master where type = 'view'"
    )}
    if not required_views.issubset(views):
        raise ValueError("Required inference views are missing")


def read_index(connection: sqlite3.Connection) -> dict:
    companies = []
    for row in connection.execute("""
        select * from company_overview
        order by company_name, company_id
    """):
        companies.append({
            "id": row["company_id"], "name": row["company_name"],
            "industry": row["industry"], "sizeBand": row["size_band"],
            "employeeCount": row["employee_count"], "headquarters": row["headquarters"],
        })
    totals = connection.execute("""
        select (select count(*) from companies) as company_count,
               (select count(*) from employees) as employee_count
    """).fetchone()
    return {
        "companies": companies,
        "summary": {
            "companyCount": totals["company_count"],
            "employeeCount": totals["employee_count"],
        },
    }


def read_company(connection: sqlite3.Connection, company_id: str) -> dict | None:
    profile = connection.execute(
        "select * from company_overview where company_id = ?", (company_id,)
    ).fetchone()
    if profile is None:
        return None
    # Views take no parameters, so run the same CTE chain scoped to one company
    # rather than scoring all 87k people for every page load.
    query = f"""
        {COMPANY_INFERENCE_CTES},
        person_rows as materialized (
            select e.*, f.inferred_department, f.inferred_level,
                   p.accepted_manager_id, p.best_candidate_id,
                   p.confidence, p.margin, p.decision, p.rule, p.reason
            from employees e
            join employee_reporting_features f using (company_id, employee_id)
            join employee_reporting_decisions p using (company_id, employee_id)
            where e.company_id = :company_id
        )
        select *,
               sum(decision = 'accepted') over () as resolved_count,
               sum(decision = 'unresolved') over () as unresolved_count,
               round(1.0 * sum(decision = 'accepted') over () /
                     max(sum(decision <> 'company_root') over (), 1), 4) as coverage,
               round(coalesce(avg(case when decision = 'accepted' then confidence end)
                     over (), 0.0), 4) as average_confidence
        from person_rows order by employee_id
    """
    rows = connection.execute(query, {"company_id": company_id}).fetchall()
    if not rows:
        raise ValueError(f"Company has no employee records: {company_id}")
    employees = []
    for person in rows:
        employees.append({
            "id": person["employee_id"], "name": person["full_name"],
            "title": person["job_title"] or "Title unavailable",
            "rawDepartment": person["raw_department"] or "Unavailable",
            "team": person["raw_team"] or "Unavailable",
            "inferredDepartment": person["inferred_department"],
            "inferredLevel": person["inferred_level"], "location": person["location"] or "Unavailable",
            "predictedManagerId": person["accepted_manager_id"],
            "bestCandidateId": person["best_candidate_id"],
            "confidence": person["confidence"], "margin": person["margin"],
            "rule": person["rule"], "reason": person["reason"],
            "isRoot": person["decision"] == "company_root",
        })
    return {
        "company": {"id": profile["company_id"], "name": profile["company_name"],
                    "industry": profile["industry"], "sizeBand": profile["size_band"],
                    "employeeCount": profile["employee_count"],
                    "headquarters": profile["headquarters"]},
        "summary": {"resolved": rows[0]["resolved_count"],
                    "unresolved": rows[0]["unresolved_count"],
                    "coverage": rows[0]["coverage"],
                    "averageConfidence": rows[0]["average_confidence"]},
        "employees": employees,
    }
