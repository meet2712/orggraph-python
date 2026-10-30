"""Load a relational SQLite snapshot and read company pages from it."""

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
RANKS = {
    "Unknown": 1, "Junior IC": 0, "Individual Contributor": 1, "Senior IC": 2,
    "Lead / Principal IC": 3, "Principal / Staff IC": 3, "Team Lead / Supervisor": 3,
    "Manager": 4, "Senior Manager": 5, "Director": 6,
    "Senior Director": 7, "VP / Head": 8, "C-Suite": 9, "CEO": 10,
}


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
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
        for row_number, row in enumerate(csv.DictReader(source), start=2):
            key = (row["company_id"], row["employee_id"])
            if key in records:
                raise ValueError(f"Duplicate employee in {path.name}: {key}")
            records[key] = {**row, "source_row_number": row_number}
    return records


def validate_company(payload: dict, company_id: str) -> None:
    """Check graph boundaries before any data becomes the served snapshot."""
    if payload.get("company", {}).get("id") != company_id:
        raise ValueError(f"Company ID does not match its file: {company_id}")
    employees = payload.get("employees")
    if not isinstance(employees, list) or not employees:
        raise ValueError(f"Company has no employee records: {company_id}")
    people = {}
    for employee in employees:
        if not isinstance(employee, dict):
            raise ValueError(f"Invalid employee record in {company_id}")
        employee_id = employee.get("id")
        if not isinstance(employee_id, str) or not employee_id or employee_id in people:
            raise ValueError(f"Missing or duplicate employee ID in {company_id}")
        if employee.get("inferredLevel") not in RANKS:
            raise ValueError(f"Unknown inferred seniority in {company_id}")
        people[employee_id] = employee

    for employee in employees:
        for field in ("predictedManagerId", "bestCandidateId"):
            manager_id = employee.get(field)
            if manager_id is not None and not isinstance(manager_id, str):
                raise ValueError(f"Invalid manager ID in {company_id}")
            if manager_id and manager_id not in people:
                raise ValueError(f"Manager is outside the company: {company_id}")
        visited = set()
        cursor = employee["id"]
        while cursor:
            if cursor in visited:
                raise ValueError(f"Circular reporting line in {company_id}")
            visited.add(cursor)
            cursor = people[cursor].get("predictedManagerId")
        manager_id = employee.get("predictedManagerId")
        if manager_id and RANKS[people[manager_id]["inferredLevel"]] <= RANKS[employee["inferredLevel"]]:
            raise ValueError(f"Accepted manager is not more senior in {company_id}")


def source_fingerprint(files: list[tuple[str, Path]]) -> str:
    digest = hashlib.sha256()
    for label, path in files:
        digest.update(label.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def snapshot_fingerprint(data_dir: Path, raw_dir: Path) -> str:
    """Fingerprint the schema and source records, not derived predictions."""
    files = [
        ("companies/index.json", data_dir / "index.json"),
        ("raw/employees_messy.csv", raw_dir / "employees_messy.csv"),
        ("schema.sql", ROOT / "schema.sql"),
    ]
    return source_fingerprint(files)


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def cached_run(database: Path, fingerprint: str) -> str | None:
    """Reuse a healthy database even when source employees were edited locally."""
    try:
        manifest = read_json(database.with_suffix(".manifest.json"))
        if manifest["source_hash"] != fingerprint:
            return None
        with closing(connect(database, readonly=True)) as connection:
            if connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                return None
            run = connection.execute("SELECT * FROM inference_runs").fetchone()
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )}
            if run is None or run["run_id"] != "live" or tables != {"companies", "employees"}:
                return None
            return run["run_id"]
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return None


