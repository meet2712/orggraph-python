"""Check startup, database reads, routes, and the no-guessing boundary."""

import json
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
import unittest

from jinja2 import DictLoader

from app import chart_context, create_app, get_database


def employee(employee_id, level, manager=None, candidate=None):
    return {
        "id": employee_id,
        "name": employee_id,
        "inferredLevel": level,
        "predictedManagerId": manager,
        "bestCandidateId": candidate,
        "groundTruthManagerId": "ceo" if employee_id != "ceo" else None,
    }


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        data = self.root / "data"
        (data / "companies").mkdir(parents=True)
        self.payload = {
            "company": {"id": "cmp_0001", "name": "Example Company"},
            "summary": {"resolved": 1},
            "employees": [
                employee("ceo", "CEO"),
                employee("manager", "Manager", candidate="ceo"),
                employee("report", "Individual Contributor", manager="manager"),
                employee("unresolved", "Individual Contributor", candidate="ceo"),
            ],
        }
        self.company_file = data / "companies" / "cmp_0001.json"
        self.company_file.write_text(json.dumps(self.payload))
        (data / "index.json").write_text(json.dumps({
            "companies": [{"id": "cmp_0001", "name": "Example Company"}],
            "summary": {"companyCount": 1},
        }))
        (data / "evaluation.json").write_text(json.dumps({"split": {"testCompanies": 1}}))
        self.config = {
            "TESTING": True,
            "DATABASE": self.root / "orggraph.sqlite3",
            "DATA_DIR": data,
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

    def test_startup_imports_predictions_into_sqlite(self):
        with closing(sqlite3.connect(self.config["DATABASE"])) as connection:
            row = connection.execute(
                "SELECT payload FROM companies WHERE company_id = ?", ("cmp_0001",)
            ).fetchone()
        self.assertEqual(json.loads(row[0]), self.payload)
        self.assertEqual(self.client.get("/health").json, {"status": "ok"})

    def test_all_pages_use_the_selected_company(self):
        expected = {
            "/": "chart|cmp_0001|cmp_0001",
            "/companies/cmp_0001.html": "chart|cmp_0001|cmp_0001",
            "/results.html": "results|cmp_0001|cmp_0001",
            "/approach.html": "approach|cmp_0001|cmp_0001",
        }
        for url, text in expected.items():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, text)

    def test_unknown_or_malformed_company_is_404(self):
        for company_id in ("cmp_9999", "not-a-company", "cmp_0001' OR 1=1"):
            with self.subTest(company_id=company_id):
                response = self.client.get(f"/companies/{company_id}.html")
                self.assertEqual(response.status_code, 404)

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

    def test_database_connection_closes_after_the_request_context(self):
        with self.app.test_request_context("/"):
            connection = get_database()
            self.assertIs(connection, get_database())
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_startup_rejects_a_broken_reporting_link(self):
        self.payload["employees"][2]["predictedManagerId"] = "missing-manager"
        self.company_file.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, "Manager is outside the company"):
            create_app(self.config)

    def test_startup_rejects_a_cycle(self):
        self.payload["employees"][1]["predictedManagerId"] = "report"
        self.company_file.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, "Circular reporting line"):
            create_app(self.config)


if __name__ == "__main__":
    unittest.main()
