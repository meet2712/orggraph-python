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

EXECUTIVE_PORTFOLIOS = {
    "Technology": {
        "title": "Chief Technology Officer",
        "departments": ["Engineering", "Product", "Data & Analytics", "Security", "IT"],
    },
    "Revenue": {
        "title": "Chief Revenue Officer",
        "departments": ["Sales", "Marketing", "Customer Success"],
    },
    "Operations": {
        "title": "Chief Operating Officer",
        "departments": ["Operations"],
    },
    "Finance & Risk": {
        "title": "Chief Financial Officer",
        "departments": ["Finance", "Legal"],
    },
    "People": {
        "title": "Chief People Officer",
        "departments": ["People"],
    },
}

PORTFOLIO_PRINCIPAL_ROLES = {
    "Technology": ("Principal Software Architect", "Engineering"),
    "Revenue": ("Principal Sales Strategist", "Sales"),
    "Operations": ("Principal Operations Analyst", "Operations"),
    "Finance & Risk": ("Principal Financial Analyst", "Finance"),
    "People": ("Principal People Partner", "People"),
}

DEPARTMENT_HEAD_TITLES = {
    "Engineering": ["VP of Engineering", "Head of Engineering"],
    "Sales": ["VP of Sales", "Head of Sales"],
    "Customer Success": ["VP of Customer Success", "Head of Customer Success"],
    "Operations": ["VP of Operations", "Head of Operations"],
    "Product": ["VP of Product", "Head of Product"],
    "Marketing": ["VP of Marketing", "Head of Marketing"],
    "Data & Analytics": ["VP of Data", "Head of Data & Analytics"],
    "Finance": ["VP of Finance", "Head of Finance"],
    "People": ["VP of People", "Head of People"],
    "Security": ["VP of Security", "Head of Security"],
    "IT": ["VP of IT", "Head of IT"],
    "Legal": ["VP of Legal", "Head of Legal"],
}

