"""The documented generator must reproduce the shipped benchmark inputs."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GenerationTests(unittest.TestCase):
    def test_seed_reproduces_all_shipped_csv_files(self):
        summary = json.loads((ROOT / "data/dataset_summary.json").read_text())
        with TemporaryDirectory() as temporary:
            subprocess.run([
                sys.executable, str(ROOT / "pipeline/generate_dataset.py"),
                "--companies", str(summary["companies"]),
                "--min-employees", str(summary["minimum_company_size"]),
                "--max-employees", str(summary["maximum_company_size"]),
                "--seed", str(summary["seed"]), "--output-dir", temporary,
            ], check=True, stdout=subprocess.DEVNULL)
            for source in (ROOT / "data").glob("*.csv"):
                with self.subTest(file=source.name):
                    generated = Path(temporary) / source.name
                    self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),
                                     hashlib.sha256(generated.read_bytes()).digest())
