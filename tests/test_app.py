"""Check source-only storage and live SQL inference."""

import csv
import gzip
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from database import connect, read_company, read_index


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class SourceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        data, raw = root / "data", root / "raw"
        data.mkdir()
        raw.mkdir()
        self.database = root / "orggraph.sqlite3"
        self.snapshot = root / "snapshot.sqlite.gz"
        write_csv(raw / "companies.csv", [{
            "company_id": "cmp_0001", "company_name": "Example Company",
            "industry": "B2B SaaS", "size_band": "Small", "employee_count": 4,
            "headquarters": "Sydney, AU",
        }])
        (raw / "dataset_summary.json").write_text(json.dumps({
            "companies": 1, "employees": 4, "minimum_company_size": 4,
            "maximum_company_size": 4,
        }), encoding="utf-8")
        (data / "sql_evaluation.json").write_text(json.dumps({
            "companies": 1, "employees": 4, "roots": 1,
            "eligible_reporting_lines": 3, "accepted_reporting_lines": 2,
            "correct_reporting_lines": 2, "incorrect_reporting_lines": 0,
            "precision": 1.0, "coverage": 0.6667, "recall": 0.6667,
        }), encoding="utf-8")
        team = "Company / Technology / Engineering / Quality & Reliability"
        write_csv(raw / "employees_messy.csv", [
            self.person("ceo", "Chief Executive Officer", "Executive", "Company"),
            self.person("cto", "Chief Technology Officer", "Executive", "Company / Technology"),
            self.person("manager", "QA Manager", "Engineering", team),
            self.person("junior", "Junior QA Engineer", "Engineering", team),
        ])
        self.config = {"TESTING": True, "DATABASE": self.database,
                       "DATABASE_SNAPSHOT": self.snapshot, "DATA_DIR": data,
                       "RAW_DATA_DIR": raw}
        self.app = create_app(self.config)

    @staticmethod
    def person(employee_id, title, department, team):
        return {"employee_id": employee_id, "company_id": "cmp_0001",
                "full_name": employee_id.title(), "job_title": title,
                "department": department, "team": team, "location": "Sydney, AU",
                "work_email": f"{employee_id}@example.test"}

    def insert_person(self, employee_id, title="Junior QA Engineer",
                      department="Engineering",
                      team="Company / Technology / Engineering / Quality & Reliability"):
        with closing(connect(self.database)) as connection, connection:
            connection.execute("""
                insert into employees values
                ('cmp_0001', ?, ?, ?, ?, ?, 'Sydney, AU', ?)
            """, (employee_id, employee_id.title(), title, department, team,
                  f"{employee_id}@example.test"))

    def test_only_basic_source_tables_are_persisted(self):
        with closing(connect(self.database, readonly=True)) as connection:
            tables = {row[0] for row in connection.execute("""
                select name from sqlite_master where type = 'table'
                and name not like 'sqlite_%'
            """)}
            self.assertEqual(tables, {"companies", "employees"})
            views = {row[0] for row in connection.execute(
                "select name from sqlite_master where type = 'view'")}
            self.assertEqual(len(views), 12)
            self.assertIn("employee_role_classification", views)
            self.assertIn("employee_reporting_features", views)
            self.assertIn("employee_reporting_decisions", views)
            self.assertIn("company_reporting_summary", views)
            self.assertNotIn("employee_text", views)
            self.assertNotIn("employee_role_profiles", views)
            self.assertNotIn("benchmark_labels", tables | views)
            self.assertNotIn("inference_outputs", tables | views)

    def test_reporting_line_uses_current_employee_rows(self):
        with closing(connect(self.database, readonly=True)) as connection:
            payload = read_company(connection, "cmp_0001")
            people = {person["id"]: person for person in payload["employees"]}
            self.assertEqual(people["cto"]["predictedManagerId"], "ceo")
            self.assertEqual(people["junior"]["predictedManagerId"], "manager")
            self.assertEqual(people["junior"]["bestCandidateId"], "manager")
            self.assertNotIn("groundTruthManagerId", people["junior"])
            self.assertEqual(payload["company"]["employeeCount"], 4)

    def test_equally_plausible_managers_remain_unresolved(self):
        self.insert_person("other_manager", "QA Manager")
        with closing(connect(self.database, readonly=True)) as connection:
            payload = read_company(connection, "cmp_0001")
            junior = next(p for p in payload["employees"] if p["id"] == "junior")
            self.assertIsNone(junior["predictedManagerId"])
            self.assertIn(junior["bestCandidateId"], {"manager", "other_manager"})

    def test_direct_insert_updates_inference_and_survives_restart(self):
        self.insert_person("new_cfo", "Chief Financial Officer", "Executive",
                           "Company / Finance & Risk")
        with closing(connect(self.database, readonly=True)) as connection:
            payload = read_company(connection, "cmp_0001")
            new_hire = next(p for p in payload["employees"] if p["id"] == "new_cfo")
            self.assertEqual(new_hire["predictedManagerId"], "ceo")
            self.assertEqual(payload["company"]["employeeCount"], 5)
            self.assertEqual(read_index(connection)["summary"]["employeeCount"], 5)
        restarted = create_app(self.config)
        self.assertTrue(restarted.config["DATABASE_REUSED"])
        with closing(connect(self.database, readonly=True)) as connection:
            self.assertEqual(connection.execute("select count(*) from employees").fetchone()[0], 5)
        with gzip.open(self.snapshot, "rb") as source:
            self.assertEqual(source.read(16), b"SQLite format 3\0")

    def test_headcount_and_size_band_recalculate(self):
        with closing(connect(self.database)) as connection, connection:
            rows = [("cmp_0001", f"extra_{i:03d}", f"Extra {i}", "Analyst",
                     "Operations", "", "Sydney, AU", f"extra_{i}@example.test")
                    for i in range(125)]
            connection.executemany("insert into employees values (?,?,?,?,?,?,?,?)", rows)
            before = connection.execute("""
                select employee_count, size_band from company_overview
                where company_id = 'cmp_0001'
            """).fetchone()
            self.assertEqual(tuple(before), (129, "Small"))
            connection.execute("""
                insert into employees values
                ('cmp_0001', 'threshold_hire', 'Threshold Hire', 'Analyst',
                 'Operations', '', 'Sydney, AU', 'threshold@example.test')
            """)
            after = connection.execute("""
                select employee_count, size_band from company_overview
                where company_id = 'cmp_0001'
            """).fetchone()
            self.assertEqual(tuple(after), (130, "Growth"))

    def test_keys_reject_duplicate_and_unknown_company(self):
        with closing(connect(self.database)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""
                    insert into employees values
                    ('cmp_0001', 'ceo', 'Duplicate', 'CEO', '', '', '', '')
                """)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""
                    insert into employees values
                    ('missing', 'another', 'Another', 'Analyst', '', '', '', '')
                """)


if __name__ == "__main__":
    unittest.main()
