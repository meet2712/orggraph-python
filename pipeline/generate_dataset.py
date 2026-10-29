#!/usr/bin/env python3
"""Generate a reproducible synthetic org-chart inference dataset."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter
from pathlib import Path


INDUSTRIES = [
    "B2B SaaS", "FinTech", "Cybersecurity", "HealthTech", "E-commerce",
    "Logistics", "Professional Services", "Clean Energy",
    "Telecommunications", "EdTech",
]

LOCATIONS = [
    "Sydney, AU", "Melbourne, AU", "Brisbane, AU", "Perth, AU",
    "Bengaluru, IN", "Singapore, SG", "London, UK", "New York, US",
    "San Francisco, US", "Toronto, CA",
]

FIRST_NAMES = [
    "Aarav", "Aisha", "Akira", "Amelia", "Arjun", "Ava", "Ben", "Camila",
    "Charlotte", "Chen", "Daniel", "Diya", "Ethan", "Fatima", "Grace", "Hana",
    "Harper", "Henry", "Isla", "Jack", "Jia", "Kabir", "Kai", "Layla", "Leo",
    "Liam", "Maya", "Meera", "Mia", "Mohammed", "Nina", "Noah", "Oliver",
    "Olivia", "Priya", "Ravi", "Saanvi", "Samuel", "Sara", "Sofia", "Theo",
    "Vihaan", "William", "Yuki", "Zara",
]

LAST_NAMES = [
    "Anderson", "Brown", "Chen", "Davis", "Evans", "Garcia", "Gupta", "Harris",
    "Jackson", "Johnson", "Khan", "Kim", "Kumar", "Lee", "Lewis", "Martin",
    "Miller", "Nguyen", "Patel", "Robinson", "Shah", "Singh", "Smith", "Taylor",
    "Thomas", "Thompson", "Walker", "Wang", "White", "Williams", "Wilson", "Young",
]

COMPANY_LEFT = [
    "Amber", "Apex", "Arc", "Atlas", "Blue", "Bright", "Cloud", "Core", "Delta",
    "Ever", "Flux", "Green", "Harbor", "Helio", "Iron", "Lattice", "Lumen", "Metro",
    "Nimbus", "North", "Nova", "Orbit", "Peak", "Pixel", "Quantum", "River", "Signal",
    "Silver", "Summit", "Terra", "True", "Vertex", "West", "Wild", "Zenith",
]

COMPANY_RIGHT = [
    "Bridge", "Circuit", "Collective", "Dynamics", "Forge", "Grid", "Labs", "Link",
    "Logic", "Matrix", "Networks", "Path", "Point", "Pulse", "Scale", "Shift", "Stack",
    "Systems", "Works", "Wave",
]

DEPARTMENT_WEIGHTS = {
    "Engineering": 0.24, "Sales": 0.18, "Customer Success": 0.11,
    "Operations": 0.09, "Product": 0.08, "Marketing": 0.07,
    "Data & Analytics": 0.07, "Finance": 0.045, "People": 0.04,
    "Security": 0.035, "IT": 0.035, "Legal": 0.02,
}

INDUSTRY_ADJUSTMENTS = {
    "FinTech": {"Data & Analytics": 1.35, "Security": 1.45, "Finance": 1.25},
    "Cybersecurity": {"Security": 2.6, "Engineering": 1.2, "Sales": 1.1},
    "HealthTech": {"Security": 1.35, "Legal": 1.4, "Data & Analytics": 1.2},
    "E-commerce": {"Operations": 1.45, "Marketing": 1.3, "Data & Analytics": 1.2},
    "Logistics": {"Operations": 1.8, "IT": 1.25},
    "Professional Services": {"Sales": 1.25, "Operations": 1.25, "Engineering": 0.7},
    "Clean Energy": {"Operations": 1.4, "Engineering": 1.15, "Legal": 1.25},
    "Telecommunications": {"Engineering": 1.25, "IT": 1.4, "Operations": 1.3},
    "EdTech": {"Customer Success": 1.3, "Product": 1.2},
}

LEADER_TITLES = {
    "Engineering": ["Chief Technology Officer", "VP of Engineering", "Head of Engineering"],
    "Sales": ["Chief Revenue Officer", "VP of Sales", "Head of Sales"],
    "Customer Success": ["Chief Customer Officer", "VP of Customer Success", "Head of Customer Success"],
    "Operations": ["Chief Operating Officer", "VP of Operations", "Head of Operations"],
    "Product": ["Chief Product Officer", "VP of Product", "Head of Product"],
    "Marketing": ["Chief Marketing Officer", "VP of Marketing", "Head of Marketing"],
    "Data & Analytics": ["Chief Data Officer", "VP of Data", "Head of Data & Analytics"],
    "Finance": ["Chief Financial Officer", "VP of Finance", "Head of Finance"],
    "People": ["Chief People Officer", "VP of People", "Head of People"],
    "Security": ["Chief Information Security Officer", "VP of Security", "Head of Security"],
    "IT": ["Chief Information Officer", "VP of IT", "Head of IT"],
    "Legal": ["General Counsel", "VP of Legal", "Head of Legal"],
}

DIRECTOR_TITLES = {
    department: [f"Director of {department}", f"Senior Director of {department}"]
    for department in DEPARTMENT_WEIGHTS
}

MANAGER_TITLES = {
    "Engineering": ["Engineering Manager", "Software Development Manager", "QA Manager"],
    "Sales": ["Sales Manager", "Regional Sales Manager", "Business Development Manager"],
    "Customer Success": ["Customer Success Team Manager", "Client Success Lead", "Support Manager"],
    "Operations": ["Operations Manager", "Business Operations Manager", "Program Lead"],
    "Product": ["Group Product Manager", "Product Team Lead", "Product Operations Manager"],
    "Marketing": ["Marketing Manager", "Growth Marketing Manager", "Demand Generation Manager"],
    "Data & Analytics": ["Data Engineering Manager", "Analytics Manager", "Data Science Manager"],
    "Finance": ["Finance Manager", "FP&A Manager", "Accounting Manager"],
    "People": ["People Operations Manager", "HR Manager", "Talent Acquisition Manager"],
    "Security": ["Security Engineering Manager", "GRC Manager", "Security Operations Manager"],
    "IT": ["IT Manager", "Infrastructure Manager", "Service Desk Manager"],
    "Legal": ["Legal Operations Manager", "Senior Counsel", "Compliance Manager"],
}

IC_TITLES = {
    "Engineering": ["Software Engineer", "Backend Engineer", "Frontend Developer", "DevOps Engineer", "QA Engineer"],
    "Sales": ["Account Executive", "Sales Development Representative", "Business Development Representative", "Account Manager"],
    "Customer Success": ["Customer Success Manager", "Implementation Consultant", "Support Specialist", "Onboarding Specialist"],
    "Operations": ["Operations Analyst", "Program Coordinator", "Business Operations Specialist", "Project Coordinator"],
    "Product": ["Product Manager", "Product Designer", "Product Analyst", "UX Researcher"],
    "Marketing": ["Growth Marketer", "Content Strategist", "Demand Generation Specialist", "Marketing Analyst"],
    "Data & Analytics": ["Data Engineer", "Data Analyst", "BI Analyst", "Data Scientist", "Machine Learning Engineer"],
    "Finance": ["Financial Analyst", "Accountant", "FP&A Analyst", "Payroll Specialist"],
    "People": ["People Partner", "Recruiter", "HR Coordinator", "Talent Specialist"],
    "Security": ["Security Engineer", "Security Analyst", "GRC Analyst", "Incident Response Specialist"],
    "IT": ["Systems Administrator", "IT Support Specialist", "Network Engineer", "Cloud Administrator"],
    "Legal": ["Legal Counsel", "Paralegal", "Compliance Analyst", "Contracts Specialist"],
}

DEPARTMENT_ALIASES = {
    "Engineering": ["Eng", "Tech", "R&D", "Software"],
    "Sales": ["Revenue", "Commercial", "GTM", "Sales"],
    "Customer Success": ["CS", "Cust Success", "Client Success", "CX"],
    "Operations": ["Ops", "BizOps", "Business Ops", "Operations"],
    "Product": ["Prod", "Product", "Product & Design"],
    "Marketing": ["Mktg", "Growth", "Demand Gen", "Marketing"],
    "Data & Analytics": ["Data", "Analytics", "BI", "Data/AI"],
    "Finance": ["Fin", "Finance", "Accounting"],
    "People": ["HR", "People Ops", "People & Culture"],
    "Security": ["InfoSec", "Cyber", "Security", "GRC"],
    "IT": ["IT", "Info Tech", "Infrastructure"],
    "Legal": ["Legal", "Compliance", "Risk & Legal"],
}

DEPARTMENT_TEAMS = {
    "Engineering": ["Platform", "Core Services", "Developer Experience", "Applications", "Quality", "Infrastructure", "Mobile", "Web"],
    "Sales": ["Enterprise", "Mid-Market", "SMB", "Partnerships", "APAC", "EMEA", "Americas"],
    "Customer Success": ["Enterprise Success", "Commercial Success", "Onboarding", "Support", "Implementations"],
    "Operations": ["Business Operations", "Revenue Operations", "Programs", "Delivery", "Strategy"],
    "Product": ["Core Product", "Growth Product", "Platform Product", "Design", "Research"],
    "Marketing": ["Growth", "Demand Generation", "Content", "Brand", "Product Marketing"],
    "Data & Analytics": ["Data Platform", "Analytics", "Data Science", "ML Platform", "Business Intelligence"],
    "Finance": ["Financial Planning", "Accounting", "Payroll", "Commercial Finance"],
    "People": ["People Operations", "Talent", "Business Partners", "Learning"],
    "Security": ["Security Engineering", "GRC", "Security Operations", "Identity"],
    "IT": ["Infrastructure", "Service Desk", "Enterprise Applications", "Cloud Operations"],
    "Legal": ["Commercial Legal", "Compliance", "Legal Operations", "Privacy"],
}

ABBREVIATIONS = {
    "Chief Technology Officer": "CTO", "Chief Revenue Officer": "CRO",
    "Chief Customer Officer": "CCO", "Chief Operating Officer": "COO",
    "Chief Product Officer": "CPO", "Chief Marketing Officer": "CMO",
    "Chief Data Officer": "CDO", "Chief Financial Officer": "CFO",
    "Chief People Officer": "CPO - People",
    "Chief Information Security Officer": "CISO",
    "Chief Information Officer": "CIO", "Senior": "Sr.",
    "Manager": "Mgr", "Engineering": "Eng", "Operations": "Ops",
    "Information": "Info", "Customer Success": "Cust Success",
    "Representative": "Rep",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--companies", type=int, default=500)
    parser.add_argument("--min-employees", type=int, default=100)
    parser.add_argument("--max-employees", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    return parser.parse_args()


def size_band(size: int) -> str:
    return "Small" if size < 130 else "Growth" if size < 180 else "Mid-market"


def active_departments(size: int, industry: str) -> list[str]:
    departments = ["Engineering", "Sales", "Customer Success", "Operations", "Finance", "People"]
    if size >= 115 or industry in {"B2B SaaS", "FinTech", "Cybersecurity", "EdTech"}:
        departments += ["Product", "Marketing"]
    if size >= 135 or industry in {"FinTech", "Cybersecurity", "E-commerce"}:
        departments.append("Data & Analytics")
    if size >= 155 or industry in {"FinTech", "Cybersecurity", "HealthTech"}:
        departments.append("Security")
    if size >= 170 or industry in {"Logistics", "Telecommunications"}:
        departments.append("IT")
    if size >= 190 or industry in {"FinTech", "HealthTech", "Clean Energy"}:
        departments.append("Legal")
    return list(dict.fromkeys(departments))


def allocate_department_counts(total: int, departments: list[str], industry: str) -> dict[str, int]:
    minimum = 3
    counts = {department: minimum for department in departments}
    remaining = total - minimum * len(departments)
    weights = {
        department: DEPARTMENT_WEIGHTS[department]
        * INDUSTRY_ADJUSTMENTS.get(industry, {}).get(department, 1.0)
        for department in departments
    }
    total_weight = sum(weights.values())
    raw = {department: remaining * weights[department] / total_weight for department in departments}
    for department in departments:
        counts[department] += int(raw[department])
    remainder = total - sum(counts.values())
    order = sorted(departments, key=lambda d: raw[d] - int(raw[d]), reverse=True)
    for department in order[:remainder]:
        counts[department] += 1
    return counts


def unique_person_name(rng: random.Random, used: set[str]) -> str:
    while True:
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        name = f"{first} {last}"
        if name not in used:
            used.add(name)
            return name
        name = f"{first} {chr(ord('A') + rng.randrange(26))}. {last}"
        if name not in used:
            used.add(name)
            return name


def leader_title(department: str, size: int, rng: random.Random) -> tuple[str, str]:
    titles = LEADER_TITLES[department]
    if size >= 190 and rng.random() < 0.5:
        return titles[0], "C-Suite"
    return (titles[1], "VP") if size >= 135 or rng.random() < 0.55 else (titles[2], "VP")


def ic_title(department: str, rng: random.Random) -> tuple[str, str]:
    base = rng.choice(IC_TITLES[department])
    roll = rng.random()
    if roll < 0.13:
        return f"Junior {base}", "Junior"
    if roll < 0.42:
        return base, "Individual Contributor"
    if roll < 0.77:
        return f"Senior {base}", "Senior"
    if roll < 0.91:
        return f"Lead {base}", "Lead"
    return f"Principal {base}", "Lead"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "company"


def messify_title(title: str, department: str, location: str, rng: random.Random) -> tuple[str, list[str]]:
    if rng.random() < 0.015:
        return "", ["missing_title"]
    result = title
    noise: list[str] = []
    if rng.random() < 0.37:
        for original, replacement in ABBREVIATIONS.items():
            if original in result and rng.random() < 0.72:
                result = result.replace(original, replacement)
                noise.append("abbreviation")
    if rng.random() < 0.18 and " of " in result:
        result = result.replace(" of ", " ")
        noise.append("removed_connector")
    if rng.random() < 0.13:
        result = result.replace(" ", "  ", 1)
        noise.append("spacing")
    if rng.random() < 0.11 and " " in result:
        first, rest = result.split(" ", 1)
        result = f"{first}, {rest}"
        noise.append("punctuation")
    if department in {"Sales", "Marketing", "Customer Success"} and rng.random() < 0.18:
        result = f"{result} - {location.split(',')[0]}"
        noise.append("regional_suffix")
    if rng.random() < 0.055:
        typo_map = {
            "Engineering": "Enginering", "Analytics": "Analtyics",
            "Manager": "Manger", "Security": "Securty",
        }
        for original, replacement in typo_map.items():
            if original in result:
                result = result.replace(original, replacement)
                noise.append("typo")
                break
    if rng.random() < 0.055:
        result = result.upper() if rng.random() < 0.45 else result.lower()
        noise.append("case")
    return result, sorted(set(noise)) or ["clean"]


def messy_department(department: str, all_departments: list[str], rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.14:
        return ""
    if roll < 0.19:
        return rng.choice(["N/A", "Unknown", "-"])
    if roll < 0.23:
        return rng.choice([value for value in all_departments if value != department])
    if roll < 0.55:
        return rng.choice(DEPARTMENT_ALIASES[department])
    return department


def messy_team(team: str, available_teams: list[str], rng: random.Random) -> str:
    """Return a realistically incomplete team label without leaking hierarchy."""
    roll = rng.random()
    if roll < 0.22:
        return ""
    if roll < 0.26:
        return rng.choice(["N/A", "Unknown", "-"])
    if roll < 0.29 and len(available_teams) > 1:
        alternatives = [value for value in available_teams if value != team]
        return rng.choice(alternatives)
    if roll < 0.35:
        return team.upper() if rng.random() < 0.5 else team.lower()
    if roll < 0.40 and " " in team:
        return team.replace(" ", "  ", 1)
    return team


def employee_record(
    employee_id: str, company_id: str, full_name: str, title: str,
    department: str, team: str, level: str, manager_id: str, location: str,
) -> dict[str, str]:
    return {
        "employee_id": employee_id, "company_id": company_id,
        "full_name": full_name, "canonical_title": title,
        "canonical_department": department, "canonical_level": level,
        "canonical_team": team, "manager_employee_id": manager_id, "location": location,
    }


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.companies < 1:
        raise SystemExit("--companies must be positive")
    if args.min_employees < 10 or args.max_employees < args.min_employees:
        raise SystemExit("employee bounds are invalid")

    rng = random.Random(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    company_names = [f"{left} {right}" for left in COMPANY_LEFT for right in COMPANY_RIGHT]
    if args.companies > len(company_names):
        raise SystemExit(f"--companies cannot exceed {len(company_names)} with the current name vocabulary")
    rng.shuffle(company_names)
    companies: list[dict[str, object]] = []
    truth: list[dict[str, object]] = []
    messy: list[dict[str, object]] = []
    employee_counter = 0

    def next_employee_id() -> str:
        nonlocal employee_counter
        employee_counter += 1
        return f"emp_{employee_counter:07d}"

    for company_index in range(1, args.companies + 1):
        company_id = f"cmp_{company_index:04d}"
        industry = rng.choice(INDUSTRIES)
        target_size = rng.randint(args.min_employees, args.max_employees)
        headquarters = rng.choice(LOCATIONS)
        name = company_names[company_index - 1]
        used_names: set[str] = set()
        company_employees: list[dict[str, str]] = []

        ceo_id = next_employee_id()
        company_employees.append(employee_record(
            ceo_id, company_id, unique_person_name(rng, used_names),
            "Chief Executive Officer", "Executive", "Executive", "CEO", "", headquarters,
        ))
        departments = active_departments(target_size, industry)
        allocations = allocate_department_counts(target_size - 1, departments, industry)

        for department, department_count in allocations.items():
            leader_id = next_employee_id()
            title, level = leader_title(department, target_size, rng)
            leader_team = department
            leader = employee_record(
                leader_id, company_id, unique_person_name(rng, used_names), title,
                department, leader_team, level, ceo_id,
                rng.choice(LOCATIONS) if rng.random() < 0.28 else headquarters,
            )
            company_employees.append(leader)
            remaining = department_count - 1
            director_count = min(4, max(0, remaining // 32))
            manager_count = min(14, max(0 if remaining < 5 else 1, round((remaining - director_count) / 8)))
            if director_count and manager_count < director_count:
                manager_count = director_count

            directors: list[str] = []
            director_teams: dict[str, str] = {}
            for director_index in range(director_count):
                director_id = next_employee_id()
                director_team = f"{department} / {DEPARTMENT_TEAMS[department][director_index]}"
                director_title = DIRECTOR_TITLES[department][
                    1 if director_index == 0 and rng.random() < 0.35 else 0
                ]
                company_employees.append(employee_record(
                    director_id, company_id, unique_person_name(rng, used_names),
                    director_title, department, director_team,
                    "Director", leader_id, leader["location"],
                ))
                directors.append(director_id)
                director_teams[director_id] = director_team

            managers: list[str] = []
            for manager_index in range(manager_count):
                manager_id = next_employee_id()
                parent_id = directors[manager_index % len(directors)] if directors else leader_id
                parent_team = director_teams.get(parent_id, leader_team)
                team_names = [
                    value for value in DEPARTMENT_TEAMS[department]
                    if value != parent_team.split(" / ")[-1]
                ]
                team_base = team_names[manager_index % len(team_names)]
                team_cycle = manager_index // len(team_names)
                if team_cycle:
                    team_base = f"{team_base} {team_cycle + 1}"
                manager_team = f"{parent_team} / {team_base}"
                company_employees.append(employee_record(
                    manager_id, company_id, unique_person_name(rng, used_names),
                    rng.choice(MANAGER_TITLES[department]), department, manager_team,
                    "Manager", parent_id,
                    rng.choice(LOCATIONS) if rng.random() < 0.2 else leader["location"],
                ))
                managers.append(manager_id)

            parents = managers or directors or [leader_id]
            parent_locations = {row["employee_id"]: row["location"] for row in company_employees}
            parent_teams = {row["employee_id"]: row["canonical_team"] for row in company_employees}
            for ic_index in range(remaining - director_count - manager_count):
                employee_id = next_employee_id()
                job_title, ic_level = ic_title(department, rng)
                parent_id = parents[ic_index % len(parents)]
                company_employees.append(employee_record(
                    employee_id, company_id, unique_person_name(rng, used_names),
                    job_title, department, parent_teams[parent_id], ic_level, parent_id,
                    rng.choice(LOCATIONS) if rng.random() < 0.18 else parent_locations[parent_id],
                ))

        actual_size = len(company_employees)
        companies.append({
            "company_id": company_id, "company_name": name, "industry": industry,
            "size_band": size_band(actual_size), "employee_count": actual_size,
            "headquarters": headquarters,
        })
        report_counts = Counter(
            row["manager_employee_id"] for row in company_employees if row["manager_employee_id"]
        )
        company_slug = slug(name)
        available_teams = sorted({row["canonical_team"] for row in company_employees})
        for row in company_employees:
            noisy_title, noise_profile = messify_title(
                row["canonical_title"], row["canonical_department"], row["location"], rng
            )
            row["is_people_manager"] = "1" if report_counts[row["employee_id"]] else "0"
            row["noise_profile"] = "|".join(noise_profile)
            truth.append({key: value for key, value in row.items() if key != "location"})
            department_value = (
                "Executive" if row["canonical_department"] == "Executive"
                else messy_department(row["canonical_department"], departments, rng)
            )
            location_value = "" if rng.random() < 0.075 else row["location"]
            email_local = re.sub(r"[^a-z0-9]+", ".", row["full_name"].lower()).strip(".")
            messy.append({
                "employee_id": row["employee_id"], "company_id": company_id,
                "full_name": row["full_name"], "job_title": noisy_title,
                "department": department_value,
                "team": messy_team(row["canonical_team"], available_teams, rng),
                "location": location_value,
                "work_email": f"{email_local}.{row['employee_id'].split('_')[-1]}@{company_slug}.example",
            })

    edges = [
        {"company_id": row["company_id"], "employee_id": row["employee_id"],
         "manager_employee_id": row["manager_employee_id"]}
        for row in truth if row["manager_employee_id"]
    ]
    write_csv(args.output_dir / "companies.csv", companies,
              ["company_id", "company_name", "industry", "size_band", "employee_count", "headquarters"])
    write_csv(args.output_dir / "employees_messy.csv", messy,
              ["employee_id", "company_id", "full_name", "job_title", "department", "team", "location", "work_email"])
    write_csv(args.output_dir / "employees_ground_truth.csv", truth,
              ["employee_id", "company_id", "full_name", "canonical_title",
               "canonical_department", "canonical_team", "canonical_level", "manager_employee_id",
               "is_people_manager", "noise_profile"])
    write_csv(args.output_dir / "reporting_edges.csv", edges,
              ["company_id", "employee_id", "manager_employee_id"])

    industry_counts = Counter(row["industry"] for row in companies)
    noise_counts: Counter[str] = Counter()
    for row in truth:
        noise_counts.update(str(row["noise_profile"]).split("|"))
    summary = {
        "seed": args.seed,
        "companies": len(companies),
        "employees": len(truth),
        "reporting_edges": len(edges),
        "minimum_company_size": min(int(row["employee_count"]) for row in companies),
        "maximum_company_size": max(int(row["employee_count"]) for row in companies),
        "industries": dict(sorted(industry_counts.items())),
        "noise_profiles": dict(sorted(noise_counts.items())),
        "missing_job_title_rows": sum(1 for row in messy if not row["job_title"]),
        "missing_or_sentinel_department_rows": sum(
            1 for row in messy if row["department"] in {"", "N/A", "Unknown", "-"}
        ),
        "missing_location_rows": sum(1 for row in messy if not row["location"]),
        "missing_or_sentinel_team_rows": sum(
            1 for row in messy if row["team"] in {"", "N/A", "Unknown", "-"}
        ),
    }
    (args.output_dir / "dataset_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

