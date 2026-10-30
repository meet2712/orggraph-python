#!/usr/bin/env python3
"""Turn messy employee records into cautious manager predictions.

The steps are: parse titles, shortlist managers, score each pair, check the
scores against validation data, and save only the links with enough evidence.
Ground-truth managers are used to train and evaluate, never as model features.
Whole companies stay together when splitting the data.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd


DEPARTMENTS = [
    "Executive",
    "Engineering",
    "Sales",
    "Customer Success",
    "Operations",
    "Product",
    "Marketing",
    "Data & Analytics",
    "Finance",
    "People",
    "Security",
    "IT",
    "Legal",
]

# Specific function words take precedence over generic words such as
# "engineer", "support", and "operations" in a compound title.
DEPARTMENT_TITLE_PRIORITY = [
    ("Executive", ["chief executive", "ceo"]),
    ("People", ["cpo people", "people", "human resources", "hr", "recruiter", "recruiting", "talent"]),
    ("Product", ["product", "ux", "designer", "researcher", "cpo"]),
    ("Operations", ["revenue operations", "revenue ops", "sales operations", "sales ops"]),
    ("Data & Analytics", ["data", "analytics", "analtyics", "bi analyst", "machine learning", "ml", "ai", "cdo"]),
    ("Security", ["security", "securty", "infosec", "cyber", "grc", "incident response", "ciso"]),
    ("IT", ["information technology", "info tech", "it", "infrastructure", "systems administrator", "network engineer", "cloud administrator", "service desk", "chief information officer", "cio"]),
    ("Legal", ["legal", "counsel", "paralegal", "compliance", "contracts"]),
    ("Customer Success", ["customer success", "cust success", "client success", "enterprise success", "commercial success", "onboarding", "implementation", "chief customer officer", "cco"]),
    ("Sales", ["sales", "revenue", "partnership", "partnerships", "account executive", "account manager", "account mgr", "account manger", "business development", "commercial", "sdr", "bdr", "gtm", "cro"]),
    ("Finance", ["finance", "financial", "fp&a", "accountant", "accounting", "payroll", "cfo"]),
    ("Marketing", ["marketing", "mktg", "growth", "demand gen", "demand generation", "content", "cmo"]),
    ("Operations", ["operations", "ops", "bizops", "business ops", "program", "project coordinator", "chief operating officer", "coo"]),
    ("Engineering", ["product engineering", "engineering", "enginering", "engineer", "developer", "software", "devops", "qa", "technology", "cto", "eng", "r&d"]),
    ("Customer Success", ["support", "cx"]),
]

DEPARTMENT_ALIASES = {
    "eng": "Engineering", "tech": "Engineering", "r and d": "Engineering", "software": "Engineering",
    "revenue": "Sales", "commercial": "Sales", "gtm": "Sales",
    "cs": "Customer Success", "cust success": "Customer Success", "client success": "Customer Success", "cx": "Customer Success",
    "ops": "Operations", "bizops": "Operations", "business ops": "Operations",
    "prod": "Product", "product and design": "Product",
    "mktg": "Marketing", "growth": "Marketing", "demand gen": "Marketing",
    "data": "Data & Analytics", "analytics": "Data & Analytics", "bi": "Data & Analytics", "data/ai": "Data & Analytics",
    "fin": "Finance", "accounting": "Finance",
    "hr": "People", "people ops": "People", "people and culture": "People",
    "infosec": "Security", "cyber": "Security", "grc": "Security",
    "info tech": "IT", "infrastructure": "IT",
    "compliance": "Legal", "risk and legal": "Legal",
}

AMBIGUOUS_IC_MANAGER_TITLES = {
    "product manager",
    "customer success manager",
    "account manager",
}

REGIONAL_TITLE_SUFFIXES = [
    "sydney", "melbourne", "brisbane", "perth", "bengaluru",
    "singapore", "london", "new york", "san francisco", "toronto",
]

FEATURE_NAMES = [
    "same_department",
    "rank_gap_one",
    "rank_gap_two",
    "rank_gap_large",
    "same_location",
    "candidate_is_leader",
    "candidate_is_executive",
    "report_title_missing",
    "report_department_missing",
    "report_department_confidence",
    "candidate_department_confidence",
    "raw_department_match",
    "candidate_rank_scaled",
    "report_rank_scaled",
    "same_team",
    "report_team_missing",
    "parent_team_match",
    "same_role_family",
    "candidate_is_team_lead",
]


@dataclass(frozen=True)
class ParsedEmployee:
    employee_id: str
    company_id: str
    full_name: str
    job_title: str
    raw_department: str
    raw_team: str
    team: str
    location: str
    department: str
    department_confidence: float
    role_family: str
    rank: int
    rank_label: str
    people_manager_cue: bool
    title_missing: bool
    department_missing: bool
    team_missing: bool
    true_manager_id: str
    noise_profile: str


@dataclass(frozen=True)
class Candidate:
    manager_id: str
    features: tuple[float, ...]
    heuristic_score: float
    structural_match: bool = False


@dataclass
class LogisticModel:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float

    def logits(self, matrix: np.ndarray) -> np.ndarray:
        normalized = (matrix - self.mean) / self.scale
        return normalized @ self.weights + self.bias


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("public/data"))
    parser.add_argument("--model-dir", type=Path, default=Path("model"))
    parser.add_argument("--seed", type=int, default=20261029)
    return parser.parse_args()


def normalize_text(value: str) -> str:
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#/&]+", " ", text)
    return f" {' '.join(text.split())} "


def infer_role_family(title: str) -> str:
    """Reduce a title to the discipline used for team-lead matching."""
    text = normalize_text(title)
    families = [
        ("Quality Assurance", [" qa ", " quality assurance ", " test engineer "]),
        ("Frontend", [" frontend ", " front end ", " web developer "]),
        ("Backend", [" backend ", " back end "]),
        ("DevOps", [" devops ", " developer experience ", " cloud administrator "]),
        ("Data Engineering", [" data engineer ", " data platform "]),
        ("Data Science", [" data scientist ", " machine learning ", " ml "]),
        ("Analytics", [" analytics ", " analyst ", " business intelligence ", " bi "]),
        ("Security", [" security ", " securty ", " grc ", " incident response "]),
        ("Support", [" support ", " service desk "]),
        ("Onboarding", [" onboarding ", " implementation "]),
        ("Design", [" designer ", " design ", " ux ", " researcher "]),
        ("Sales", [" sales ", " account ", " partnership ", " business development ", " sdr ", " bdr "]),
        ("Marketing", [" marketing ", " mktg ", " growth ", " content ", " demand generation "]),
        ("Finance", [" finance ", " financial ", " fp&a ", " accounting ", " accountant ", " payroll "]),
        ("People", [" people ", " human resources ", " hr ", " recruiter ", " talent "]),
        ("Legal", [" legal ", " counsel ", " paralegal ", " compliance ", " contracts "]),
        ("Product", [" product "]),
        ("Operations", [" operations ", " ops ", " program ", " project coordinator "]),
        ("IT", [" information technology ", " info tech ", " infrastructure ", " systems administrator ", " network engineer "]),
        ("Software Engineering", [" software ", " engineer ", " engineering ", " developer "]),
    ]
    return next((family for family, terms in families if any(term in text for term in terms)), "Unknown")


def infer_department(title: str, raw_department: str, raw_team: str = "") -> tuple[str, float, bool]:
    title_text = normalize_text(title)
    raw_text = normalize_text(raw_department).strip()
    missing = raw_text in {"", "n/a", "unknown", "-"}

    raw_match = None
    if not missing:
        for department in DEPARTMENTS:
            if raw_text == department.lower().replace("&", "and"):
                raw_match = department
                break
        raw_match = raw_match or DEPARTMENT_ALIASES.get(raw_text)

    # "Product Engineering" is an engineering function, not Product
    # Management. Resolve this common compound title before the generic
    # Product keyword is considered.
    title_match = (
        "Engineering"
        if any(term in title_text for term in (" product engineering ", " product eng "))
        else next(
        (
            department
            for department, terms in DEPARTMENT_TITLE_PRIORITY
            if any(normalize_text(term) in title_text for term in terms)
        ),
        None,
        )
    )

    # Generated team values are containment paths such as
    # Company / Technology / Engineering / Product Engineering.  Use an exact
    # path segment as a second independent department signal; the previous
    # parser inspected only the first segment ("Company") and discarded this
    # useful evidence.
    team_match = None
    # Inspect the deepest path segment first. In
    # Company / Revenue / Customer Success, "Revenue" is a portfolio while
    # "Customer Success" is the employee's department.
    for segment in reversed(str(raw_team or "").split("/")):
        normalized_segment = normalize_text(segment).strip()
        for department in DEPARTMENTS:
            if normalized_segment == normalize_text(department).strip():
                team_match = department
                break
        team_match = team_match or DEPARTMENT_ALIASES.get(normalized_segment)
        if team_match:
            break
    if raw_match and title_match == raw_match:
        return raw_match, 0.98, missing
    if title_match:
        return title_match, 0.88 if raw_match is None else 0.72, missing
    if team_match and raw_match == team_match:
        return team_match, 0.96, missing
    if team_match:
        return team_match, 0.82 if raw_match is None else 0.70, missing
    if raw_match:
        return raw_match, 0.76, missing
    return "Unknown", 0.22, True


def infer_rank(title: str) -> tuple[int, str, float]:
    text = normalize_text(title)
    compact = text.strip()
    if not compact:
        return 1, "Unknown", 0.15
    words = [
        {"sr": "senior", "mgr": "manager", "manger": "manager", "cust": "customer"}.get(word, word)
        for word in compact.split()
    ]
    compact = " ".join(words)
    for city in REGIONAL_TITLE_SUFFIXES:
        if compact.endswith(f" {city}"):
            compact = compact[: -(len(city) + 1)]
            break
    if "chief executive officer" in compact or compact == "ceo":
        return 10, "CEO", 1.0
    c_suite_abbreviations = {"cto", "cro", "coo", "cpo", "cmo", "cdo", "cfo", "ciso", "cio", "cco", "cpo people"}
    if compact.startswith("chief ") or compact in c_suite_abbreviations or "general counsel" in compact:
        return 9, "C-Suite", 0.97
    if "vice president" in compact or re.search(r"\bvp\b", compact) or compact.startswith("head "):
        return 8, "VP / Head", 0.94
    if "senior director" in compact or "sr director" in compact:
        return 7, "Senior Director", 0.94
    if "director" in compact:
        return 6, "Director", 0.94

    modifier = compact.split(" ", 1)[0]
    base = compact.split(" ", 1)[1] if modifier in {
        "junior", "senior", "staff", "lead", "principal"
    } else compact
    if base in AMBIGUOUS_IC_MANAGER_TITLES:
        if modifier == "junior":
            return 0, "Junior IC", 0.87
        if modifier == "senior":
            return 2, "Senior IC", 0.88
        if modifier in {"staff", "lead", "principal"}:
            return 3, "Principal / Staff IC", 0.87
        return 1, "Individual Contributor", 0.86

    if ("senior manager" in compact or re.search(r"\bsr manager\b", compact)
            or re.search(r"^senior .+ manager$", compact)):
        return 5, "Senior Manager", 0.92
    if "team lead" in compact or "supervisor" in compact:
        return 3, "Team Lead / Supervisor", 0.91
    management_terms = ["manager", "group product"]
    if any(f" {term} " in f" {compact} " for term in management_terms):
        return 4, "Manager", 0.88
    if (
        compact.startswith("staff ")
        or compact.startswith("lead ")
        or compact.startswith("principal ")
        or compact.endswith(" lead")
    ):
        return 3, "Principal / Staff IC", 0.88
    if compact.startswith("senior ") or compact.startswith("sr "):
        return 2, "Senior IC", 0.9
    if compact.startswith("junior "):
        return 0, "Junior IC", 0.9
    return 1, "Individual Contributor", 0.72


def is_people_manager_level(rank_label: str) -> bool:
    """Only explicit management titles may receive inferred direct reports."""
    return rank_label in {
        "CEO", "C-Suite", "VP / Head", "Senior Director", "Director",
        "Senior Manager", "Manager", "Team Lead / Supervisor",
    }


def parse_employees(messy: pd.DataFrame, truth: pd.DataFrame) -> list[ParsedEmployee]:
    truth_fields = truth.set_index("employee_id")[["manager_employee_id", "noise_profile"]].to_dict("index")
    parsed: list[ParsedEmployee] = []
    for row in messy.itertuples(index=False):
        department, department_confidence, department_missing = infer_department(
            row.job_title, row.department, row.team
        )
        raw_team = str(row.team or "")
        normalized_team = normalize_text(raw_team).strip()
        team_missing = normalized_team in {"", "n/a", "unknown", "-"}
        rank, rank_label, _ = infer_rank(row.job_title)
        truth_row = truth_fields[row.employee_id]
        parsed.append(
            ParsedEmployee(
                employee_id=row.employee_id,
                company_id=row.company_id,
                full_name=row.full_name,
                job_title=row.job_title,
                raw_department=row.department,
                raw_team=raw_team,
                team="Unknown" if team_missing else normalized_team,
                location=row.location,
                department=department,
                department_confidence=department_confidence,
                role_family=infer_role_family(row.job_title),
                rank=rank,
                rank_label=rank_label,
                people_manager_cue=is_people_manager_level(rank_label),
                title_missing=not bool(str(row.job_title).strip()),
                department_missing=department_missing,
                team_missing=team_missing,
                true_manager_id=str(truth_row["manager_employee_id"] or ""),
                noise_profile=str(truth_row["noise_profile"] or "clean"),
            )
        )
    return parsed


def feature_vector(report: ParsedEmployee, manager: ParsedEmployee) -> tuple[float, ...]:
    rank_gap = manager.rank - report.rank
    same_department = report.department != "Unknown" and report.department == manager.department
    raw_department_match = (
        bool(report.raw_department.strip())
        and normalize_text(report.raw_department) == normalize_text(manager.raw_department)
    )
    same_team = report.team != "Unknown" and report.team == manager.team
    parent_team = report.team.rsplit(" / ", 1)[0] if " / " in report.team else ""
    return (
        float(same_department),
        float(rank_gap == 1),
        float(rank_gap == 2),
        float(rank_gap >= 3),
        float(bool(report.location) and report.location == manager.location),
        float(manager.people_manager_cue),
        float(manager.rank >= 9),
        float(report.title_missing),
        float(report.department_missing),
        report.department_confidence,
        manager.department_confidence,
        float(raw_department_match),
        manager.rank / 10.0,
        report.rank / 10.0,
        float(same_team),
        float(report.team_missing),
        float(bool(parent_team) and parent_team == manager.team),
        float(report.role_family != "Unknown" and report.role_family == manager.role_family),
        float(manager.people_manager_cue and manager.rank == 3),
    )


def heuristic_score(report: ParsedEmployee, manager: ParsedEmployee, features: tuple[float, ...]) -> float:
    rank_gap = manager.rank - report.rank
    score = 2.9 * features[0]
    score += 2.6 if rank_gap == 1 else 1.6 if rank_gap == 2 else 0.5
    score += 0.9 * features[4] + 0.8 * features[5] + 0.35 * features[11]
    score += 5.0 * features[14]
    score += 4.0 * features[16]
    score += 2.4 * features[17] + 0.5 * features[18]
    score += 0.25 * features[9] + 0.2 * features[10]
    if manager.rank == 10 and report.rank >= 8:
        score += 4.0
    elif manager.rank == 10 and report.rank < 6:
        score -= 3.0
    if report.department == "Unknown":
        score -= 0.5
    return score


EXECUTIVE_SCOPE_DEPARTMENTS = {
    "technology": {"Engineering", "Product", "Data & Analytics", "Security", "IT"},
    "cto": {"Engineering", "Product", "Data & Analytics", "Security", "IT"},
    "revenue": {"Sales", "Marketing", "Customer Success"},
    "cro": {"Sales", "Marketing", "Customer Success"},
    "operating": {"Operations"},
    "coo": {"Operations"},
    "financial": {"Finance", "Legal"},
    "cfo": {"Finance", "Legal"},
    "people": {"People"},
}

SCOPE_STOPWORDS = {
    "company", "chief", "officer", "of", "vp", "vice", "president", "head",
    "director", "senior", "manager", "mgr", "manger", "team", "lead",
    "supervisor", "engineering", "sales", "customer", "success", "operations",
    "product", "marketing", "data", "analytics", "finance", "people", "security",
    "it", "legal", "technology", "revenue", "risk", "and",
}


def scope_tokens(value: str) -> set[str]:
    """Keep only the words that distinguish one functional scope from another."""
    return set(normalize_text(value).strip().split()) - SCOPE_STOPWORDS


def team_leaf(team: str) -> str:
    return team.rsplit(" / ", 1)[-1] if team != "Unknown" else ""


def executive_scope_departments(person: ParsedEmployee) -> set[str]:
    title = normalize_text(person.job_title)
    return next(
        (departments for cue, departments in EXECUTIVE_SCOPE_DEPARTMENTS.items() if cue in title),
        set(),
    )


def management_parent_pool(
    report: ParsedEmployee, company: list[ParsedEmployee]
) -> tuple[list[ParsedEmployee], str]:
    """Reconstruct the likely parent layer for an explicit management title.

    Rank and title-derived department/portfolio determine the layer. Team paths
    and role words only separate peers inside that layer. The function returns
    a high-confidence parent only when that evidence identifies one person.
    """
    pool = [
        person for person in company
        if person.employee_id != report.employee_id
        and person.rank > report.rank
        and person.people_manager_cue
        and not person.title_missing
    ]
    if report.rank == 9:
        pool = [person for person in pool if person.rank == 10]
    elif report.rank == 8:
        matching_executives = [
            person for person in pool
            if person.rank == 9 and report.department in executive_scope_departments(person)
        ]
        pool = matching_executives or [person for person in pool if person.rank == 10]
    elif report.rank in {6, 7}:
        pool = [
            person for person in pool
            if person.rank == 8 and person.department == report.department
        ]
    elif report.rank == 5:
        pool = [
            person for person in pool
            if person.rank in {6, 7} and person.department == report.department
        ]
    elif report.rank == 4:
        pool = [
            person for person in pool
            if person.rank in {5, 6, 7, 8} and person.department == report.department
        ]
    elif report.rank == 3 and report.rank_label == "Team Lead / Supervisor":
        pool = [
            person for person in pool
            if person.rank == 4 and person.department == report.department
        ]
    else:
        return [], ""

    if not pool:
        return [], ""
    closest_rank = min(person.rank for person in pool)
    pool = [person for person in pool if person.rank == closest_rank]
    # Senior Manager relationships remain model-scored: their title alone does
    # not reliably identify which Director owns the scope.
    can_mark_structural = report.rank_label != "Senior Manager"
    if len(pool) == 1 and report.rank_label != "Team Lead / Supervisor":
        return pool, pool[0].employee_id if can_mark_structural else ""

    report_tokens = scope_tokens(team_leaf(report.team)) | scope_tokens(report.job_title)
    parent_team = report.team.rsplit(" / ", 1)[0] if " / " in report.team else ""
    scored: list[tuple[float, bool, ParsedEmployee]] = []
    for person in pool:
        exact_team = report.team != "Unknown" and report.team == person.team
        parent_team_match = bool(parent_team) and parent_team == person.team
        overlap = len(
            report_tokens
            & (scope_tokens(team_leaf(person.team)) | scope_tokens(person.job_title))
        )
        role_match = (
            report.role_family != "Unknown" and report.role_family == person.role_family
        )
        score = 8.0 * exact_team + 10.0 * parent_team_match + 4.0 * role_match + 3.0 * overlap
        has_scope_evidence = exact_team or parent_team_match or overlap > 0
        scored.append((score, has_scope_evidence, person))
    scored.sort(key=lambda item: (-item[0], item[2].employee_id))
    pool = [item[2] for item in scored]
    unique_scope = (
        can_mark_structural
        and scored[0][1]
        and (len(scored) == 1 or scored[0][0] > scored[1][0])
    )
    return pool, pool[0].employee_id if unique_scope else ""


def apply_structural_confidence(
    report_candidates: list[Candidate], probabilities: np.ndarray
) -> np.ndarray:
    """Blend a validated deterministic hierarchy match into model confidence."""
    structural = [index for index, candidate in enumerate(report_candidates) if candidate.structural_match]
    if len(structural) != 1:
        return probabilities
    adjusted = probabilities.copy()
    adjusted[structural[0]] = max(float(adjusted[structural[0]]), 0.995)
    return adjusted


def preserves_team_lead_layer(
    report: ParsedEmployee,
    manager: ParsedEmployee,
    company: list[ParsedEmployee],
) -> bool:
    """Do not publish a junior/intermediate edge that may skip a Team Lead.

    A missing Team Lead scope makes the direct parent ambiguous; leaving the
    edge unresolved is safer than attaching the employee straight to a formal
    Manager and flattening the visible hierarchy.
    """
    if report.rank >= 2 or manager.rank < 4:
        return True
    plausible_leads = [
        person for person in company
        if person.rank_label == "Team Lead / Supervisor"
        and person.department == report.department
        and (
            person.team == "Unknown"
            or (report.team != "Unknown" and person.team == report.team)
        )
    ]
    # A missing title can hide the Team Lead itself. Treat a missing-title
    # person in the same scope as unresolved evidence instead of flattening the
    # employee directly under the formal Manager.
    possible_hidden_leads = [
        person for person in company
        if person.title_missing
        and person.department == report.department
        and (
            person.team == "Unknown"
            or (report.team != "Unknown" and person.team == report.team)
        )
    ]
    same_department_leads = [
        person for person in company
        if person.rank_label == "Team Lead / Supervisor"
        and person.department == report.department
    ]
    scoped_population = sum(
        1 for person in company
        if report.team != "Unknown"
        and person.team == report.team
        and person.department == report.department
    )
    possible_corrupted_scope = scoped_population >= 7 and same_department_leads
    return not (plausible_leads or possible_hidden_leads or possible_corrupted_scope)


def build_candidates(company: list[ParsedEmployee], limit: int = 48) -> dict[str, list[Candidate]]:
    """Shortlist explicit people managers from the same company.

    Senior, Staff and Principal titles are IC career levels. They never become
    manager candidates unless the title also contains an explicit management
    cue such as Manager, Director, VP, Team Lead or Supervisor.
    """
    candidates: dict[str, list[Candidate]] = {}
    for report in company:
        if report.rank == 10:
            candidates[report.employee_id] = []
            continue
        structural_parent_id = ""
        if report.people_manager_cue:
            pool, structural_parent_id = management_parent_pool(report, company)
        else:
            pool = [
                person for person in company
                if person.employee_id != report.employee_id
                and person.rank > report.rank
                and person.people_manager_cue
                and not (person.rank == 3 and report.rank >= 2)
            ]
        same_department = [person for person in pool if report.department != "Unknown" and person.department == report.department]
        same_team = [
            person for person in pool
            if report.team != "Unknown"
            and person.team == report.team
            and (report.department == "Unknown" or person.department == report.department)
        ]
        parent_team = report.team.rsplit(" / ", 1)[0] if " / " in report.team else ""
        same_parent_team = [
            person for person in pool
            if parent_team
            and person.team == parent_team
            and (report.department == "Unknown" or person.department == report.department)
        ]
        scoped_team_lead = False
        if report.people_manager_cue:
            pass
        elif report.rank < 2:
            team_leads = [
                person for person in pool
                if person.rank_label == "Team Lead / Supervisor"
                and person.department == report.department
            ]
            exact_team_leads = [
                person for person in team_leads
                if report.team != "Unknown" and person.team == report.team
            ]
            if exact_team_leads:
                pool = exact_team_leads
                scoped_team_lead = True
                if len(pool) == 1:
                    structural_parent_id = pool[0].employee_id
            elif team_leads:
                report_scope = scope_tokens(team_leaf(report.team)) | scope_tokens(report.job_title)
                lead_scores = [
                    (
                        len(report_scope & (
                            scope_tokens(team_leaf(person.team)) | scope_tokens(person.job_title)
                        )),
                        person,
                    )
                    for person in team_leads
                ]
                lead_scores.sort(key=lambda item: (-item[0], item[1].employee_id))
                if (
                    lead_scores[0][0] > 0
                    and (len(lead_scores) == 1 or lead_scores[0][0] > lead_scores[1][0])
                ):
                    pool = [lead_scores[0][1]]
                    structural_parent_id = pool[0].employee_id
                    scoped_team_lead = True
        if report.people_manager_cue or scoped_team_lead:
            pass
        elif same_team:
            team_leads = [person for person in same_team if person.rank == 3]
            formal_managers = [person for person in same_team if person.rank >= 4]
            if report.rank < 2 and team_leads:
                pool = team_leads
            elif formal_managers:
                closest_rank = min(person.rank for person in formal_managers)
                pool = [person for person in formal_managers if person.rank == closest_rank]
            else:
                closest_rank = min(person.rank for person in same_team)
                pool = [person for person in same_team if person.rank == closest_rank]
        elif same_parent_team:
            closest_rank = min(person.rank for person in same_parent_team)
            pool = [person for person in same_parent_team if person.rank == closest_rank]
        elif report.role_family == "Quality Assurance" and report.rank <= 3:
            # QA ICs and QA Team Leads remain inside the QA management chain.
            qa_managers = [
                person for person in pool
                if person.role_family == "Quality Assurance"
            ]
            local_qa_managers = [
                person for person in qa_managers
                if bool(report.location) and person.location == report.location
            ]
            pool = local_qa_managers or qa_managers
        elif same_department:
            closest_rank = min(person.rank for person in same_department)
            pool = [person for person in same_department if person.rank == closest_rank]
        elif report.rank >= 8:
            pool = [person for person in pool if person.rank >= 9]
        ranked: list[Candidate] = []
        for manager in pool:
            features = feature_vector(report, manager)
            ranked.append(Candidate(
                manager.employee_id,
                features,
                heuristic_score(report, manager, features),
                manager.employee_id == structural_parent_id,
            ))
        ranked.sort(key=lambda item: (-int(item.structural_match), -item.heuristic_score, item.manager_id))
        candidates[report.employee_id] = ranked[:limit]
    return candidates


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-values))


def rounded_metric(value: float) -> float:
    """Match SQLite and UI half-up rounding for stored four-place metrics."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def fit_logistic(matrix: np.ndarray, labels: np.ndarray, steps: int = 180) -> LogisticModel:
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale < 1e-6] = 1.0
    normalized = (matrix - mean) / scale
    weights = np.zeros(normalized.shape[1], dtype=np.float64)
    bias = 0.0
    positives = max(float(labels.sum()), 1.0)
    negatives = max(float(len(labels) - labels.sum()), 1.0)
    positive_weight = min(8.0, negatives / positives)
    row_weights = np.where(labels == 1.0, positive_weight, 1.0)
    normalizer = row_weights.sum()
    for step in range(steps):
        probabilities = sigmoid(normalized @ weights + bias)
        error = (probabilities - labels) * row_weights
        learning_rate = 0.09 / math.sqrt(1.0 + step / 24.0)
        gradient = normalized.T @ error / normalizer + 0.012 * weights
        weights -= learning_rate * gradient
        bias -= learning_rate * float(error.sum() / normalizer)
    return LogisticModel(mean=mean, scale=scale, weights=weights, bias=bias)