# Teams are grouped into real functional areas. Directors own a function,
# managers own a team, and IC seniority remains a career level rather than an
# automatic people-management relationship.
TEAM_CLUSTERS = {
    "Engineering": {
        "Platform": "Product Engineering", "Core Services": "Product Engineering",
        "Applications": "Product Engineering", "Mobile": "Product Engineering",
        "Web": "Product Engineering", "Quality": "Quality & Reliability",
        "Infrastructure": "Quality & Reliability",
        "Developer Experience": "Quality & Reliability",
    },
    "Sales": {
        "Enterprise": "Segment Sales", "Mid-Market": "Segment Sales",
        "SMB": "Segment Sales", "Partnerships": "Partnerships",
        "APAC": "Regional Sales", "EMEA": "Regional Sales",
        "Americas": "Regional Sales",
    },
    "Customer Success": {
        "Enterprise Success": "Customer Success", "Commercial Success": "Customer Success",
        "Onboarding": "Customer Delivery", "Support": "Customer Support",
        "Implementations": "Customer Delivery",
    },
    "Operations": {
        "Business Operations": "Business Operations", "Revenue Operations": "Business Operations",
        "Programs": "Program Delivery", "Delivery": "Program Delivery",
        "Strategy": "Strategy",
    },
    "Product": {
        "Core Product": "Product Management", "Growth Product": "Product Management",
        "Platform Product": "Product Management", "Design": "Design & Research",
        "Research": "Design & Research",
    },
    "Marketing": {
        "Growth": "Growth Marketing", "Demand Generation": "Growth Marketing",
        "Content": "Brand & Content", "Brand": "Brand & Content",
        "Product Marketing": "Product Marketing",
    },
    "Data & Analytics": {
        "Data Platform": "Data Engineering", "ML Platform": "Data Engineering",
        "Analytics": "Analytics & BI", "Business Intelligence": "Analytics & BI",
        "Data Science": "Data Science",
    },
    "Finance": {
        "Financial Planning": "Planning & Analysis", "Commercial Finance": "Planning & Analysis",
        "Accounting": "Controllership", "Payroll": "Controllership",
    },
    "People": {
        "People Operations": "People Operations", "Business Partners": "People Operations",
        "Talent": "Talent", "Learning": "Talent",
    },
    "Security": {
        "Security Engineering": "Security Engineering", "Identity": "Security Engineering",
        "GRC": "Risk & Compliance", "Security Operations": "Security Operations",
    },
    "IT": {
        "Infrastructure": "Infrastructure & Cloud", "Cloud Operations": "Infrastructure & Cloud",
        "Service Desk": "IT Services", "Enterprise Applications": "IT Services",
    },
    "Legal": {
        "Commercial Legal": "Commercial Legal", "Legal Operations": "Legal Operations",
        "Compliance": "Risk & Compliance", "Privacy": "Risk & Compliance",
    },
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

SENIOR_MANAGER_TITLES = {
    "Engineering": "Senior Engineering Manager", "Sales": "Senior Sales Manager",
    "Customer Success": "Senior Customer Success Manager", "Operations": "Senior Operations Manager",
    "Product": "Senior Product Operations Manager", "Marketing": "Senior Marketing Manager",
    "Data & Analytics": "Senior Data & Analytics Manager", "Finance": "Senior Finance Manager",
    "People": "Senior People Operations Manager", "Security": "Senior Security Manager",
    "IT": "Senior IT Manager", "Legal": "Senior Legal Operations Manager",
}

# Keep a manager's title consistent with the team they own.  The earlier
# generator selected a random department-level manager title, which could put
# a QA Manager over a platform team and QA Engineers under a software manager.
TEAM_MANAGER_TITLES = {
    "Engineering": {
        "Quality": ["QA Manager"],
        "Infrastructure": ["Engineering Manager", "Software Development Manager"],
        "Developer Experience": ["Engineering Manager"],
        "Platform": ["Engineering Manager", "Software Development Manager"],
        "Core Services": ["Software Development Manager", "Engineering Manager"],
        "Applications": ["Software Development Manager", "Engineering Manager"],
        "Mobile": ["Software Development Manager"],
        "Web": ["Software Development Manager", "Engineering Manager"],
    },
    "Sales": {
        "Enterprise": ["Enterprise Sales Manager"],
        "Mid-Market": ["Mid-Market Sales Manager"],
        "SMB": ["SMB Sales Manager"],
        "Partnerships": ["Business Development Manager"],
        "APAC": ["Regional Sales Manager"],
        "EMEA": ["Regional Sales Manager"],
        "Americas": ["Regional Sales Manager"],
    },
    "Customer Success": {
        "Enterprise Success": ["Enterprise Customer Success Manager"],
        "Commercial Success": ["Commercial Customer Success Manager"],
        "Support": ["Support Manager"],
        "Onboarding": ["Customer Success Team Manager"],
        "Implementations": ["Implementation Manager"],
    },
    "Operations": {
        "Business Operations": ["Business Operations Manager"],
        "Revenue Operations": ["Business Operations Manager"],
        "Programs": ["Program Lead"],
        "Delivery": ["Operations Manager"],
        "Strategy": ["Business Operations Manager"],
    },
    "Product": {
        "Core Product": ["Group Product Manager"],
        "Growth Product": ["Group Product Manager"],
        "Platform Product": ["Group Product Manager"],
        "Design": ["Product Design Manager"],
        "Research": ["User Research Manager"],
    },
    "Marketing": {
        "Growth": ["Growth Marketing Manager"],
        "Demand Generation": ["Demand Generation Manager"],
        "Content": ["Content Marketing Manager"],
        "Brand": ["Brand Marketing Manager"],
        "Product Marketing": ["Product Marketing Manager"],
    },
    "Data & Analytics": {
        "Data Platform": ["Data Engineering Manager"],
        "Analytics": ["Analytics Manager"],
        "Data Science": ["Data Science Manager"],
        "ML Platform": ["Data Science Manager", "Data Engineering Manager"],
        "Business Intelligence": ["Analytics Manager"],
    },
    "Finance": {
        "Financial Planning": ["FP&A Manager"],
        "Accounting": ["Accounting Manager"],
        "Payroll": ["Accounting Manager"],
        "Commercial Finance": ["Commercial Finance Manager"],
    },
    "People": {
        "People Operations": ["People Operations Manager"],
        "Talent": ["Talent Acquisition Manager"],
        "Business Partners": ["HR Business Partner Manager"],
        "Learning": ["Learning and Development Manager"],
    },
    "Security": {
        "Security Engineering": ["Security Engineering Manager"],
        "GRC": ["GRC Manager"],
        "Security Operations": ["Security Operations Manager"],
        "Identity": ["Security Engineering Manager"],
    },
    "IT": {
        "Infrastructure": ["Infrastructure Manager"],
        "Service Desk": ["Service Desk Manager"],
        "Enterprise Applications": ["IT Manager"],
        "Cloud Operations": ["Infrastructure Manager"],
    },
    "Legal": {
        "Commercial Legal": ["Commercial Legal Manager"],
        "Legal Operations": ["Legal Operations Manager"],
        "Compliance": ["Compliance Manager"],
        "Privacy": ["Privacy Manager"],
    },
}

TEAM_LEAD_TITLES = {
    "Engineering": {
        "Quality": "QA Team Lead", "Infrastructure": "Infrastructure Team Lead",
        "Developer Experience": "Developer Experience Team Lead",
        "Platform": "Platform Engineering Team Lead", "Core Services": "Core Services Team Lead",
        "Applications": "Application Engineering Team Lead", "Mobile": "Mobile Engineering Team Lead",
        "Web": "Web Engineering Team Lead",
    },
    "Sales": {"default": "Sales Team Lead"},
    "Customer Success": {"Support": "Support Team Lead", "default": "Customer Success Team Lead"},
    "Operations": {"default": "Operations Team Lead"},
    "Product": {"Design": "Design Team Lead", "Research": "Research Team Lead", "default": "Product Team Lead"},
    "Marketing": {"default": "Marketing Team Lead"},
    "Data & Analytics": {"default": "Data & Analytics Team Lead"},
    "Finance": {"default": "Finance Team Lead"},
    "People": {"default": "People Operations Team Lead"},
    "Security": {"default": "Security Team Lead"},
    "IT": {"Service Desk": "Service Desk Supervisor", "default": "IT Team Lead"},
    "Legal": {"default": "Legal Operations Team Lead"},
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

TEAM_IC_TITLES = {
    "Engineering": {
        "Quality": ["QA Engineer"],
        "Infrastructure": ["DevOps Engineer", "Software Engineer"],
        "Developer Experience": ["DevOps Engineer", "Software Engineer"],
        "Platform": ["Backend Engineer", "Software Engineer", "DevOps Engineer"],
        "Core Services": ["Backend Engineer", "Software Engineer"],
        "Applications": ["Software Engineer", "Backend Engineer", "Frontend Developer"],
        "Mobile": ["Software Engineer", "Frontend Developer"],
        "Web": ["Frontend Developer", "Software Engineer"],
    },
    "Sales": {
        "Enterprise": ["Account Executive", "Sales Development Representative"],
        "Mid-Market": ["Account Executive", "Sales Development Representative"],
        "Partnerships": ["Business Development Representative", "Account Executive"],
        "SMB": ["Sales Development Representative", "Account Executive"],
        "APAC": ["Account Executive", "Sales Development Representative"],
        "EMEA": ["Account Executive", "Sales Development Representative"],
        "Americas": ["Account Executive", "Sales Development Representative"],
    },
    "Customer Success": {
        "Enterprise Success": ["Customer Success Manager"],
        "Commercial Success": ["Customer Success Manager"],
        "Support": ["Support Specialist"],
        "Onboarding": ["Onboarding Specialist"],
        "Implementations": ["Implementation Consultant"],
    },
    "Operations": {
        "Business Operations": ["Business Operations Specialist", "Operations Analyst"],
        "Revenue Operations": ["Business Operations Specialist", "Operations Analyst"],
        "Programs": ["Program Coordinator"],
        "Delivery": ["Project Coordinator", "Operations Analyst"],
        "Strategy": ["Operations Analyst", "Business Operations Specialist"],
    },
    "Product": {
        "Core Product": ["Product Manager", "Product Analyst"],
        "Growth Product": ["Product Manager", "Product Analyst"],
        "Platform Product": ["Product Manager", "Product Analyst"],
        "Design": ["Product Designer"],
        "Research": ["UX Researcher"],
    },
    "Marketing": {
        "Growth": ["Growth Marketer"],
        "Demand Generation": ["Demand Generation Specialist"],
        "Content": ["Content Strategist"],
        "Brand": ["Content Strategist", "Marketing Analyst"],
        "Product Marketing": ["Marketing Analyst", "Content Strategist"],
    },
    "Data & Analytics": {
        "Data Platform": ["Data Engineer"],
        "Analytics": ["Data Analyst", "BI Analyst"],
        "Data Science": ["Data Scientist"],
        "ML Platform": ["Machine Learning Engineer", "Data Engineer"],
        "Business Intelligence": ["BI Analyst", "Data Analyst"],
    },
    "Finance": {
        "Financial Planning": ["FP&A Analyst", "Financial Analyst"],
        "Accounting": ["Accountant"],
        "Payroll": ["Payroll Specialist"],
        "Commercial Finance": ["Financial Analyst", "FP&A Analyst"],
    },
    "People": {
        "People Operations": ["People Partner", "HR Coordinator"],
        "Talent": ["Recruiter", "Talent Specialist"],
        "Business Partners": ["People Partner"],
        "Learning": ["Talent Specialist", "HR Coordinator"],
    },
    "Security": {
        "Security Engineering": ["Security Engineer"],
        "GRC": ["GRC Analyst"],
        "Security Operations": ["Security Analyst", "Incident Response Specialist"],
        "Identity": ["Security Engineer"],
    },
    "IT": {
        "Infrastructure": ["Systems Administrator", "Network Engineer"],
        "Service Desk": ["IT Support Specialist"],
        "Enterprise Applications": ["Systems Administrator", "IT Support Specialist"],
        "Cloud Operations": ["Cloud Administrator"],
    },
    "Legal": {
        "Commercial Legal": ["Legal Counsel", "Contracts Specialist"],
        "Compliance": ["Compliance Analyst"],
        "Legal Operations": ["Paralegal", "Contracts Specialist"],
        "Privacy": ["Legal Counsel", "Compliance Analyst"],
    },
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


def selected_executive_portfolios(
    company_id: str, size: int, industry: str, seed: int,
) -> set[str]:
    """Choose a realistic, reproducible subset of non-CEO executives.

    Headcount determines how many specialist executives are affordable while
    industry changes which portfolios are most likely. The dedicated RNG keeps
    this decision independent from the legacy employee/noise generation stream.
    """
    band = size_band(size)
    count_ranges = {
        "Small": (1, 2),
        "Growth": (2, 4),
        "Mid-market": (3, 5),
    }
    minimum, maximum = count_ranges[band]
    rng = random.Random(f"{seed}:{company_id}:executive-portfolios")
    count = rng.randint(minimum, maximum)

    weights = {
        "Technology": 3.0,
        "Revenue": 2.5,
        "Operations": 1.7,
        "Finance & Risk": 1.4,
        "People": 0.8,
    }
    if industry in {"B2B SaaS", "FinTech", "Cybersecurity", "HealthTech", "EdTech"}:
        weights["Technology"] += 2.2
    if industry in {"B2B SaaS", "E-commerce", "Professional Services", "EdTech"}:
        weights["Revenue"] += 1.7
    if industry in {"E-commerce", "Logistics", "Clean Energy", "Telecommunications"}:
        weights["Operations"] += 2.4
    if industry in {"FinTech", "HealthTech", "Clean Energy"}:
        weights["Finance & Risk"] += 2.0
    if band == "Mid-market":
        weights["Finance & Risk"] += 1.4
        weights["People"] += 1.5
    elif band == "Growth":
        weights["People"] += 0.5

    remaining = list(EXECUTIVE_PORTFOLIOS)
    selected: set[str] = set()
    while len(selected) < count:
        chosen = rng.choices(
            remaining, weights=[weights[portfolio] for portfolio in remaining], k=1
        )[0]
        selected.add(chosen)
        remaining.remove(chosen)
    return selected


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
    # Keep allocation identical across Python versions with different sum algorithms.
    total_weight = 0.0
    for weight in weights.values():
        total_weight += weight
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


def department_head_title(department: str, department_size: int, rng: random.Random) -> str:
    """Choose a VP or Head title; C-suite roles are created separately."""
    titles = DEPARTMENT_HEAD_TITLES[department]
    return titles[0] if department_size >= 18 or rng.random() < 0.55 else titles[1]


def plain_team_name(team: str) -> str:
    """Return the reusable team name without a numeric overflow suffix."""
    return re.sub(r" \d+$", "", team.rsplit(" / ", 1)[-1])


def manager_title(department: str, team: str, rng: random.Random) -> str:
    choices = TEAM_MANAGER_TITLES.get(department, {}).get(
        plain_team_name(team), MANAGER_TITLES[department]
    )
    return rng.choice(choices)


def team_cluster(department: str, team: str) -> str:
    leaf = plain_team_name(team)
    return TEAM_CLUSTERS[department].get(leaf, department)


def director_title(department: str, cluster: str) -> str:
    if cluster == department:
        return f"Director of {department}"
    return f"Director of {cluster}"


def team_lead_title(department: str, team: str) -> str:
    titles = TEAM_LEAD_TITLES[department]
    leaf = plain_team_name(team)
    return titles[leaf] if leaf in titles else titles["default"]


def ic_title(
    department: str, team: str, level: str, rng: random.Random,
) -> tuple[str, str]:
    """Create a title whose discipline matches the employee's actual team."""
    choices = TEAM_IC_TITLES.get(department, {}).get(
        plain_team_name(team), IC_TITLES[department]
    )
    base = rng.choice(choices)
    if level == "Junior":
        return f"Junior {base}", level
    if level == "Senior":
        return f"Senior {base}", level
    if level == "Staff":
        return f"Staff {base}", level
    if level == "Principal":
        return f"Principal {base}", level
    return base, "Individual Contributor"


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
    if roll < 0.10:
        return ""
    if roll < 0.12:
        return rng.choice(["N/A", "Unknown", "-"])
    if roll < 0.14 and len(available_teams) > 1:
        alternatives = [value for value in available_teams if value != team]
        return rng.choice(alternatives)
    if roll < 0.20:
        return team.upper() if rng.random() < 0.5 else team.lower()
    if roll < 0.24 and " " in team:
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
            "Chief Executive Officer", "Executive", "Company", "CEO", "", headquarters,
        ))
        departments = active_departments(target_size, industry)
        active_portfolios = {
            portfolio: spec for portfolio, spec in EXECUTIVE_PORTFOLIOS.items()
            if any(department in departments for department in spec["departments"])
        }
        allocations = allocate_department_counts(
            target_size - 1 - len(active_portfolios), departments, industry
        )

        # The CEO owns a small executive team. Department VPs/Heads report to
        # the appropriate executive instead of every function reporting to the
        # CEO directly.
        portfolio_ids: dict[str, str] = {}
        portfolio_locations: dict[str, str] = {}
        department_portfolio: dict[str, str] = {}
        department_leader_ids: dict[str, str] = {}
        for portfolio, spec in active_portfolios.items():
            executive_id = next_employee_id()
            executive_location = (
                rng.choice(LOCATIONS) if rng.random() < 0.18 else headquarters
            )
            company_employees.append(employee_record(
                executive_id, company_id, unique_person_name(rng, used_names),
                str(spec["title"]), "Executive", f"Company / {portfolio}", "C-Suite", ceo_id,
                executive_location,
            ))
            portfolio_ids[portfolio] = executive_id
            portfolio_locations[portfolio] = executive_location
            for department in spec["departments"]:
                if department in departments:
                    department_portfolio[department] = portfolio

        for department, department_count in allocations.items():
            portfolio = department_portfolio[department]
            executive_id = portfolio_ids[portfolio]
            department_path = (
                f"Company / {department}" if portfolio == department
                else f"Company / {portfolio} / {department}"
            )
            leader_id = next_employee_id()
            leader_location = (
                rng.choice(LOCATIONS)
                if rng.random() < 0.22 else portfolio_locations[portfolio]
            )
            leader = employee_record(
                leader_id, company_id, unique_person_name(rng, used_names),
                department_head_title(department, department_count, rng),
                department, department_path, "VP", executive_id, leader_location,
            )
            company_employees.append(leader)
            department_leader_ids[department] = leader_id

            remaining = department_count - 1
            manager_count = max(1, min(14, round(remaining / 9)))
            team_specs: list[tuple[str, str, str]] = []
            team_names = DEPARTMENT_TEAMS[department]
            for manager_index in range(manager_count):
                base_team = team_names[manager_index % len(team_names)]
                cycle = manager_index // len(team_names)
                display_team = f"{base_team} {cycle + 1}" if cycle else base_team
                team_specs.append((display_team, base_team, team_cluster(department, base_team)))

            # Small departments can report managers directly to the VP/Head.
            # Larger departments add directors; very large functions separate
            # directors by functional cluster.
            distinct_clusters = list(dict.fromkeys(spec[2] for spec in team_specs))
            if department_count < 24:
                director_clusters: list[str] = []
            elif department_count < 45 or len(distinct_clusters) == 1:
                director_clusters = [department]
            else:
                director_clusters = distinct_clusters[:3]

            directors_by_cluster: dict[str, str] = {}
            director_teams: dict[str, str] = {}
            for cluster in director_clusters:
                director_id = next_employee_id()
                director_team = (
                    department_path if cluster == department
                    else f"{department_path} / {cluster}"
                )
                company_employees.append(employee_record(
                    director_id, company_id, unique_person_name(rng, used_names),
                    director_title(department, cluster), department, director_team,
                    "Director", leader_id, leader_location,
                ))
                directors_by_cluster[cluster] = director_id
                director_teams[director_id] = director_team

            # A senior-manager layer appears only when one leader would
            # otherwise have an unrealistically wide manager span.
            senior_managers_by_parent: dict[str, str] = {}
            if manager_count >= 5 and directors_by_cluster:
                for director_id in directors_by_cluster.values():
                    senior_manager_id = next_employee_id()
                    senior_team = director_teams[director_id]
                    company_employees.append(employee_record(
                        senior_manager_id, company_id, unique_person_name(rng, used_names),
                        SENIOR_MANAGER_TITLES[department], department, senior_team,
                        "Senior Manager", director_id, leader_location,
                    ))
                    senior_managers_by_parent[director_id] = senior_manager_id

            managers: list[str] = []
            manager_teams: dict[str, str] = {}
            manager_locations: dict[str, str] = {}
            for display_team, _base_team, cluster in team_specs:
                if department in directors_by_cluster:
                    director_id = directors_by_cluster[department]
                else:
                    director_id = directors_by_cluster.get(cluster, "")
                parent_id = senior_managers_by_parent.get(
                    director_id, director_id or leader_id
                )
                parent_team = (
                    director_teams.get(director_id, department_path)
                )
                manager_team = f"{parent_team} / {display_team}"
                manager_id = next_employee_id()
                manager_location = (
                    rng.choice(LOCATIONS) if rng.random() < 0.16 else leader_location
                )
                company_employees.append(employee_record(
                    manager_id, company_id, unique_person_name(rng, used_names),
                    manager_title(department, manager_team, rng), department,
                    manager_team, "Manager", parent_id, manager_location,
                ))
                managers.append(manager_id)
                manager_teams[manager_id] = manager_team
                manager_locations[manager_id] = manager_location

            overhead = (
                len(directors_by_cluster) + len(senior_managers_by_parent) + len(managers)
            )
            individual_count = remaining - overhead
            if individual_count < len(managers) * 2:
                raise AssertionError(f"insufficient IC capacity in {company_id} {department}")
            group_sizes = {manager_id: 0 for manager_id in managers}
            for ic_index in range(individual_count):
                group_sizes[managers[ic_index % len(managers)]] += 1

            for formal_manager_id in managers:
                group_size = group_sizes[formal_manager_id]
                team = manager_teams[formal_manager_id]
                manager_location = manager_locations[formal_manager_id]
                lead_id = ""
                member_slots = group_size
                if group_size >= 8:
                    lead_id = next_employee_id()
                    company_employees.append(employee_record(
                        lead_id, company_id, unique_person_name(rng, used_names),
                        team_lead_title(department, team), department, team,
                        "Team Lead", formal_manager_id, manager_location,
                    ))
                    member_slots -= 1

                # Senior, Staff and Principal are IC career levels. They do not
                # become managers merely because their title is more senior.
                level_pattern = [
                    "Senior", "Individual Contributor", "Junior",
                    "Individual Contributor", "Staff", "Senior",
                    "Individual Contributor", "Junior", "Principal",
                ]
                for member_index in range(member_slots):
                    member_level = level_pattern[member_index % len(level_pattern)]
                    if member_level == "Principal" and member_slots < 9:
                        member_level = "Individual Contributor"
                    job_title, _ = ic_title(department, team, member_level, rng)
                    # Explicit Team Leads may supervise junior/intermediate ICs;
                    # senior/staff/principal ICs continue to report to Manager.
                    manager_id = (
                        lead_id if lead_id and member_level in {"Junior", "Individual Contributor"}
                        else formal_manager_id
                    )
                    employee_id = next_employee_id()
                    company_employees.append(employee_record(
                        employee_id, company_id, unique_person_name(rng, used_names),
                        job_title, department, team, member_level, manager_id,
                        rng.choice(LOCATIONS) if rng.random() < 0.10 else manager_location,
                    ))

        actual_size = len(company_employees)
        # Preserve the original flat employee population and its global RNG
        # sequence, but do not force every company into the same five-person
        # C-suite. Portfolios without a dedicated executive roll their VP up
        # to the CEO and keep the preserved employee as a functional Principal.
        selected_portfolios = selected_executive_portfolios(
            company_id, actual_size, industry, args.seed
        )
        original_titles = {
            row["employee_id"]: row["canonical_title"] for row in company_employees
        }
        original_departments = {
            row["employee_id"]: row["canonical_department"] for row in company_employees
        }
        original_teams = {
            row["employee_id"]: row["canonical_team"] for row in company_employees
        }
        inactive_executives = {
            executive_id: portfolio
            for portfolio, executive_id in portfolio_ids.items()
            if portfolio not in selected_portfolios
        }
        for row in company_employees:
            if row["employee_id"] in inactive_executives:
                portfolio = inactive_executives[row["employee_id"]]
                principal_title, principal_department = PORTFOLIO_PRINCIPAL_ROLES[portfolio]
                row["canonical_title"] = principal_title
                row["canonical_department"] = principal_department
                row["canonical_level"] = "Principal"
                row["manager_employee_id"] = department_leader_ids[principal_department]
                leader = next(
                    employee for employee in company_employees
                    if employee["employee_id"] == row["manager_employee_id"]
                )
                row["canonical_team"] = leader["canonical_team"]
            elif (
                row["canonical_level"] == "VP"
                and row["manager_employee_id"] in inactive_executives
            ):
                row["manager_employee_id"] = ceo_id

        companies.append({
            "company_id": company_id, "company_name": name, "industry": industry,
            "size_band": size_band(actual_size), "employee_count": actual_size,
            "headquarters": headquarters,
        })
        report_counts = Counter(
            row["manager_employee_id"] for row in company_employees if row["manager_employee_id"]
        )
        company_slug = slug(name)
        available_teams = sorted(set(original_teams.values()))
        for row in company_employees:
            # Always consume the legacy title-noise RNG call so every untouched
            # raw row remains byte-for-byte reproducible from the old dataset.
            noisy_title, noise_profile = messify_title(
                original_titles[row["employee_id"]],
                original_departments[row["employee_id"]],
                row["location"], rng
            )
            if row["employee_id"] in inactive_executives:
                principal_rng = random.Random(
                    f"{args.seed}:{company_id}:{row['employee_id']}:principal-title"
                )
                noisy_title, noise_profile = messify_title(
                    row["canonical_title"], row["canonical_department"],
                    row["location"], principal_rng
                )
            row["is_people_manager"] = "1" if report_counts[row["employee_id"]] else "0"
            row["noise_profile"] = "|".join(noise_profile)
            truth.append({key: value for key, value in row.items() if key != "location"})
            original_department = original_departments[row["employee_id"]]
            department_value = (
                "Executive" if original_department == "Executive"
                else messy_department(original_department, departments, rng)
            )
            location_value = "" if rng.random() < 0.075 else row["location"]
            email_local = re.sub(r"[^a-z0-9]+", ".", row["full_name"].lower()).strip(".")
            messy.append({
                "employee_id": row["employee_id"], "company_id": company_id,
                "full_name": row["full_name"], "job_title": noisy_title,
                "department": department_value,
                "team": messy_team(original_teams[row["employee_id"]], available_teams, rng),
                "location": location_value,
                "work_email": f"{email_local}.{row['employee_id'].split('_')[-1]}@{company_slug}.example",
            })

    reporting_line_count = sum(bool(row["manager_employee_id"]) for row in truth)
    write_csv(args.output_dir / "companies.csv", companies,
              ["company_id", "company_name", "industry", "size_band", "employee_count", "headquarters"])
    write_csv(args.output_dir / "employees_messy.csv", messy,
              ["employee_id", "company_id", "full_name", "job_title", "department", "team", "location", "work_email"])
    write_csv(args.output_dir / "employees_ground_truth.csv", truth,
              ["employee_id", "company_id", "full_name", "canonical_title",
               "canonical_department", "canonical_team", "canonical_level", "manager_employee_id",
               "is_people_manager", "noise_profile"])
    industry_counts = Counter(row["industry"] for row in companies)
    c_suite_counts = Counter(
        Counter(
            row["company_id"] for row in truth if row["canonical_level"] == "C-Suite"
        ).values()
    )
    noise_counts: Counter[str] = Counter()
    for row in truth:
        noise_counts.update(str(row["noise_profile"]).split("|"))
    summary = {
        "seed": args.seed,
        "companies": len(companies),
        "employees": len(truth),
        "reporting_edges": reporting_line_count,
        "minimum_company_size": min(int(row["employee_count"]) for row in companies),
        "maximum_company_size": max(int(row["employee_count"]) for row in companies),
        "industries": dict(sorted(industry_counts.items())),
        "non_ceo_c_suite_distribution": {
            str(count): companies_at_count
            for count, companies_at_count in sorted(c_suite_counts.items())
        },
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

