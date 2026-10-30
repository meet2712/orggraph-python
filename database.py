"""Load a relational SQLite snapshot and read company pages from it."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parent
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


def snapshot_fingerprint(data_dir: Path, raw_dir: Path, model_path: Path, index: dict) -> str:
    company_ids = [company["id"] for company in index["companies"]]
    files = [
        ("predictions/index.json", data_dir / "index.json"),
        ("predictions/evaluation.json", data_dir / "evaluation.json"),
        ("raw/employees_messy.csv", raw_dir / "employees_messy.csv"),
        ("benchmark/employees_ground_truth.csv", raw_dir / "employees_ground_truth.csv"),
        ("model/model.json", model_path),
        ("pipeline/train_and_infer.py", ROOT / "pipeline/train_and_infer.py"),
        ("schema.sql", ROOT / "schema.sql"),
        ("database.py", ROOT / "database.py"),
    ]
    files.extend(
        (f"predictions/companies/{company_id}.json", data_dir / "companies" / f"{company_id}.json")
        for company_id in sorted(company_ids)
    )
    return source_fingerprint(files)


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def cached_run(database: Path, snapshot: Path, fingerprint: str, index: dict) -> str | None:
    """Reuse only the exact files produced by a successful checked load."""
    try:
        manifest = read_json(database.with_suffix(".manifest.json"))
        if manifest["source_hash"] != fingerprint:
            return None
        if file_digest(database) != manifest["database_sha256"]:
            return None
        if file_digest(snapshot) != manifest["snapshot_sha256"]:
            return None
        with closing(connect(database, readonly=True)) as connection:
            if connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                return None
            run = connection.execute("SELECT * FROM inference_runs").fetchone()
            companies = connection.execute("SELECT count(*) FROM companies").fetchone()[0]
            employees = connection.execute("SELECT count(*) FROM employees").fetchone()[0]
            outputs = connection.execute("SELECT count(*) FROM inference_outputs").fetchone()[0]
            if (run is None or run["load_status"] != "ready"
                    or run["source_hash"] != fingerprint or run["run_id"] != manifest["run_id"]
                    or companies != len(index["companies"])
                    or employees != index["summary"]["employeeCount"]
                    or outputs != employees
                    or run["source_company_count"] != companies
                    or run["source_employee_count"] != employees):
                return None
            return run["run_id"]
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return None


def ensure_snapshot(database: Path, snapshot: Path, data_dir: Path, raw_dir: Path,
                    model_path: Path, index: dict, evaluation: dict) -> tuple[str, bool]:
    fingerprint = snapshot_fingerprint(data_dir, raw_dir, model_path, index)
    run_id = cached_run(database, snapshot, fingerprint, index)
    if run_id is not None:
        return run_id, True
    run_id = load_snapshot(database, data_dir, raw_dir, model_path, index, evaluation)
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


def load_snapshot(database: Path, data_dir: Path, raw_dir: Path, model_path: Path,
                  index: dict, evaluation: dict) -> str:
    """Always import, validate, and atomically replace the snapshot when called."""
    raw = read_employee_csv(raw_dir / "employees_messy.csv")
    truth = read_employee_csv(raw_dir / "employees_ground_truth.csv")
    if set(raw) != set(truth):
        raise ValueError("Raw and benchmark employee keys do not match")
    if len(raw) != index["summary"]["employeeCount"]:
        raise ValueError("Raw employee count does not match the source index")
    company_ids = [company["id"] for company in index["companies"]]
    source_hash = snapshot_fingerprint(data_dir, raw_dir, model_path, index)
    run_id = f"run_{source_hash[:16]}"
    threshold = evaluation["model"]["threshold"]
    database.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".orggraph-load-", suffix=".sqlite3", dir=database.parent, delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        with closing(connect(staging)) as connection:
            connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
            with connection:
                connection.execute(
                    """INSERT INTO inference_runs (
                        run_id, source_hash, model_version, pipeline_version, model_type,
                        probability_threshold, margin_threshold, source_company_count,
                        source_employee_count, load_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'loading')""",
                    (run_id, source_hash, hashlib.sha256(model_path.read_bytes()).hexdigest(),
                     hashlib.sha256((ROOT / "pipeline/train_and_infer.py").read_bytes()).hexdigest(),
                     evaluation["modelType"], threshold["probability"], threshold["margin"],
                     len(company_ids), len(raw)),
                )
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
                connection.executemany(
                    "INSERT INTO benchmark_labels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(row["company_id"], row["employee_id"], row["manager_employee_id"] or None,
                      row["canonical_title"], row["canonical_department"], row["canonical_team"],
                      row["canonical_level"], int(row["is_people_manager"]),
                      json.dumps(row.get("noise_profile", "clean").split("|")))
                     for row in truth.values()],
                )
                seen = set()
                for company_id in company_ids:
                    payload = read_json(data_dir / "companies" / f"{company_id}.json")
                    validate_company(payload, company_id)
                    import_company(connection, run_id, company_id, payload, raw, truth)
                    seen.update((company_id, employee["id"]) for employee in payload["employees"])
                if seen != set(raw):
                    raise ValueError("Prediction and raw employee keys do not match")
                check_loaded_snapshot(connection, run_id, len(company_ids), len(raw))
        os.replace(staging, database)
    finally:
        staging.unlink(missing_ok=True)
    return run_id


def import_company(connection, run_id, company_id, payload, raw, truth):
    employees = payload["employees"]
    for person in employees:
        key = (company_id, person["id"])
        if key not in raw:
            raise ValueError(f"Prediction has no raw employee record: {key}")
        record = raw[key]
        expected = {
            "name": record["full_name"], "title": record["job_title"] or "Title unavailable",
            "rawDepartment": record["department"] or "Unavailable",
            "team": record["team"] or "Unavailable", "location": record["location"] or "Unavailable",
            "groundTruthManagerId": truth[key]["manager_employee_id"] or None,
            "isRoot": not truth[key]["manager_employee_id"],
        }
        if any(person[field] != value for field, value in expected.items()):
            raise ValueError(f"Raw/benchmark fields disagree with prediction export: {key}")
    connection.executemany(
        "INSERT INTO inference_outputs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(run_id, company_id, person["id"], person["inferredDepartment"],
          person["inferredLevel"], RANKS[person["inferredLevel"]],
          person["predictedManagerId"], person["bestCandidateId"], person["confidence"],
          person["margin"], "accepted" if person["predictedManagerId"] else
          "company_root" if person["inferredLevel"] == "CEO" else "unresolved",
          json.dumps(person["reasons"])) for person in employees],
    )


def check_loaded_snapshot(connection, run_id, company_count, employee_count):
    counts = [connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
              for table in ("companies", "employees", "inference_outputs")]
    if counts != [company_count, employee_count, employee_count]:
        raise ValueError("Loaded table counts do not match the source")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Foreign-key validation failed")
    # Mark the run ready inside this transaction so its dynamic views are
    # queryable during validation. Any later failure rolls this update back.
    connection.execute(
        "UPDATE inference_runs SET load_status = 'ready' WHERE run_id = ?",
        (run_id,),
    )
    mismatched_views = connection.execute("""
        SELECT profile.company_id
        FROM company_profiles AS profile
        JOIN company_run_metrics AS metrics USING (company_id)
        JOIN reporting_predictions AS prediction
          ON prediction.run_id = metrics.run_id
         AND prediction.company_id = metrics.company_id
        WHERE metrics.run_id = ?
        GROUP BY profile.company_id, profile.employee_count,
                 metrics.resolved_count, metrics.unresolved_count
        HAVING profile.employee_count < 1
            OR metrics.resolved_count + metrics.unresolved_count <>
               profile.employee_count - sum(prediction.decision = 'company_root')
        LIMIT 1
    """, (run_id,)).fetchone()
    if mismatched_views:
        raise ValueError("Dynamic company views do not reconcile")
    weak_accepted = connection.execute("""
        SELECT p.employee_id FROM reporting_predictions p
        JOIN inference_runs r USING (run_id)
        WHERE p.decision = 'accepted'
          AND (p.confidence < r.probability_threshold OR p.margin < r.margin_threshold)
        LIMIT 1
    """).fetchone()
    if weak_accepted:
        raise ValueError("Accepted reporting line did not clear both thresholds")
    accepted = connection.execute(
        "SELECT count(*) FROM inference_outputs WHERE decision = 'accepted'"
    ).fetchone()[0]
    if accepted < 1:
        raise ValueError("The inference run contains no accepted reporting lines")


def read_index(connection: sqlite3.Connection, run_id: str) -> dict:
    """Build the company directory and totals from live database views."""
    companies = []
    for row in connection.execute("""
        SELECT profile.*, metrics.resolved_count, metrics.unresolved_count,
               metrics.coverage, metrics.precision, metrics.average_confidence
        FROM company_profiles AS profile
        JOIN company_run_metrics AS metrics USING (company_id)
        WHERE metrics.run_id = ?
        ORDER BY profile.company_name, profile.company_id
    """, (run_id,)):
        companies.append({
            "id": row["company_id"], "name": row["company_name"],
            "industry": row["industry"], "sizeBand": row["size_band"],
            "employeeCount": row["employee_count"], "headquarters": row["headquarters"],
            "resolved": row["resolved_count"], "unresolved": row["unresolved_count"],
            "coverage": row["coverage"], "precision": row["precision"],
            "averageConfidence": row["average_confidence"],
        })
    totals = connection.execute(
        "SELECT * FROM run_metrics WHERE run_id = ?", (run_id,)
    ).fetchone()
    return {
        "companies": companies,
        "summary": {
            "companyCount": totals["company_count"],
            "employeeCount": totals["employee_count"],
            "averageResolvedConfidence": totals["average_resolved_confidence"],
        },
    }


def read_company(connection: sqlite3.Connection, run_id: str, company_id: str) -> dict | None:
    row = connection.execute("""
        SELECT c.*, m.resolved_count, m.unresolved_count, m.coverage, m.precision, m.average_confidence
        FROM company_profiles c JOIN company_run_metrics m USING (company_id)
        WHERE c.company_id = ? AND m.run_id = ?
    """, (company_id, run_id)).fetchone()
    if row is None:
        return None
    reasons = defaultdict(list)
    for reason in connection.execute("""
        SELECT employee_id, reason FROM prediction_reasons
        WHERE run_id = ? AND company_id = ? ORDER BY employee_id, position
    """, (run_id, company_id)):
        reasons[reason["employee_id"]].append(reason["reason"])
    noise = defaultdict(list)
    for item in connection.execute("""
        SELECT employee_id, noise_type FROM employee_noise
        WHERE company_id = ? ORDER BY employee_id, position
    """, (company_id,)):
        noise[item["employee_id"]].append(item["noise_type"])
    employees = []
    for person in connection.execute("""
        SELECT e.*, f.inferred_department, f.inferred_level, f.processing_status,
            p.accepted_manager_id, p.best_candidate_id, p.confidence, p.margin,
            p.decision, t.manager_employee_id, t.is_root
        FROM employees e
        JOIN employee_features f USING (company_id, employee_id)
        JOIN reporting_predictions p USING (run_id, company_id, employee_id)
        LEFT JOIN benchmark_truth t USING (company_id, employee_id)
        WHERE e.company_id = ? AND f.run_id = ? ORDER BY e.source_row_number
    """, (company_id, run_id)):
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
            "reasons": reasons[person["employee_id"]],
            "groundTruthManagerId": person["manager_employee_id"],
            "isCorrect": bool(person["accepted_manager_id"] and
                              person["accepted_manager_id"] == person["manager_employee_id"]),
            "isRoot": bool(person["is_root"] if person["is_root"] is not None
                           else person["decision"] == "company_root"),
            "noiseProfile": noise[person["employee_id"]],
        })
    return {
        "company": {"id": row["company_id"], "name": row["company_name"],
                    "industry": row["industry"], "sizeBand": row["size_band"],
                    "employeeCount": row["employee_count"], "headquarters": row["headquarters"]},
        "summary": {"resolved": row["resolved_count"], "unresolved": row["unresolved_count"],
                    "coverage": row["coverage"], "precision": row["precision"],
                    "averageConfidence": row["average_confidence"]},
        "employees": employees,
    }