def fit_platt(logits: np.ndarray, labels: np.ndarray, steps: int = 240) -> tuple[float, float]:
    """Adjust raw scores so confidence better matches observed correctness."""
    slope = 1.0
    intercept = 0.0
    for step in range(steps):
        probabilities = sigmoid(slope * logits + intercept)
        error = probabilities - labels
        learning_rate = 0.04 / math.sqrt(1.0 + step / 40.0)
        slope -= learning_rate * float(np.mean(error * logits))
        intercept -= learning_rate * float(np.mean(error))
    return slope, intercept


def calibrated_probability(model: LogisticModel, features: np.ndarray, platt: tuple[float, float]) -> np.ndarray:
    slope, intercept = platt
    return sigmoid(slope * model.logits(features) + intercept)


def pair_matrix(
    company_groups: dict[str, list[ParsedEmployee]], company_ids: set[str]
) -> tuple[np.ndarray, np.ndarray, float]:
    rows: list[tuple[float, ...]] = []
    labels: list[float] = []
    eligible = 0
    captured = 0
    for company_id in sorted(company_ids):
        company = company_groups[company_id]
        candidates = build_candidates(company)
        for report in company:
            if not report.true_manager_id:
                continue
            eligible += 1
            report_candidates = candidates[report.employee_id]
            if any(candidate.manager_id == report.true_manager_id for candidate in report_candidates):
                captured += 1
            for candidate in report_candidates:
                rows.append(candidate.features)
                labels.append(float(candidate.manager_id == report.true_manager_id))
    return (
        np.asarray(rows, dtype=np.float64),
        np.asarray(labels, dtype=np.float64),
        captured / eligible if eligible else 0.0,
    )


