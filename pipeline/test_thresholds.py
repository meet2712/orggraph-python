"""Check that weak evidence never lowers the acceptance bar."""

import unittest

from train_and_infer import evaluate_summaries, tune_threshold


def choices(correct: bool, count: int = 60) -> list[dict[str, object]]:
    return [
        {
            "top": "manager-a",
            "truth": "manager-a" if correct else "manager-b",
            "confidence": 0.95,
            "margin": 0.3,
            "candidate_hit": correct,
            "noise_profile": "clean",
        }
        for _ in range(count)
    ]


class ThresholdTests(unittest.TestCase):
    def test_keeps_supported_links(self) -> None:
        rows = choices(correct=True)
        threshold = tune_threshold(rows)
        result = evaluate_summaries(rows, threshold)
        self.assertEqual(result["predicted_edges"], 60)
        self.assertEqual(result["precision"], 1.0)

    def test_abstains_when_no_threshold_meets_the_target(self) -> None:
        rows = choices(correct=False)
        threshold = tune_threshold(rows)
        result = evaluate_summaries(rows, threshold)
        self.assertEqual(result["predicted_edges"], 0)
        self.assertEqual(result["unresolved_edges"], 60)

    def test_abstains_when_evidence_is_too_small(self) -> None:
        rows = choices(correct=True, count=10)
        threshold = tune_threshold(rows)
        self.assertEqual(evaluate_summaries(rows, threshold)["predicted_edges"], 0)

    def test_handles_empty_validation_data(self) -> None:
        threshold = tune_threshold([])
        self.assertEqual(evaluate_summaries([], threshold)["predicted_edges"], 0)


if __name__ == "__main__":
    unittest.main()
