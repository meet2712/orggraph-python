"""Check relational loading, SQL constraints, app reads, and graph boundaries."""

import csv
import gzip
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from jinja2 import DictLoader

from app import chart_context, create_app, get_database
from database import connect, import_company, load_snapshot, read_company


def employee(employee_id, level, manager=None, candidate=None, truth=None):
    return {
        "id": employee_id, "name": employee_id, "title": level,
        "rawDepartment": "Engineering", "team": "Platform",
        "inferredDepartment": "Executive" if level == "CEO" else "Engineering",
        "inferredLevel": level, "location": "Sydney, AU",
        "predictedManagerId": manager, "bestCandidateId": candidate or manager,
        "confidence": 0.95 if candidate or manager else 0.0,
        "margin": 0.3 if candidate or manager else 0.0,
        "reasons": ["same team"] if manager else [],
        "groundTruthManagerId": truth,
        "isCorrect": bool(manager and manager == truth),
        "isRoot": truth is None, "noiseProfile": ["clean"],
    }


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        data = self.root / "data"
        raw = self.root / "raw"
        (data / "companies").mkdir(parents=True)
        raw.mkdir()
        metadata = {
            "id": "cmp_0001", "name": "Example Company", "industry": "B2B SaaS",
            "sizeBand": "Small", "employeeCount": 4, "headquarters": "Sydney, AU",
        }
        self.payload = {
            "company": metadata,
            "summary": {
                "resolved": 1, "unresolved": 2, "coverage": 0.3333,
                "precision": 1.0, "averageConfidence": 0.95,
            },
            "employees": [
                employee("ceo", "CEO"),
                employee("manager", "Manager", candidate="ceo", truth="ceo"),
                employee("report", "Individual Contributor", manager="manager", truth="manager"),
                employee("unresolved", "Individual Contributor", candidate="ceo", truth="ceo"),
            ],
        }
        self.company_file = data / "companies" / "cmp_0001.json"
        self.save_payload()
        (data / "index.json").write_text(json.dumps({
            "companies": [metadata], "summary": {"companyCount": 1, "employeeCount": 4},
        }))
        (data / "evaluation.json").write_text(json.dumps({
            "modelType": "Test scorer", "model": {"threshold": {"probability": 0.6, "margin": 0.1}},
            "split": {"testCompanies": 1},
        }))
        model = self.root / "model.json"
        model.write_text('{"seed": 1}')
        raw_rows = []
        truth_rows = []
        for person in self.payload["employees"]:
            raw_rows.append({
                "company_id": "cmp_0001", "employee_id": person["id"],
                "full_name": person["name"], "job_title": person["title"],
                "department": person["rawDepartment"], "team": person["team"],
                "location": person["location"], "work_email": f"{person['id']}@company.example",
            })
            truth_rows.append({
                "company_id": "cmp_0001", "employee_id": person["id"],
                "manager_employee_id": person["groundTruthManagerId"] or "",
                "canonical_title": person["title"], "canonical_department": person["inferredDepartment"],
                "canonical_team": person["team"], "canonical_level": person["inferredLevel"],
                "is_people_manager": "1" if person["id"] in {"ceo", "manager"} else "0",
            })
        write_csv(raw / "employees_messy.csv", raw_rows)
        write_csv(raw / "employees_ground_truth.csv", truth_rows)
        self.config = {
            "TESTING": True, "DATABASE": self.root / "orggraph.sqlite3",
            "DATABASE_SNAPSHOT": self.root / "snapshot.sqlite.gz", "DATA_DIR": data,
            "RAW_DATA_DIR": raw, "MODEL_PATH": model,
        }
        self.app = create_app(self.config)
        self.app.jinja_loader = DictLoader({
            "index.html": "{{ page }}|{{ company.company.id }}|{{ selected_id }}"
        })
        static = self.root / "public"
        static.mkdir()
        (static / "style.css").write_text("body { color: green; }")
        self.app.static_folder = str(static)
        self.client = self.app.test_client()
        self.run_id = self.app.config["ACTIVE_RUN_ID"]

    def save_payload(self):
        self.company_file.write_text(json.dumps(self.payload))

    def test_relational_read_reconstructs_the_source_payload(self):
        with closing(connect(self.config["DATABASE"], readonly=True)) as connection:
            self.assertEqual(read_company(connection, self.run_id, "cmp_0001"), self.payload)
            columns = connection.execute("PRAGMA table_info(companies)").fetchall()
            self.assertNotIn("payload", [row["name"] for row in columns])
            run = connection.execute("SELECT * FROM inference_runs").fetchone()
            self.assertEqual(run["load_status"], "ready")
            self.assertEqual(run["loaded_employee_count"], 4)
            self.assertEqual(run["loaded_prediction_count"], 4)
        self.assertEqual(self.client.get("/health").json, {"status": "ok"})

    def test_all_pages_use_the_selected_company(self):
        expected = {
            "/": "chart|cmp_0001|cmp_0001",
            "/companies/cmp_0001.html": "chart|cmp_0001|cmp_0001",
            "/results.html": "results|cmp_0001|cmp_0001",
            "/approach.html": "approach|cmp_0001|cmp_0001",
            "/data.html": "data|cmp_0001|cmp_0001",
        }
        for url, text in expected.items():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, text)

    def test_unknown_or_malformed_company_is_404(self):
        for company_id in ("cmp_9999", "not-a-company", "cmp_0001' OR 1=1"):
            with self.subTest(company_id=company_id):
                self.assertEqual(self.client.get(f"/companies/{company_id}.html").status_code, 404)

    def test_candidates_and_answer_key_never_become_chart_edges(self):
        chart = chart_context(self.payload)
        self.assertEqual(set(chart["children"]), {"manager"})
        self.assertEqual([person["id"] for person in chart["children"]["manager"]], ["report"])
        self.assertEqual([person["id"] for person in chart["roots"]], ["ceo", "manager"])
        self.assertEqual([person["id"] for person in chart["unresolved"]], ["manager", "unresolved"])

    def test_static_assets_use_public_urls(self):
        with self.client.get("/style.css") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/css", response.content_type)
            self.assertIn("color: green", response.text)

    def test_request_connection_is_read_only_and_closes(self):
        with self.app.test_request_context("/"):
            connection = get_database()
            self.assertIs(connection, get_database())
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM employees")
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO companies VALUES ('cmp_0002', 'Other', 'IT', 'Small', 1, 'Sydney')")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_snapshot_download_round_trips_as_sqlite(self):
        with self.client.get("/database/snapshot.sqlite.gz") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, "application/octet-stream")
            self.assertNotIn("Content-Encoding", response.headers)
            database_bytes = gzip.decompress(response.data)
        target = self.root / "download.sqlite3"
        target.write_bytes(database_bytes)
        with closing(connect(target, readonly=True)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM employees").fetchone()[0], 4)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_loading_again_preserves_keys_counts_and_payload(self):
        reloaded = create_app(self.config)
        self.assertEqual(reloaded.config["ACTIVE_RUN_ID"], self.run_id)
        with closing(connect(self.config["DATABASE"], readonly=True)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM inference_runs").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM employees").fetchone()[0], 4)
            self.assertEqual(read_company(connection, self.run_id, "cmp_0001"), self.payload)

    def test_unchanged_startup_reuses_the_checked_database_and_download(self):
        paths = [self.config["DATABASE"], self.config["DATABASE_SNAPSHOT"]]
        before = [path.stat().st_mtime_ns for path in paths]
        with patch("database.load_snapshot", side_effect=AssertionError("Unexpected rebuild")):
            reused = create_app(self.config)
        self.assertTrue(reused.config["DATABASE_REUSED"])
        self.assertEqual([path.stat().st_mtime_ns for path in paths], before)

    def test_confidence_display_matches_sql_rounding_at_halfway_values(self):
        percent = self.app.jinja_env.filters["percent"]
        points = self.app.jinja_env.filters["points"]
        self.assertEqual(percent(0.6425), "64.3%")
        self.assertEqual(percent(0.5995), "60.0%")
        self.assertEqual(points(0.6425), "64.3")

    def test_decision_audit_joins_evidence_without_the_answer_key(self):
        with closing(connect(self.config["DATABASE"])) as connection:
            rows = connection.execute("SELECT * FROM employee_reporting_audit").fetchall()
            self.assertEqual(len(rows), 4)
            report = next(row for row in rows if row["employee_id"] == "report")
            self.assertEqual(report["inferred_manager"], "manager")
            self.assertEqual(report["decision_reason"], "cleared_both_checks")
            self.assertNotIn("groundTruthManagerId", report.keys())
            self.assertNotIn("manager_employee_id", report.keys())
            connection.execute("UPDATE reporting_predictions SET confidence=0.5, margin=0.05 WHERE employee_id='unresolved'")
            reason = connection.execute("SELECT decision_reason FROM employee_reporting_audit WHERE employee_id='unresolved'").fetchone()[0]
            self.assertEqual(reason, "low_confidence_and_ambiguous_candidates")

    def test_load_rejects_a_summary_that_hides_unresolved_people(self):
        path = self.config["DATA_DIR"] / "companies" / "cmp_0001.json"
        payload = json.loads(path.read_text())
        payload["summary"]["unresolved"] = 0
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "Company counts"):
            create_app(self.config)
        with closing(connect(self.config["DATABASE"], readonly=True)) as connection:
            self.assertEqual(read_company(connection, self.run_id, "cmp_0001"), self.payload)

    def test_load_rejects_an_accepted_line_below_its_run_threshold(self):
        payload = json.loads(self.company_file.read_text())
        payload["employees"][2]["confidence"] = 0.5
        self.company_file.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "both thresholds"):
            create_app(self.config)

    def test_changed_model_rebuilds_instead_of_reusing_a_stale_snapshot(self):
        self.config["MODEL_PATH"].write_text('{"seed": 2}')
        with patch("database.load_snapshot", wraps=load_snapshot) as loader:
            rebuilt = create_app(self.config)
        self.assertEqual(loader.call_count, 1)
        self.assertFalse(rebuilt.config["DATABASE_REUSED"])
        self.assertNotEqual(rebuilt.config["ACTIVE_RUN_ID"], self.run_id)

    def test_damaged_database_download_or_manifest_is_rebuilt(self):
        paths = [self.config["DATABASE"], self.config["DATABASE_SNAPSHOT"],
                 self.config["DATABASE"].with_suffix(".manifest.json")]
        for path in paths:
            with self.subTest(path=path.name):
                path.write_bytes(b"damaged file")
                rebuilt = create_app(self.config)
                self.assertFalse(rebuilt.config["DATABASE_REUSED"])
                with closing(connect(self.config["DATABASE"], readonly=True)) as connection:
                    self.assertEqual(read_company(connection, self.run_id, "cmp_0001"), self.payload)
                self.assertTrue(gzip.decompress(self.config["DATABASE_SNAPSHOT"].read_bytes()).startswith(b"SQLite format 3"))

    def test_explicit_load_snapshot_still_forces_a_full_import(self):
        data = self.config["DATA_DIR"]
        with patch("database.import_company", wraps=import_company) as importer:
            run_id = load_snapshot(
                self.config["DATABASE"], data, self.config["RAW_DATA_DIR"],
                self.config["MODEL_PATH"], json.loads((data / "index.json").read_text()),
                json.loads((data / "evaluation.json").read_text()),
            )
        self.assertEqual(importer.call_count, 1)
        self.assertEqual(run_id, self.run_id)

    def test_raw_blanks_stay_queryable_and_display_fallbacks_stay_in_the_app(self):
        path = self.config["RAW_DATA_DIR"] / "employees_messy.csv"
        with path.open(newline="") as source:
            rows = list(csv.DictReader(source))
        rows[2].update(job_title="", department="", team="-", location="")
        write_csv(path, rows)
        self.payload["employees"][2].update(
            title="Title unavailable", rawDepartment="Unavailable", team="-", location="Unavailable"
        )
        self.save_payload()
        reloaded = create_app(self.config)
        with closing(connect(self.config["DATABASE"], readonly=True)) as connection:
            raw = connection.execute(
                "SELECT job_title, raw_department, raw_team, location FROM employees WHERE employee_id = 'report'"
            ).fetchone()
            self.assertEqual(tuple(raw), ("", "", "-", ""))
            self.assertEqual(read_company(connection, reloaded.config["ACTIVE_RUN_ID"], "cmp_0001"), self.payload)

    def test_invalid_load_preserves_the_previous_database(self):
        before = self.config["DATABASE"].read_bytes()
        self.payload["employees"][2]["predictedManagerId"] = "missing-manager"
        self.save_payload()
        with self.assertRaisesRegex(ValueError, "Manager is outside the company"):
            create_app(self.config)
        self.assertEqual(self.config["DATABASE"].read_bytes(), before)
        self.assertEqual(list(self.root.glob(".orggraph-load-*")), [])

    def test_startup_rejects_a_cycle(self):
        self.payload["employees"][1]["predictedManagerId"] = "report"
        self.save_payload()
        with self.assertRaisesRegex(ValueError, "Circular reporting line"):
            create_app(self.config)

    def test_startup_rejects_a_manager_who_is_not_more_senior(self):
        self.payload["employees"][2]["predictedManagerId"] = "unresolved"
        self.save_payload()
        with self.assertRaisesRegex(ValueError, "not more senior"):
            create_app(self.config)

    def test_score_bounds_and_single_prediction_are_enforced(self):
        with closing(connect(self.config["DATABASE"])) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE reporting_predictions SET confidence = 1.1 WHERE employee_id = 'report'")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE reporting_predictions SET margin = -0.1 WHERE employee_id = 'report'")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO reporting_predictions SELECT * FROM reporting_predictions WHERE employee_id = 'report'")

    def test_self_manager_is_rejected_by_sql(self):
        with closing(connect(self.config["DATABASE"])) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE reporting_predictions SET accepted_manager_id = employee_id, best_candidate_id = employee_id, decision = 'accepted' WHERE employee_id = 'report'")

    def test_composite_keys_reject_cross_company_managers_and_candidates(self):
        with closing(connect(self.config["DATABASE"])) as connection:
            connection.execute("INSERT INTO companies VALUES ('cmp_0002', 'Other Company', 'IT', 'Small', 1, 'Sydney')")
            connection.execute("INSERT INTO employees VALUES ('cmp_0002', 'other-ceo', 'Other CEO', 'CEO', '', '', '', '', 6)")
            connection.execute("INSERT INTO employee_features VALUES (?, 'cmp_0002', 'other-ceo', 'Executive', 'CEO', 8)", (self.run_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE reporting_predictions SET accepted_manager_id = 'other-ceo', best_candidate_id = 'other-ceo' WHERE employee_id = 'report'")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE reporting_predictions SET best_candidate_id = 'other-ceo' WHERE employee_id = 'unresolved'")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE benchmark_truth SET manager_employee_id = 'other-ceo' WHERE employee_id = 'report'")


if __name__ == "__main__":
    unittest.main()
