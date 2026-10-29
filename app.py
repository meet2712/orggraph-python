"""A small Flask app for browsing saved org-chart predictions."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, abort, current_app, g, render_template


ROOT = Path(__file__).resolve().parent
COMPANY_ID = re.compile(r"cmp_\d{4}\Z")
DEFAULT_COMPANY = "cmp_0001"


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def validate_company(payload: dict, company_id: str) -> None:
    """Reject incomplete records and broken reporting links before serving them."""
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
        people[employee_id] = employee

    for employee in employees:
        manager_id = employee.get("predictedManagerId")
        if manager_id is not None and not isinstance(manager_id, str):
            raise ValueError(f"Invalid manager ID in {company_id}")
        if manager_id and manager_id not in people:
            raise ValueError(f"Manager is outside the company: {company_id}")

    for employee in employees:
        visited = set()
        cursor = employee["id"]
        while cursor:
            if cursor in visited:
                raise ValueError(f"Circular reporting line in {company_id}")
            visited.add(cursor)
            cursor = people[cursor].get("predictedManagerId")


def initialize_database(app: Flask) -> None:
    """Import saved predictions into SQLite. Starting the app never trains a model."""
    data_dir = Path(app.config["DATA_DIR"])
    index = read_json(data_dir / "index.json")
    evaluation = read_json(data_dir / "evaluation.json")
    companies = index.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("The company directory is empty")

    rows = []
    seen = set()
    for company in companies:
        if not isinstance(company, dict):
            raise ValueError("Invalid entry in the company directory")
        company_id = company.get("id", "")
        if not isinstance(company_id, str) or not COMPANY_ID.fullmatch(company_id):
            raise ValueError("Invalid company ID in the dataset")
        if company_id in seen:
            raise ValueError(f"Duplicate company ID: {company_id}")
        seen.add(company_id)
        payload = read_json(data_dir / "companies" / f"{company_id}.json")
        validate_company(payload, company_id)
        rows.append((company_id, json.dumps(payload, separators=(",", ":"))))

    database = Path(app.config["DATABASE"])
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS companies "
                "(company_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute("DELETE FROM companies")
            connection.executemany(
                "INSERT INTO companies (company_id, payload) VALUES (?, ?)", rows
            )

    app.config["DATASET_INDEX"] = index
    app.config["EVALUATION"] = evaluation


def get_database() -> sqlite3.Connection:
    """Use one connection per request, closed when that request ends."""
    if "database" not in g:
        g.database = sqlite3.connect(current_app.config["DATABASE"])
        g.database.row_factory = sqlite3.Row
    return g.database


def chart_context(payload: dict) -> dict:
    """Build a forest from accepted predictions, leaving every unknown link open."""
    employees = payload["employees"]
    people = {employee["id"]: employee for employee in employees}
    connected = set()
    children = {}
    unresolved = []

    for employee in employees:
        manager_id = employee.get("predictedManagerId")
        if manager_id:
            connected.update((employee["id"], manager_id))
            children.setdefault(manager_id, []).append(employee)
        elif employee["inferredLevel"] != "CEO":
            unresolved.append(employee)
        if employee["inferredLevel"] == "CEO":
            connected.add(employee["id"])

    roots = [
        employee for employee in employees
        if employee["id"] in connected and not employee.get("predictedManagerId")
    ]
    return {
        "employees_by_id": people,
        "roots": roots,
        "children": children,
        "unresolved": unresolved,
    }


def page_context(page: str, company_id: str = DEFAULT_COMPANY) -> dict:
    if not COMPANY_ID.fullmatch(company_id):
        abort(404)
    row = get_database().execute(
        "SELECT payload FROM companies WHERE company_id = ?", (company_id,)
    ).fetchone()
    if row is None:
        abort(404)
    payload = json.loads(row["payload"])
    index = current_app.config["DATASET_INDEX"]
    return {
        "page": page,
        "index": index,
        "evaluation": current_app.config["EVALUATION"],
        "company": payload,
        "companies": index["companies"],
        "selected_id": company_id,
        **chart_context(payload),
    }


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="public", static_url_path="")
    app.config.from_mapping(
        DATABASE=ROOT / "instance" / "orggraph.sqlite3",
        DATA_DIR=ROOT / "public" / "data",
    )
    if test_config:
        app.config.update(test_config)
    initialize_database(app)

    app.jinja_env.filters["percent"] = lambda value: f"{value * 100:.1f}%"
    app.jinja_env.filters["points"] = lambda value: f"{value * 100:.1f}"
    app.jinja_env.filters["count"] = lambda value: f"{value:,}"

    @app.teardown_appcontext
    def close_database(_error: BaseException | None) -> None:
        connection = g.pop("database", None)
        if connection is not None:
            connection.close()

    @app.get("/")
    def home():
        return render_template("index.html", **page_context("chart"))

    @app.get("/companies/<company_id>.html")
    def company_page(company_id: str):
        return render_template("index.html", **page_context("chart", company_id))

    @app.get("/results.html")
    def results_page():
        return render_template("index.html", **page_context("results"))

    @app.get("/approach.html")
    def approach_page():
        return render_template("index.html", **page_context("approach"))

    @app.get("/health")
    def health():
        get_database().execute("SELECT 1").fetchone()
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