def top_choice_logits(
    company_groups: dict[str, list[ParsedEmployee]], company_ids: set[str], model: LogisticModel
) -> tuple[np.ndarray, np.ndarray]:
    """Use one validation example per report to calibrate the leading choice."""
    scores: list[float] = []
    labels: list[float] = []
    for company_id in sorted(company_ids):
        candidates = build_candidates(company_groups[company_id])
        for report in company_groups[company_id]:
            if not report.true_manager_id or not candidates[report.employee_id]:
                continue
            choices = candidates[report.employee_id]
            logits = model.logits(np.asarray([choice.features for choice in choices]))
            best = int(np.argmax(logits))
            scores.append(float(logits[best]))
            labels.append(float(choices[best].manager_id == report.true_manager_id))
    return np.asarray(scores), np.asarray(labels)


def top_choice_summaries(
    company_groups: dict[str, list[ParsedEmployee]],
    company_ids: set[str],
    model: LogisticModel | None,
    platt: tuple[float, float] | None,
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for company_id in sorted(company_ids):
        company = company_groups[company_id]
        people_by_id = {person.employee_id: person for person in company}
        candidates = build_candidates(company)
        for report in company:
            if not report.true_manager_id:
                continue
            report_candidates = candidates[report.employee_id]
            if not report_candidates:
                summaries.append({
                    "company_id": company_id,
                    "employee_id": report.employee_id,
                    "truth": report.true_manager_id,
                    "top": "",
                    "confidence": 0.0,
                    "margin": 0.0,
                    "candidate_hit": False,
                    "noise_profile": report.noise_profile,
                })
                continue
            if model is None:
                scores = np.asarray([candidate.heuristic_score for candidate in report_candidates])
                probabilities = sigmoid((scores - 5.3) / 1.25)
            else:
                matrix = np.asarray([candidate.features for candidate in report_candidates], dtype=np.float64)
                probabilities = calibrated_probability(model, matrix, platt or (1.0, 0.0))
                probabilities = apply_structural_confidence(report_candidates, probabilities)
            order = np.argsort(-probabilities)
            best = int(order[0])
            second_probability = float(probabilities[order[1]]) if len(order) > 1 else 0.0
            top_manager = people_by_id[report_candidates[best].manager_id]
            qa_scope_matches = not (
                report.rank < 4
                and report.role_family == "Quality Assurance"
                and top_manager.role_family != "Quality Assurance"
            )
            team_lead_layer_matches = preserves_team_lead_layer(
                report, top_manager, company
            )
            summaries.append({
                "company_id": company_id,
                "employee_id": report.employee_id,
                "truth": report.true_manager_id,
                "top": report_candidates[best].manager_id,
                "confidence": float(probabilities[best]),
                "margin": float(probabilities[best] - second_probability),
                "candidate_hit": any(candidate.manager_id == report.true_manager_id for candidate in report_candidates),
                "can_accept": (
                    not report.title_missing
                    and qa_scope_matches
                    and team_lead_layer_matches
                ),
                "noise_profile": report.noise_profile,
            })
    return summaries


def tune_threshold(
    summaries: list[dict[str, object]],
    target_precision: float = 0.90,
    minimum_margin: float = 0.10,
) -> dict[str, float]:
    """Accept as many links as possible without lowering the precision target."""
    total = len(summaries)
    candidates: list[dict[str, float]] = []
    for probability_threshold in np.arange(0.45, 0.961, 0.025):
        for margin_threshold in np.arange(minimum_margin, 0.951, 0.025):
            selected = [
                row for row in summaries
                if row["top"]
                and bool(row.get("can_accept", True))
                and float(row["confidence"]) >= probability_threshold
                and float(row["margin"]) >= margin_threshold
            ]
            correct = sum(row["top"] == row["truth"] for row in selected)
            predicted = len(selected)
            precision = correct / predicted if predicted else 0.0
            coverage = predicted / total if total else 0.0
            recall = correct / total if total else 0.0
            candidates.append({
                "probability": float(round(probability_threshold, 3)),
                "margin": float(round(margin_threshold, 3)),
                "precision": precision,
                "coverage": coverage,
                "recall": recall,
                "predicted": float(predicted),
            })
    feasible = [row for row in candidates if row["precision"] >= target_precision and row["predicted"] >= 50]
    if feasible:
        return max(feasible, key=lambda row: (row["coverage"], row["precision"], row["recall"]))
    # If the data cannot support the target, leave every link unresolved.
    return {
        "probability": 1.0,
        "margin": 1.0,
        "precision": 0.0,
        "coverage": 0.0,
        "recall": 0.0,
        "predicted": 0.0,
    }


def evaluate_summaries(
    summaries: list[dict[str, object]], threshold: dict[str, float]
) -> dict[str, object]:
    selected = [
        row for row in summaries
        if row["top"]
        and bool(row.get("can_accept", True))
        and float(row["confidence"]) >= threshold["probability"]
        and float(row["margin"]) >= threshold["margin"]
    ]
    correct = sum(row["top"] == row["truth"] for row in selected)
    predicted = len(selected)
    total = len(summaries)
    precision = correct / predicted if predicted else 0.0
    recall = correct / total if total else 0.0
    coverage = predicted / total if total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    candidate_recall = sum(bool(row["candidate_hit"]) for row in summaries) / total if total else 0.0
    top_probabilities = np.asarray([float(row["confidence"]) for row in summaries], dtype=np.float64)
    top_correct = np.asarray([float(row["top"] == row["truth"]) for row in summaries], dtype=np.float64)
    brier = float(np.mean((top_probabilities - top_correct) ** 2)) if total else 0.0
    bins = np.linspace(0.0, 1.0, 11)
    ece = 0.0
    calibration_bins: list[dict[str, float]] = []
    for low, high in zip(bins[:-1], bins[1:]):
        mask = (top_probabilities >= low) & (top_probabilities < high if high < 1.0 else top_probabilities <= high)
        if not mask.any():
            continue
        confidence = float(top_probabilities[mask].mean())
        accuracy = float(top_correct[mask].mean())
        share = float(mask.mean())
        ece += abs(confidence - accuracy) * share
        calibration_bins.append({
            "low": round(float(low), 2), "high": round(float(high), 2),
            "confidence": round(confidence, 4), "accuracy": round(accuracy, 4),
            "count": int(mask.sum()),
        })

    noise_metrics: dict[str, dict[str, float]] = {}
    noise_types = sorted({noise for row in summaries for noise in str(row["noise_profile"]).split("|")})
    for noise in noise_types:
        population = [row for row in summaries if noise in str(row["noise_profile"]).split("|")]
        chosen = [row for row in selected if noise in str(row["noise_profile"]).split("|")]
        noise_correct = sum(row["top"] == row["truth"] for row in chosen)
        noise_metrics[noise] = {
            "population": len(population),
            "precision": round(noise_correct / len(chosen), 4) if chosen else 0.0,
            "coverage": round(len(chosen) / len(population), 4) if population else 0.0,
        }
    return {
        "eligible_edges": total,
        "predicted_edges": predicted,
        "correct_edges": correct,
        "unresolved_edges": total - predicted,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "coverage": round(coverage, 4),
        "f1": round(f1, 4),
        "candidate_recall": round(candidate_recall, 4),
        "brier_score_top_choice": round(brier, 4),
        "expected_calibration_error": round(float(ece), 4),
        "calibration_bins": calibration_bins,
        "by_noise_type": noise_metrics,
        "threshold": {
            "probability": threshold["probability"],
            "margin": threshold["margin"],
        },
    }


def prediction_reasons(
    report: ParsedEmployee,
    manager: ParsedEmployee,
    margin: float,
    structural_match: bool = False,
) -> list[str]:
    reasons: list[str] = []
    if structural_match:
        reasons.append("explicit management path")
    if report.department == manager.department and report.department != "Unknown":
        reasons.append("same department")
    if report.team == manager.team and report.team != "Unknown":
        reasons.append("same team")
    if " / " in report.team and report.team.rsplit(" / ", 1)[0] == manager.team:
        reasons.append("parent team")
    if report.role_family != "Unknown" and report.role_family == manager.role_family:
        reasons.append("matching role family")
    rank_gap = manager.rank - report.rank
    reasons.append("one level above" if rank_gap == 1 else "higher inferred seniority")
    if report.location and report.location == manager.location:
        reasons.append("same location")
    if manager.people_manager_cue and manager.rank >= 4:
        reasons.append("leadership title")
    elif manager.people_manager_cue:
        reasons.append("explicit team lead")
    if margin >= 0.15:
        reasons.append("clear candidate margin")
    return reasons[:4]


def export_predictions(
    companies: pd.DataFrame,
    company_groups: dict[str, list[ParsedEmployee]],
    model: LogisticModel,
    platt: tuple[float, float],
    threshold: dict[str, float],
    output_dir: Path,
) -> dict[str, object]:
    company_output = output_dir / "companies"
    company_output.mkdir(parents=True, exist_ok=True)
    company_rows = companies.set_index("company_id").to_dict("index")
    index_rows: list[dict[str, object]] = []
    aggregate_confidence: list[float] = []

    for company_id in sorted(company_groups):
        people = company_groups[company_id]
        people_by_id = {person.employee_id: person for person in people}
        candidate_map = build_candidates(people)
        employees: list[dict[str, object]] = []
        resolved = 0
        correct = 0
        confidence_values: list[float] = []
        for report in people:
            report_candidates = candidate_map[report.employee_id]
            predicted_manager_id = ""
            top_candidate_id = ""
            confidence = 0.0
            margin = 0.0
            reasons: list[str] = []
            if report_candidates:
                matrix = np.asarray([candidate.features for candidate in report_candidates], dtype=np.float64)
                probabilities = calibrated_probability(model, matrix, platt)
                probabilities = apply_structural_confidence(report_candidates, probabilities)
                order = np.argsort(-probabilities)
                best = int(order[0])
                top_candidate_id = report_candidates[best].manager_id
                confidence = float(probabilities[best])
                second = float(probabilities[order[1]]) if len(order) > 1 else 0.0
                margin = confidence - second
                qa_scope_matches = not (
                    report.rank < 4
                    and report.role_family == "Quality Assurance"
                    and people_by_id[top_candidate_id].role_family != "Quality Assurance"
                )
                team_lead_layer_matches = preserves_team_lead_layer(
                    report, people_by_id[top_candidate_id], people
                )
                if (not report.title_missing and qa_scope_matches and team_lead_layer_matches
                        and confidence >= threshold["probability"]
                        and margin >= threshold["margin"]):
                    predicted_manager_id = top_candidate_id
                    resolved += 1
                    correct += int(predicted_manager_id == report.true_manager_id)
                    reasons = prediction_reasons(
                        report,
                        people_by_id[predicted_manager_id],
                        margin,
                        report_candidates[best].structural_match,
                    )
                    confidence_values.append(confidence)
                    aggregate_confidence.append(confidence)
            employees.append({
                "id": report.employee_id,
                "name": report.full_name,
                "title": report.job_title or "Title unavailable",
                "rawDepartment": report.raw_department or "Unavailable",
                "team": report.raw_team or "Unavailable",
                "inferredDepartment": report.department,
                "inferredLevel": report.rank_label,
                "location": report.location or "Unavailable",
                "predictedManagerId": predicted_manager_id or None,
                "bestCandidateId": top_candidate_id or None,
                "confidence": round(confidence, 4),
                "margin": round(margin, 4),
                "reasons": reasons,
                "groundTruthManagerId": report.true_manager_id or None,
                "isCorrect": bool(predicted_manager_id and predicted_manager_id == report.true_manager_id),
                "isRoot": not bool(report.true_manager_id),
                "noiseProfile": report.noise_profile.split("|"),
            })
        company_meta = company_rows[company_id]
        # Company counts describe inferred decisions, not the hidden answer key.
        eligible = max(sum(person.rank_label != "CEO" for person in people), 1)
        payload = {
            "company": {
                "id": company_id,
                "name": company_meta["company_name"],
                "industry": company_meta["industry"],
                "sizeBand": company_meta["size_band"],
                "employeeCount": int(company_meta["employee_count"]),
                "headquarters": company_meta["headquarters"],
            },
            "summary": {
                "resolved": resolved,
                "unresolved": eligible - resolved,
                "coverage": rounded_metric(resolved / eligible),
                "precision": rounded_metric(correct / resolved) if resolved else 0.0,
                "averageConfidence": rounded_metric(float(np.mean(confidence_values))) if confidence_values else 0.0,
            },
            "employees": employees,
        }
        (company_output / f"{company_id}.json").write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
        index_rows.append({**payload["company"], **payload["summary"]})

    index_payload = {
        "companies": index_rows,
        "summary": {
            "companyCount": len(index_rows),
            "employeeCount": int(companies["employee_count"].sum()),
            "averageResolvedConfidence": rounded_metric(float(np.mean(aggregate_confidence))) if aggregate_confidence else 0.0,
        },
    }
    (output_dir / "index.json").write_text(json.dumps(index_payload, separators=(",", ":")), encoding="utf-8")
    return index_payload


def main() -> None:
    args = parse_args()
    np.random.seed(args.seed)
    messy = pd.read_csv(args.data_dir / "employees_messy.csv", keep_default_na=False)
    truth = pd.read_csv(args.data_dir / "employees_ground_truth.csv", keep_default_na=False)
    companies = pd.read_csv(args.data_dir / "companies.csv", keep_default_na=False)
    parsed = parse_employees(messy, truth)
    company_groups: dict[str, list[ParsedEmployee]] = defaultdict(list)
    for employee in parsed:
        company_groups[employee.company_id].append(employee)

    company_ids = sorted(company_groups)
    train_ids = set(company_ids[:350])
    validation_ids = set(company_ids[350:425])
    test_ids = set(company_ids[425:])

    train_matrix, train_labels, train_candidate_recall = pair_matrix(company_groups, train_ids)
    _, _, validation_candidate_recall = pair_matrix(company_groups, validation_ids)
    model = fit_logistic(train_matrix, train_labels)
    validation_logits, validation_labels = top_choice_logits(company_groups, validation_ids, model)
    platt = fit_platt(validation_logits, validation_labels)

    validation_model_summaries = top_choice_summaries(company_groups, validation_ids, model, platt)
    validation_baseline_summaries = top_choice_summaries(company_groups, validation_ids, None, None)
    # Favor precision: a wrong reporting line is costlier than an unresolved one.
    model_threshold = tune_threshold(validation_model_summaries, target_precision=0.97)
    baseline_threshold = tune_threshold(
        validation_baseline_summaries, target_precision=0.80, minimum_margin=0.0
    )

    test_model_summaries = top_choice_summaries(company_groups, test_ids, model, platt)
    test_baseline_summaries = top_choice_summaries(company_groups, test_ids, None, None)
    model_metrics = evaluate_summaries(test_model_summaries, model_threshold)
    baseline_metrics = evaluate_summaries(test_baseline_summaries, baseline_threshold)

    evaluation = {
        "dataset": {
            "companies": int(len(companies)),
            "employees": int(len(messy)),
            "industries": int(companies["industry"].nunique()),
            "minimumCompanySize": int(companies["employee_count"].min()),
            "maximumCompanySize": int(companies["employee_count"].max()),
        },
        "split": {
            "trainCompanies": len(train_ids),
            "validationCompanies": len(validation_ids),
            "testCompanies": len(test_ids),
            "unit": "company",
        },
        "baseline": baseline_metrics,
        "model": model_metrics,
        "candidateRecall": {
            "train": round(train_candidate_recall, 4),
            "validation": round(validation_candidate_recall, 4),
            "test": model_metrics["candidate_recall"],
        },
        "structuralChecks": {
            "oneManagerPerResolvedEmployee": True,
            "cycles": 0,
            "crossCompanyEdges": 0,
            "managerAlwaysMoreSenior": True,
            "unresolvedAllowed": True,
        },
        "featureNames": FEATURE_NAMES,
        "modelType": "Hybrid hierarchy rules and calibrated logistic pair scoring",
        "primaryObjective": "Maximize coverage while holding validation precision at or above 97%",
        "limitations": [
            "Synthetic reporting assignments between otherwise identical managers are not always observable when team, title, or department values are missing.",
            "The system intentionally abstains when the best candidate is not clearly separated from alternatives.",
            "Results measure recovery of generated direct-manager edges, not real-world org-chart accuracy.",
        ],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.model_dir.mkdir(parents=True, exist_ok=True)
    export_predictions(companies, company_groups, model, platt, model_threshold, args.output_dir)
    (args.output_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    model_payload = {
        "featureNames": FEATURE_NAMES,
        "mean": model.mean.tolist(),
        "scale": model.scale.tolist(),
        "weights": model.weights.tolist(),
        "bias": model.bias,
        "plattSlope": platt[0],
        "plattIntercept": platt[1],
        "threshold": model_threshold,
        "seed": args.seed,
    }
    (args.model_dir / "model.json").write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()

