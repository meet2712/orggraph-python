#!/usr/bin/env python3
"""Validate structure, leakage boundaries, and basic messiness."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


LEVEL_RANK = {
    "CEO": 8,
    "C-Suite": 7,
    "VP": 6,
    "Director": 5,
    "Manager": 4,
    "Lead": 3,
    "Senior": 2,
    "Individual Contributor": 1,
    "Junior": 0,
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    companies = read_csv(args.data_dir / "companies.csv")
    messy = read_csv(args.data_dir / "employees_messy.csv")
    truth = read_csv(args.data_dir / "employees_ground_truth.csv")
    edges = read_csv(args.data_dir / "reporting_edges.csv")

    require(len(companies) >= 500, f"expected at least 500 companies; found {len(companies)}")
    require(len(messy) == len(truth), "messy and ground-truth row counts differ")
    require(len({row['company_id'] for row in companies}) == len(companies), "duplicate company_id")
    require(len({row['employee_id'] for row in truth}) == len(truth), "duplicate employee_id in truth")
    require(len({row['employee_id'] for row in messy}) == len(messy), "duplicate employee_id in messy input")

    forbidden_input_columns = {
        "manager_employee_id", "canonical_level", "canonical_department",
        "canonical_team", "noise_profile"
    }
    require(
        not forbidden_input_columns.intersection(messy[0]),
        "messy input leaks target or canonical fields",
    )

    truth_by_id = {row["employee_id"]: row for row in truth}
    company_counts = Counter(row["company_id"] for row in truth)
    declared_counts = {row["company_id"]: int(row["employee_count"]) for row in companies}
    require(set(company_counts) == set(declared_counts), "company coverage differs between files")
    for company_id, count in company_counts.items():
        require(count >= 100, f"{company_id} has only {count} employees")
        require(count == declared_counts[company_id], f"{company_id} declared headcount does not match")

    roots = Counter(row["company_id"] for row in truth if not row["manager_employee_id"])
    for company_id in declared_counts:
        require(roots[company_id] == 1, f"{company_id} must have exactly one root")

    for row in truth:
        manager_id = row["manager_employee_id"]
        if not manager_id:
            require(row["canonical_level"] == "CEO", "non-CEO root found")
            continue
        require(manager_id in truth_by_id, f"missing manager {manager_id}")
        manager = truth_by_id[manager_id]
        require(manager["company_id"] == row["company_id"], "cross-company manager edge")
        require(
            LEVEL_RANK[manager["canonical_level"]] > LEVEL_RANK[row["canonical_level"]],
            f"manager is not more senior for {row['employee_id']}",
        )

    parent = {row["employee_id"]: row["manager_employee_id"] for row in truth}
    for employee_id in parent:
        seen: set[str] = set()
        cursor = employee_id
        while cursor:
            require(cursor not in seen, f"cycle detected from {employee_id}")
            seen.add(cursor)
            cursor = parent[cursor]

    expected_edges = sum(count - 1 for count in company_counts.values())
    require(len(edges) == expected_edges, "edge count must equal employees minus one root per company")
    require(sum(1 for row in messy if not row["job_title"]) > 0, "no missing titles were generated")
    require(
        sum(1 for row in messy if row["department"] in {"", "N/A", "Unknown", "-"}) > 0,
        "no missing/sentinel departments were generated",
    )
    require(sum(1 for row in messy if not row["location"]) > 0, "no missing locations were generated")
    require(
        sum(1 for row in messy if row["team"] in {"", "N/A", "Unknown", "-"}) > 0,
        "no missing/sentinel teams were generated",
    )

    industries = {row["industry"] for row in companies}
    departments = {row["canonical_department"] for row in truth}
    require(len(industries) >= 8, "industry diversity is too low")
    require(len(departments) >= 10, "department diversity is too low")

    print("Dataset validation passed")
    print(f"Companies: {len(companies):,}")
    print(f"Employees: {len(truth):,}")
    print(f"Reporting edges: {len(edges):,}")
    print(f"Company size range: {min(company_counts.values()):,}-{max(company_counts.values()):,}")
    print(f"Industries: {len(industries)}")
    print(f"Departments (including Executive): {len(departments)}")


if __name__ == "__main__":
    main()

