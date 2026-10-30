#!/usr/bin/env python3
"""Audit management-track hierarchy quality on a held-out company sample."""

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
    "Staff": 3,
    "Principal": 3,
    "Team Lead": 3,
    "Manager": 4,
    "Senior Manager": 5,
    "Director": 6,
    "Senior Director": 7,
    "VP": 8,
    "C-Suite": 9,
    "CEO": 10,
}

PEOPLE_MANAGER_LEVELS = {
    "Team Lead", "Manager", "Senior Manager", "Director",
    "Senior Director", "VP", "C-Suite", "CEO",
}
IC_LEVELS = {"Junior", "Individual Contributor", "Senior", "Staff", "Principal"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def is_qa(title: str) -> bool:
    text = title.lower()
    return "qa " in text or text.startswith("qa") or "quality assurance" in text


def valid_parent_levels(level: str) -> set[str]:
    if level in {"Junior", "Individual Contributor"}:
        return {"Team Lead", "Manager", "Senior Manager", "Director", "VP", "C-Suite"}
    if level in {"Senior", "Staff", "Principal"}:
        return {"Manager", "Senior Manager", "Director", "VP", "C-Suite"}
    if level == "Team Lead":
        return {"Manager", "Senior Manager", "Director", "VP", "C-Suite"}
    if level == "Manager":
        return {"Senior Manager", "Director", "VP", "C-Suite"}
    if level == "Senior Manager":
        return {"Director", "Senior Director", "VP", "C-Suite"}
    if level in {"Director", "Senior Director"}:
        return {"VP", "C-Suite"}
    if level == "VP":
        return {"C-Suite"}
    if level == "C-Suite":
        return {"CEO"}
    return set()


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

    truth_errors: list[str] = []
    qa_truth_mismatches: list[str] = []
    ic_people_managers: list[str] = []
    empty_people_managers: list[str] = []
    manager_spans: list[int] = []
    for row in sample:
        employee_id = row["employee_id"]
        level = row["canonical_level"]
        manager_id = row["manager_employee_id"]
        children = direct_reports[employee_id]

        if level in IC_LEVELS and children:
            ic_people_managers.append(employee_id)
        if level in PEOPLE_MANAGER_LEVELS:
            if not children:
                empty_people_managers.append(employee_id)
            manager_spans.append(len(children))

        if not manager_id:
            require(level == "CEO", f"non-CEO root: {employee_id}")
            continue
        manager = by_id[manager_id]
        require(manager["company_id"] == row["company_id"], "cross-company truth edge")
        if RANK[manager["canonical_level"]] <= RANK[level]:
            truth_errors.append(employee_id)
        if manager["canonical_level"] not in valid_parent_levels(level):
            truth_errors.append(employee_id)
        if is_qa(row["canonical_title"]) and level in IC_LEVELS | {"Team Lead"}:
            if not is_qa(manager["canonical_title"]):
                qa_truth_mismatches.append(employee_id)

    accepted = 0
    correct = 0
    accepted_rank_violations: list[str] = []
    accepted_non_manager_parents: list[str] = []
    accepted_qa_mismatches: list[str] = []
    accepted_by_level: Counter[str] = Counter()
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
            accepted_by_level[report["canonical_level"]] += 1
            if RANK[manager["canonical_level"]] <= RANK[report["canonical_level"]]:
                accepted_rank_violations.append(report["employee_id"])
            if manager["canonical_level"] not in PEOPLE_MANAGER_LEVELS:
                accepted_non_manager_parents.append(report["employee_id"])
            if (is_qa(report["canonical_title"])
                    and report["canonical_level"] in IC_LEVELS | {"Team Lead"}
                    and not is_qa(manager["canonical_title"])):
                accepted_qa_mismatches.append(report["employee_id"])

    precision = correct / accepted if accepted else 0.0
    require(not truth_errors, f"{len(set(truth_errors))} truth edges violate the management ladder")
    require(not ic_people_managers, f"{len(ic_people_managers)} ICs incorrectly have direct reports")
    require(not empty_people_managers, f"{len(empty_people_managers)} people managers have no reports")
    require(not qa_truth_mismatches, f"{len(qa_truth_mismatches)} QA truth edges leave the QA chain")
    require(not accepted_rank_violations,
            f"{len(accepted_rank_violations)} accepted managers are not more senior")
    require(not accepted_non_manager_parents,
            f"{len(accepted_non_manager_parents)} accepted edges point to IC titles")
    require(not accepted_qa_mismatches,
            f"{len(accepted_qa_mismatches)} accepted QA edges leave the QA chain")
    require(precision >= 0.965, f"sample precision is below 96.5%: {precision:.2%}")

    print("Hierarchy validation passed")
    print(f"Companies sampled: {len(selected):,}")
    print(f"Employees sampled: {len(sample):,}")
    print(f"Accepted reporting lines: {accepted:,}")
    print(f"Accepted precision: {precision:.2%}")
    print(f"People-manager span: {min(manager_spans):,}-{max(manager_spans):,}")
    print("Accepted edges by canonical level: " + json.dumps(dict(sorted(accepted_by_level.items()))))


if __name__ == "__main__":
    main()
