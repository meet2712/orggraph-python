"""A small Flask app for browsing saved org-chart predictions."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from flask import Flask, abort, current_app, g, render_template, send_file

from database import connect, load_snapshot, read_company, read_json, write_compressed_snapshot


ROOT = Path(__file__).resolve().parent
COMPANY_ID = re.compile(r"cmp_\d{4}\Z")
DEFAULT_COMPANY = "cmp_0001"


def initialize_database(app: Flask) -> None:
    """Load a checked relational snapshot without running inference."""
    data_dir = Path(app.config["DATA_DIR"])
    index = read_json(data_dir / "index.json")
    evaluation = read_json(data_dir / "evaluation.json")
    companies = index.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("The company directory is empty")
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
    run_id = load_snapshot(
        Path(app.config["DATABASE"]), data_dir, Path(app.config["RAW_DATA_DIR"]),
        Path(app.config["MODEL_PATH"]), index, evaluation,
    )
    write_compressed_snapshot(Path(app.config["DATABASE"]), Path(app.config["DATABASE_SNAPSHOT"]))
    app.config["ACTIVE_RUN_ID"] = run_id
    app.config["DATASET_INDEX"] = index
    app.config["EVALUATION"] = evaluation


def get_database() -> sqlite3.Connection:
    """Use one connection per request, closed when that request ends."""
    if "database" not in g:
        g.database = connect(current_app.config["DATABASE"], readonly=True)
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
    payload = read_company(get_database(), current_app.config["ACTIVE_RUN_ID"], company_id)
    if payload is None:
        abort(404)
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
        RAW_DATA_DIR=ROOT / "data",
        MODEL_PATH=ROOT / "model" / "model.json",
        DATABASE_SNAPSHOT=ROOT / "instance" / "snapshot.sqlite.gz",
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

    @app.get("/data.html")
    def data_page():
        return render_template("index.html", **page_context("data"))

    @app.get("/database/snapshot.sqlite.gz")
    def database_snapshot():
        return send_file(
            app.config["DATABASE_SNAPSHOT"], mimetype="application/octet-stream",
            as_attachment=True, download_name="orggraph.sqlite.gz", max_age=0,
        )

    @app.get("/health")
    def health():
        row = get_database().execute(
            "SELECT load_status FROM inference_runs WHERE run_id = ?",
            (app.config["ACTIVE_RUN_ID"],),
        ).fetchone()
        if row is None or row["load_status"] != "ready":
            abort(503)
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
