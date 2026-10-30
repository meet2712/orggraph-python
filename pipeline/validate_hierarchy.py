#!/usr/bin/env python3
"""Audit hierarchy quality on the held-out company sample."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


RANK = {
    "Junior": 0,
    "Individual Contributor": 1,
    "Senior": 2,
    "Lead": 3,
    "Manager": 4,
    "Director": 5,
    "VP": 6,
    "C-Suite": 7,
    "CEO": 8,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def is_qa(title: str) -> bool:
    return "qa " in title.lower() or title.lower().startswith("qa")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("public/data"))
    parser.add_argument("--sample-size", type=int, default=75)
    args = parser.parse_args()

    with (args.data_dir / "employees_ground_truth.csv").open(newline="", encoding="utf-8") as source:
        truth = list(csv.DictReader(source))
    company_ids = sorted({row["company_id"] for row in truth})
    require(0 < args.sample_size <= len(company_ids), "sample size is outside the company range")
    selected = set(company_ids[-args.sample_size:])
    sample = [row for row in truth if row["company_id"] in selected]
    by_id = {row["employee_id"]: row for row in sample}
    direct_reports: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sample:
        if row["manager_employee_id"]:
            direct_reports[row["manager_employee_id"]].append(row)

    junior_bypasses = []
    invalid_senior_parents = []
    qa_truth_mismatches = []
    empty_qa_managers = []
    for row in sample:
        manager_id = row["manager_employee_id"]
        if manager_id:
            manager = by_id[manager_id]
            require(manager["company_id"] == row["company_id"], "cross-company truth edge")
            require(RANK[manager["canonical_level"]] > RANK[row["canonical_level"]],
                    "truth manager is not more senior")
            if row["canonical_level"] == "Junior" and manager["canonical_level"] not in {"Senior", "Lead"}:
                junior_bypasses.append(row["employee_id"])
            if row["canonical_level"] == "Senior" and manager["canonical_level"] not in {
                "Lead", "Manager", "Director", "VP", "C-Suite"
            }:
                invalid_senior_parents.append(row["employee_id"])
            if "QA Engineer" in row["canonical_title"] and not is_qa(manager["canonical_title"]):
                qa_truth_mismatches.append(row["employee_id"])
        if row["canonical_title"] == "QA Manager":
            children = direct_reports[row["employee_id"]]
            if (row["canonical_team"].rsplit(" / ", 1)[-1] != "Quality"
                    or not children or any(not is_qa(child["canonical_title"]) for child in children)):
                empty_qa_managers.append(row["employee_id"])

    accepted = 0
    correct = 0
    accepted_rank_violations = []
    accepted_junior_bypasses = []
    accepted_qa_mismatches = []
    qa_manager_children: Counter[str] = Counter()
    for company_id in sorted(selected):
        payload = json.loads(
            (args.output_dir / "companies" / f"{company_id}.json").read_text(encoding="utf-8")
        )
        for person in payload["employees"]:
            manager_id = person.get("predictedManagerId")
            if not manager_id:
                continue
            accepted += 1
            report = by_id[person["id"]]
            manager = by_id[manager_id]
            correct += int(manager_id == report["manager_employee_id"])
            if RANK[manager["canonical_level"]] <= RANK[report["canonical_level"]]:
                accepted_rank_violations.append(report["employee_id"])
            if report["canonical_level"] == "Junior" and manager["canonical_level"] not in {"Senior", "Lead"}:
                accepted_junior_bypasses.append(report["employee_id"])
            if "QA Engineer" in report["canonical_title"] and not is_qa(manager["canonical_title"]):
                accepted_qa_mismatches.append(report["employee_id"])
            if manager["canonical_title"] == "QA Manager":
                qa_manager_children[manager_id] += 1

    qa_managers = [row for row in sample if row["canonical_title"] == "QA Manager"]
    visible_qa_managers = sum(qa_manager_children[row["employee_id"]] > 0 for row in qa_managers)
    precision = correct / accepted if accepted else 0.0

    require(not junior_bypasses, f"{len(junior_bypasses)} juniors bypass the senior/lead layer")
    require(not invalid_senior_parents, f"{len(invalid_senior_parents)} seniors have invalid parents")
    require(not qa_truth_mismatches, f"{len(qa_truth_mismatches)} QA truth edges leave the QA chain")
    require(not empty_qa_managers, f"{len(empty_qa_managers)} QA managers have invalid scope or reports")
    require(not accepted_rank_violations,
            f"{len(accepted_rank_violations)} accepted managers are not canonically more senior")
    require(not accepted_junior_bypasses,
            f"{len(accepted_junior_bypasses)} accepted junior edges skip the senior/lead layer")
    require(not accepted_qa_mismatches,
            f"{len(accepted_qa_mismatches)} accepted QA edges leave the QA chain")
    require(precision >= 0.95, f"sample precision is below 95%: {precision:.2%}")

    print("Hierarchy validation passed")
    print(f"Companies sampled: {len(selected):,}")
    print(f"Employees sampled: {len(sample):,}")
    print(f"Accepted reporting lines: {accepted:,}")
    print(f"Accepted precision: {precision:.2%}")
    print(f"QA managers with an accepted direct report: {visible_qa_managers:,}/{len(qa_managers):,}")


if __name__ == "__main__":
    main()
