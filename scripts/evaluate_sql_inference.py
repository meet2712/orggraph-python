"""Evaluate SQL reporting decisions against held-out generated labels.

The answer key stays in a CSV outside the application database. This script
never writes an employee-to-manager mapping into SQLite.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def evaluate(database: Path, labels: Path, minimum_company_number: int = 426) -> dict:
    truth = {}
    with labels.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if int(row["company_id"].split("_")[1]) >= minimum_company_number:
                truth[(row["company_id"], row["employee_id"])] = row["manager_employee_id"] or None

    accepted = correct = eligible = roots = seen = 0
    query = (ROOT / "sql/company_predictions.sql").read_text(encoding="utf-8")
    with sqlite3.connect(database) as connection:
        for company_id in sorted({company_id for company_id, _ in truth}):
            for result in connection.execute(query, {"company_id": company_id}):
                result_company_id, employee_id, manager_id, _, _, _, decision = result
                key = result_company_id, employee_id
                if key not in truth:
                    continue
                seen += 1
                expected = truth[key]
                if expected is None:
                    roots += 1
                    continue
                eligible += 1
                if decision == "accepted" and manager_id is not None:
                    accepted += 1
                    correct += manager_id == expected

    if seen != len(truth):
        raise ValueError(f"SQL view returned {seen} of {len(truth)} benchmark employees")

    return {
        "companies": len({company_id for company_id, _ in truth}),
        "employees": len(truth),
        "roots": roots,
        "eligible_reporting_lines": eligible,
        "accepted_reporting_lines": accepted,
        "correct_reporting_lines": correct,
        "incorrect_reporting_lines": accepted - correct,
        "precision": round(correct / accepted, 4) if accepted else 0.0,
        "coverage": round(accepted / eligible, 4) if eligible else 0.0,
        "recall": round(correct / eligible, 4) if eligible else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "instance/orggraph.sqlite3")
    parser.add_argument("--labels", type=Path, default=ROOT / "data/employees_ground_truth.csv")
    parser.add_argument("--minimum-company-number", type=int, default=426)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-precision", type=float, default=0.0)
    arguments = parser.parse_args()
    result = evaluate(arguments.database, arguments.labels, arguments.minimum_company_number)
    if result["precision"] < arguments.min_precision:
        raise SystemExit(
            f"Held-out SQL precision {result['precision']:.2%} is below "
            f"{arguments.min_precision:.2%}"
        )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
