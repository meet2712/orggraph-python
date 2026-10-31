"""Serve the SQL-derived org chart and supporting pages."""

from __future__ import annotations

import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, abort, current_app, g, render_template, send_file

from database import (
    connect, ensure_snapshot, read_company, read_company_csv, read_index,
    read_json, write_compressed_snapshot,
)


ROOT = Path(__file__).resolve().parent
COMPANY_ID = re.compile(r"cmp_\d{4}\Z")
DEFAULT_COMPANY = "cmp_0001"


def initialize_database(app: Flask) -> None:
    """Prepare the SQLite database and load published metadata."""
    public_data_dir = Path(app.config["DATA_DIR"])
    raw_dir = Path(app.config["RAW_DATA_DIR"])
    dataset_summary = read_json(raw_dir / "dataset_summary.json")
    companies = read_company_csv(raw_dir / "companies.csv")
    if not companies:
        raise ValueError("The company directory is empty")
    if len(companies) != dataset_summary.get("companies"):
        raise ValueError("Company count does not match the dataset summary")
    seen = set()
    for company in companies:
        company_id = company.get("company_id", "")
        if not isinstance(company_id, str) or not COMPANY_ID.fullmatch(company_id):
            raise ValueError("Invalid company ID in the dataset")
        if company_id in seen:
            raise ValueError(f"Duplicate company ID: {company_id}")
        seen.add(company_id)
    reused = ensure_snapshot(
        Path(app.config["DATABASE"]), Path(app.config["DATABASE_SNAPSHOT"]),
        raw_dir, companies, dataset_summary["employees"],
    )
    app.config["DATABASE_REUSED"] = reused
    app.config["DATASET_SUMMARY"] = dataset_summary
    app.config["SQL_EVALUATION"] = read_json(public_data_dir / "sql_evaluation.json")


def get_database() -> sqlite3.Connection:
    """Return the read-only SQLite connection for the current request."""
    if "database" not in g:
        g.database = connect(current_app.config["DATABASE"], readonly=True)
    return g.database


def chart_context(payload: dict) -> dict:
    """Arrange accepted reporting lines into chart roots and branches."""
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
    payload = read_company(get_database(), company_id)
    if payload is None:
        abort(404)
    index = current_app.config.get("STATIC_EXPORT_INDEX")
    if index is None:
        index = read_index(get_database())
    settings = get_database().execute(
        "select score_threshold, margin_threshold from reporting_thresholds",
    ).fetchone()
    return {
        "page": page,
        "index": index,
        "dataset_summary": current_app.config["DATASET_SUMMARY"],
        "sql_evaluation": current_app.config["SQL_EVALUATION"],
        "threshold": {"score": settings["score_threshold"],
                      "margin": settings["margin_threshold"]},
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
        DATABASE_SNAPSHOT=ROOT / "instance" / "snapshot.sqlite.gz",
    )
    if test_config:
        app.config.update(test_config)
    initialize_database(app)

    def display_points(value):
        return str((Decimal(str(value)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    app.jinja_env.filters["percent"] = lambda value: f"{display_points(value)}%"
    app.jinja_env.filters["points"] = display_points
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

    @app.get("/schema.html")
    def schema_page():
        return render_template("index.html", **page_context("schema"),
                               schema=read_json(ROOT / "public/database-schema.json"))

    @app.get("/database/snapshot.sqlite.gz")
    def database_snapshot():
        # Include edits made directly in the local SQLite source tables.
        write_compressed_snapshot(Path(app.config["DATABASE"]),
                                  Path(app.config["DATABASE_SNAPSHOT"]))
        return send_file(
            app.config["DATABASE_SNAPSHOT"], mimetype="application/octet-stream",
            as_attachment=True, download_name="orggraph.sqlite.gz", max_age=0,
        )

    @app.get("/health")
    def health():
        connection = get_database()
        settings = connection.execute("select score_threshold from reporting_thresholds").fetchone()
        tables = {row[0] for row in connection.execute(
            "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
        )}
        if settings is None or tables != {"companies", "employees"}:
            abort(503)
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
