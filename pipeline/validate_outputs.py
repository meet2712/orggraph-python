#!/usr/bin/env python3
"""Validate exported predictions and reviewer-facing JSON artifacts."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


RANK = {
    "Unknown": 1,
    "Junior IC": 0,
    "Individual Contributor": 1,
    "Senior IC": 2,
    "Lead / Principal IC": 3,
    "Principal / Staff IC": 3,
    "Team Lead / Supervisor": 3,
    "Manager": 4,
    "Senior Manager": 5,
    "Director": 6,
    "Senior Director": 7,
    "VP / Head": 8,
    "C-Suite": 9,
    "CEO": 10,
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
    require(evaluation["model"]["precision"] >= 0.965, "held-out precision is below 96.5%")
    require(evaluation["model"]["coverage"] >= 0.75, "held-out coverage is below 75%")
    require(evaluation["model"]["candidate_recall"] >= 0.88, "candidate recall is below 88%")

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
        expected_coverage = float(Decimal(str(resolved / max(eligible, 1))).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        ))
        require(abs(summary["coverage"] - expected_coverage) < 0.00001,
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
