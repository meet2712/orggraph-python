"""Regression checks for title parsing and plausible manager candidates."""

import unittest
from dataclasses import replace

from pipeline.train_and_infer import (
    FEATURE_NAMES, ParsedEmployee, build_candidates, infer_department, infer_rank,
    infer_role_family, is_people_manager_level, prediction_reasons,
)


def person(employee_id: str, rank: int, manager: bool | None = None) -> ParsedEmployee:
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
        role_family="Software Engineering",
        rank=rank,
        rank_label="Example level",
        people_manager_cue=rank >= 4 if manager is None else manager,
        title_missing=False,
        department_missing=False,
        team_missing=False,
        true_manager_id="",
        noise_profile="clean",
    )


class InferenceParsingTests(unittest.TestCase):
    def test_manager_seniority_signal_does_not_imply_executive_leadership(self) -> None:
        reasons = prediction_reasons(person("report", 2), person("manager", 4), 0.2)
        self.assertIn("higher inferred seniority", reasons)
        self.assertNotIn("senior leadership match", reasons)

    def test_individual_contributor_manager_titles_are_not_people_managers(self) -> None:
        cases = {
            "Product Manager": 1,
            "Junior Product Mgr": 0,
            "Senior, Account Manager": 2,
            "Lead Account Manager": 3,
            "Principal Account Mgr": 3,
            "Staff Product Manager": 3,
            "Staff Customer Success Manager": 3,
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

    def test_management_ladder_order(self) -> None:
        titles = [
            "Chief Executive Officer", "Chief Technology Officer", "VP of Engineering",
            "Senior Director of Engineering", "Director of Engineering",
            "Senior Engineering Manager", "Engineering Manager", "Engineering Team Lead",
        ]
        ranks = [infer_rank(title)[0] for title in titles]
        self.assertEqual(ranks, [10, 9, 8, 7, 6, 5, 4, 3])
        self.assertTrue(all(is_people_manager_level(infer_rank(title)[1]) for title in titles))

    def test_specific_functions_override_generic_title_words(self) -> None:
        cases = [
            ("Senior Data Engineer", "Eng", "Data & Analytics"),
            ("Security Engineering Manager", "Engineering", "Security"),
            ("IT Support Specialist", "CS", "IT"),
            ("People Operations Manager", "Operations", "People"),
            ("Product Operations Manager", "Operations", "Product"),
            ("Enterprise Success Team Lead", "Sales", "Customer Success"),
            ("Revenue Ops Team Lead", "Sales", "Operations"),
            ("Partnerships Team Lead", "Engineering", "Sales"),
            ("Account Manager", "", "Sales"),
            ("Recruiter", "", "People"),
        ]
        for title, raw_department, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(infer_department(title, raw_department)[0], expected)

    def test_product_engineering_and_team_path_identify_engineering(self) -> None:
        self.assertEqual(
            infer_department("Director of Product Engineering", "Product")[0],
            "Engineering",
        )
        self.assertEqual(
            infer_department(
                "Core Services Team Lead",
                "Data",
                "Company / Technology / Engineering / Core Services",
            )[0],
            "Engineering",
        )

    def test_ambiguous_leadership_words_are_not_people_manager_titles(self) -> None:
        for title in ("Senior Counsel", "Program Lead", "Client Success Lead"):
            with self.subTest(title=title):
                rank, rank_label, _ = infer_rank(title)
                self.assertFalse(is_people_manager_level(rank_label))
                self.assertLess(rank, 4)

    def test_senior_ic_is_not_a_manager_candidate(self) -> None:
        people = [person("report", 0), person("senior_ic", 2), person("manager", 4)]
        candidate_ids = {candidate.manager_id for candidate in build_candidates(people)["report"]}
        self.assertEqual(candidate_ids, {"manager"})

    def test_explicit_team_lead_is_a_manager_candidate_for_junior(self) -> None:
        people = [
            person("report", 0), person("team_lead", 3, manager=True),
            person("principal_ic", 3, manager=False), person("manager", 4),
        ]
        candidate_ids = {candidate.manager_id for candidate in build_candidates(people)["report"]}
        self.assertEqual(candidate_ids, {"team_lead"})

    def test_senior_from_another_function_is_not_a_manager_candidate(self) -> None:
        report = person("report", 0)
        unrelated = replace(
            person("senior_ic", 2), department="Sales", raw_department="Sales",
            role_family="Sales",
        )
        candidate_ids = {candidate.manager_id for candidate in build_candidates([
            report, unrelated, person("manager", 4),
        ])["report"]}
        self.assertEqual(candidate_ids, {"manager"})

    def test_qa_titles_share_a_role_family(self) -> None:
        self.assertEqual(infer_role_family("Junior QA Engineer"), "Quality Assurance")
        self.assertEqual(infer_role_family("Senior QA Engineer"), "Quality Assurance")
        self.assertEqual(infer_role_family("QA Manager"), "Quality Assurance")

    def test_wrong_department_cannot_override_management_ladder(self) -> None:
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
        self.assertEqual(candidates, [])

    def test_explicit_management_ladder_marks_unique_parent(self) -> None:
        report = replace(
            person("director", 6, manager=True),
            job_title="Director of Product Engineering",
            rank_label="Director",
            team="company / technology / engineering / product engineering",
        )
        vp = replace(
            person("vp", 8, manager=True),
            job_title="VP of Engineering",
            rank_label="VP / Head",
            team="company / technology / engineering",
        )
        candidate = build_candidates([report, vp])["director"]
        self.assertEqual([item.manager_id for item in candidate], ["vp"])
        self.assertTrue(candidate[0].structural_match)

    def test_abbreviated_executive_owns_the_correct_portfolio(self) -> None:
        report = replace(
            person("sales_vp", 8, manager=True),
            job_title="VP of Sales",
            rank_label="VP / Head",
            department="Sales",
        )
        cro = replace(
            person("cro", 9, manager=True),
            job_title="CRO",
            rank_label="C-Suite",
            department="Sales",
        )
        cfo = replace(
            person("cfo", 9, manager=True),
            job_title="CFO",
            rank_label="C-Suite",
            department="Finance",
        )
        candidates = build_candidates([report, cro, cfo])["sales_vp"]
        self.assertEqual([item.manager_id for item in candidates], ["cro"])
        self.assertTrue(candidates[0].structural_match)

    def test_team_lead_scope_separates_peer_managers(self) -> None:
        report = replace(
            person("lead", 3, manager=True),
            job_title="Platform Engineering Team Lead",
            rank_label="Team Lead / Supervisor",
            team="company / technology / engineering / platform",
        )
        platform = replace(
            person("platform_manager", 4, manager=True),
            job_title="Platform Engineering Manager",
            rank_label="Manager",
            team="company / technology / engineering / platform",
        )
        web = replace(
            person("web_manager", 4, manager=True),
            job_title="Web Engineering Manager",
            rank_label="Manager",
            team="company / technology / engineering / web",
        )
        candidates = build_candidates([report, platform, web])["lead"]
        self.assertEqual(candidates[0].manager_id, "platform_manager")
        self.assertTrue(candidates[0].structural_match)
        self.assertFalse(candidates[1].structural_match)

    def test_junior_scope_recovers_team_lead_with_missing_team(self) -> None:
        report = replace(
            person("junior", 0),
            job_title="Junior Platform Engineer",
            rank_label="Junior IC",
            team="company / technology / engineering / platform",
        )
        lead = replace(
            person("lead", 3, manager=True),
            job_title="Platform Engineering Team Lead",
            rank_label="Team Lead / Supervisor",
            raw_team="",
            team="Unknown",
            team_missing=True,
        )
        manager = replace(
            person("manager", 4, manager=True),
            job_title="Engineering Manager",
            rank_label="Manager",
            team="company / technology / engineering / platform",
        )
        candidates = build_candidates([report, lead, manager])["junior"]
        self.assertEqual([item.manager_id for item in candidates], ["lead"])
        self.assertTrue(candidates[0].structural_match)

    def test_senior_ic_does_not_report_to_team_lead(self) -> None:
        report = replace(
            person("senior", 2),
            job_title="Senior Platform Engineer",
            rank_label="Senior IC",
            team="company / technology / engineering / platform",
        )
        lead = replace(
            person("lead", 3, manager=True),
            job_title="Platform Engineering Team Lead",
            rank_label="Team Lead / Supervisor",
            team="company / technology / engineering / platform",
        )
        manager = replace(
            person("manager", 4, manager=True),
            job_title="Engineering Manager",
            rank_label="Manager",
            team="company / technology / engineering / platform",
        )
        candidates = build_candidates([report, lead, manager])["senior"]
        self.assertEqual([item.manager_id for item in candidates], ["manager"])


if __name__ == "__main__":
    unittest.main()
