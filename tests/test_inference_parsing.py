"""Regression checks for title parsing and plausible manager candidates."""

import unittest
from dataclasses import replace

from pipeline.train_and_infer import ParsedEmployee, build_candidates, infer_department, infer_rank


def person(employee_id: str, rank: int) -> ParsedEmployee:
    return ParsedEmployee(
        employee_id=employee_id,
        company_id="cmp_0001",
        full_name=employee_id,
        job_title="Example title",
        raw_department="Engineering",
        raw_team="Platform",
        team="platform",
        location="Sydney, AU",
        department="Engineering",
        department_confidence=0.9,
        rank=rank,
        rank_label="Example level",
        title_missing=False,
        department_missing=False,
        team_missing=False,
        true_manager_id="",
        noise_profile="clean",
    )


class InferenceParsingTests(unittest.TestCase):
    def test_individual_contributor_manager_titles_are_not_people_managers(self) -> None:
        cases = {
            "Product Manager": 1,
            "Junior Product Mgr": 0,
            "Senior, Account Manager": 2,
            "Lead Account Manager": 3,
            "Principal Account Mgr": 3,
            "Customer Success Manager - Singapore": 1,
            "Cust Success Mgr - Sydney": 1,
            "Senior Customer Success Manager": 2,
            "Account Manger": 1,
        }
        for title, expected_rank in cases.items():
            with self.subTest(title=title):
                self.assertEqual(infer_rank(title)[0], expected_rank)

    def test_real_management_titles_still_parse_as_managers(self) -> None:
        for title in ("Engineering Manager", "Group Product Manager", "Customer Success Team Manager"):
            with self.subTest(title=title):
                self.assertEqual(infer_rank(title)[0], 4)

    def test_specific_functions_override_generic_title_words(self) -> None:
        cases = [
            ("Senior Data Engineer", "Eng", "Data & Analytics"),
            ("Security Engineering Manager", "Engineering", "Security"),
            ("IT Support Specialist", "CS", "IT"),
            ("People Operations Manager", "Operations", "People"),
            ("Product Operations Manager", "Operations", "Product"),
            ("Account Manager", "", "Sales"),
            ("Recruiter", "", "People"),
        ]
        for title, raw_department, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(infer_department(title, raw_department)[0], expected)

    def test_senior_individual_contributors_are_not_manager_candidates(self) -> None:
        people = [person("report", 0), person("senior_ic", 2), person("manager", 4)]
        candidate_ids = {candidate.manager_id for candidate in build_candidates(people)["report"]}
        self.assertEqual(candidate_ids, {"manager"})

    def test_parent_team_scope_survives_a_wrong_department(self) -> None:
        report = replace(
            person("report", 4), department="Engineering",
            raw_team="Operations / Division 1 / Platform",
            team="operations / division 1 / platform",
        )
        director = replace(
            person("director", 5), department="Operations",
            raw_team="Operations / Division 1", team="operations / division 1",
        )
        candidates = build_candidates([report, director])["report"]
        self.assertEqual([candidate.manager_id for candidate in candidates], ["director"])
        self.assertEqual(candidates[0].features[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