def ensure_snapshot(database: Path, snapshot: Path, data_dir: Path, raw_dir: Path,
                    index: dict) -> tuple[str, bool]:
    fingerprint = snapshot_fingerprint(data_dir, raw_dir)
    run_id = cached_run(database, fingerprint)
    if run_id is not None:
        database_hash = file_digest(database)
        try:
            manifest = read_json(database.with_suffix(".manifest.json"))
            snapshot_current = (manifest.get("database_sha256") == database_hash
                                and snapshot.exists()
                                and manifest.get("snapshot_sha256") == file_digest(snapshot))
        except (OSError, ValueError, KeyError):
            snapshot_current = False
        if not snapshot_current:
            write_compressed_snapshot(database, snapshot)
            manifest = {
                "source_hash": fingerprint, "run_id": run_id,
                "database_sha256": database_hash,
                "snapshot_sha256": file_digest(snapshot),
            }
            database.with_suffix(".manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
        return run_id, True
    run_id = load_snapshot(database, data_dir, raw_dir, index)
    write_compressed_snapshot(database, snapshot)
    manifest = {
        "source_hash": fingerprint,
        "run_id": run_id,
        "database_sha256": file_digest(database),
        "snapshot_sha256": file_digest(snapshot),
    }
    with NamedTemporaryFile(prefix=".manifest-", dir=database.parent, delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        staging.write_text(json.dumps(manifest), encoding="utf-8")
        os.replace(staging, database.with_suffix(".manifest.json"))
    finally:
        staging.unlink(missing_ok=True)
    return run_id, False


def load_snapshot(database: Path, data_dir: Path, raw_dir: Path, index: dict) -> str:
    """Create a source-only database; every inference result is a SQL view."""
    raw = read_employee_csv(raw_dir / "employees_messy.csv")
    if len(raw) != index["summary"]["employeeCount"]:
        raise ValueError("Raw employee count does not match the source index")
    company_ids = [company["id"] for company in index["companies"]]
    run_id = "live"
    database.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".orggraph-load-", suffix=".sqlite3", dir=database.parent, delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        with closing(connect(staging)) as connection:
            connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
            with connection:
                connection.executemany(
                    "INSERT INTO companies VALUES (?, ?, ?, ?)",
                    [(row["id"], row["name"], row["industry"], row["headquarters"])
                     for row in index["companies"]],
                )
                connection.executemany(
                    "INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(row["company_id"], row["employee_id"], row["full_name"], row["job_title"],
                      row["department"], row["team"], row["location"], row["work_email"],
                      row["source_row_number"]) for row in raw.values()],
                )
                check_loaded_snapshot(connection, run_id, len(company_ids), len(raw))
        os.replace(staging, database)
    finally:
        staging.unlink(missing_ok=True)
    return run_id


def check_loaded_snapshot(connection, run_id, company_count, employee_count):
    counts = [connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
              for table in ("companies", "employees")]
    if counts != [company_count, employee_count]:
        raise ValueError("Loaded table counts do not match the source")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Foreign-key validation failed")
    required_views = {"inference_runs", "company_profiles", "employee_features",
                      "reporting_predictions", "prediction_reasons",
                      "company_run_metrics", "run_metrics", "employee_reporting_audit"}
    views = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view'"
    )}
    if not required_views.issubset(views):
        raise ValueError("Required inference views are missing")


def read_index(connection: sqlite3.Connection, run_id: str) -> dict:
    """Build the directory from live headcounts without scoring all companies."""
    companies = []
    for row in connection.execute("""
        SELECT * FROM company_profiles
        ORDER BY company_name, company_id
    """):
        companies.append({
            "id": row["company_id"], "name": row["company_name"],
            "industry": row["industry"], "sizeBand": row["size_band"],
            "employeeCount": row["employee_count"], "headquarters": row["headquarters"],
        })
    totals = connection.execute("""
        SELECT (SELECT count(*) FROM companies) AS company_count,
               (SELECT count(*) FROM employees) AS employee_count
    """).fetchone()
    return {
        "companies": companies,
        "summary": {
            "companyCount": totals["company_count"],
            "employeeCount": totals["employee_count"],
        },
    }


def read_company(connection: sqlite3.Connection, run_id: str, company_id: str) -> dict | None:
    profile = connection.execute(
        "SELECT * FROM company_profiles WHERE company_id = ?", (company_id,)
    ).fetchone()
    if profile is None:
        return None
    # SQLite views cannot accept parameters. Scope the same SQL scoring rules
    # to one company so a page never ranks all 87,000 employees at once.
    query = f"""
        WITH predictions AS MATERIALIZED ({COMPANY_PREDICTIONS_SQL}),
        person_rows AS MATERIALIZED (
            SELECT e.*, f.inferred_department, f.inferred_level,
                   p.accepted_manager_id, p.best_candidate_id,
                   p.confidence, p.margin, p.decision,
                   CASE WHEN p.decision = 'company_root'
                        THEN 'CEO is the company root'
                        WHEN p.best_candidate_id IS NULL
                        THEN 'No suitable management title'
                        WHEN p.decision = 'accepted'
                        THEN 'Team path and seniority identify a manager'
                        WHEN p.confidence < settings.probability_threshold
                        THEN 'Insufficient team or role evidence'
                        ELSE 'Several candidates have similar evidence'
                   END AS reason
            FROM employees e
            JOIN employee_features f USING (company_id, employee_id)
            JOIN predictions p USING (company_id, employee_id)
            CROSS JOIN inference_runs settings
            WHERE e.company_id = :company_id
        )
        SELECT *,
               sum(decision = 'accepted') OVER () AS resolved_count,
               sum(decision = 'unresolved') OVER () AS unresolved_count,
               round(1.0 * sum(decision = 'accepted') OVER () /
                     max(sum(decision <> 'company_root') OVER (), 1), 4) AS coverage,
               round(coalesce(avg(CASE WHEN decision = 'accepted' THEN confidence END)
                     OVER (), 0.0), 4) AS average_confidence
        FROM person_rows ORDER BY source_row_number
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
            "reasons": [person["reason"]],
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
