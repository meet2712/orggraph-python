#!/usr/bin/env python3
"""Validate exported predictions and reviewer-facing JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


RANK = {
    "Unknown": 1,
    "Junior IC": 0,
    "Individual Contributor": 1,
    "Senior IC": 2,
    "Lead / Principal IC": 3,
    "Manager": 4,
    "Director": 5,
    "VP / Head": 6,
    "C-Suite": 7,
    "CEO": 8,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("public/data"))
    args = parser.parse_args()

    index = json.loads((args.output_dir / "index.json").read_text(encoding="utf-8"))
    evaluation = json.loads((args.output_dir / "evaluation.json").read_text(encoding="utf-8"))
    companies = index["companies"]
    require(len(companies) == evaluation["dataset"]["companies"], "company count mismatch")
    require(evaluation["model"]["precision"] >= 0.90, "held-out precision is below 90%")
    require(evaluation["model"]["coverage"] > evaluation["baseline"]["coverage"], "model does not improve coverage")

    employee_total = 0
    edge_total = 0
    for summary in companies:
        path = args.output_dir / "companies" / f"{summary['id']}.json"
        require(path.exists(), f"missing {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        employees = payload["employees"]
        by_id = {row["id"]: row for row in employees}
        require(len(by_id) == len(employees), f"duplicate employee in {summary['id']}")
        require(len(employees) == summary["employeeCount"], f"headcount mismatch in {summary['id']}")
        roots = [row for row in employees if row["isRoot"]]
        require(len(roots) == 1, f"expected one ground-truth root in {summary['id']}")

        resolved = 0
        for employee in employees:
            manager_id = employee["predictedManagerId"]
            if not manager_id:
                continue
            resolved += 1
            require(manager_id in by_id, f"cross-company or missing manager in {summary['id']}")
            manager = by_id[manager_id]
            require(
                RANK[manager["inferredLevel"]] > RANK[employee["inferredLevel"]],
                f"manager is not more senior for {employee['id']}",
            )
            seen: set[str] = set()
            cursor = employee["id"]
            while cursor:
                require(cursor not in seen, f"cycle detected in {summary['id']}")
                seen.add(cursor)
                cursor = by_id[cursor]["predictedManagerId"]

        require(resolved == summary["resolved"], f"resolved count mismatch in {summary['id']}")
        unresolved = sum(not e["predictedManagerId"] and e["inferredLevel"] != "CEO" for e in employees)
        require(unresolved == summary["unresolved"], f"unresolved count mismatch in {summary['id']}")
        eligible = sum(e["inferredLevel"] != "CEO" for e in employees)
        require(abs(summary["coverage"] - round(resolved / max(eligible, 1), 4)) < 0.00001,
                f"company coverage mismatch in {summary['id']}")
        employee_total += len(employees)
        edge_total += resolved

    require(employee_total == index["summary"]["employeeCount"], "index employee total mismatch")
    print("Prediction validation passed")
    print(f"Companies: {len(companies):,}")
    print(f"Employees: {employee_total:,}")
    print(f"Resolved prediction edges: {edge_total:,}")
    print(f"Held-out precision: {evaluation['model']['precision']:.2%}")
    print(f"Held-out coverage: {evaluation['model']['coverage']:.2%}")


if __name__ == "__main__":
    main()
