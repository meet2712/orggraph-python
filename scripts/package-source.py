"""Create matching dataset and source downloads for the current build."""

from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile
from build_erd import build_diagram

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "public/downloads/orggraph-source.zip"
DATASET_DESTINATION = ROOT / "public/downloads/firmable-org-chart-dataset.zip"
DATABASE_DESTINATION = ROOT / "public/downloads/orggraph.sqlite.gz"
DATASET_FILES = [
    ROOT / "data/companies.csv",
    ROOT / "data/employees_messy.csv",
    ROOT / "data/employees_ground_truth.csv",
    ROOT / "data/dataset_summary.json",
    ROOT / "DATA_DICTIONARY.md",
    ROOT / "pipeline/generate_dataset.py",
    ROOT / "pipeline/validate_dataset.py",
]
EXCLUDED_DIRECTORIES = {
    "__pycache__", "venv", "instance", "dist", "outputs", "work", "node_modules",
}
ALLOWED_HIDDEN_FILES = {".gitignore", ".python-version", ".gitattributes"}


def include_file(path):
    relative = path.relative_to(ROOT)
    if any(
        part.startswith(".") or part in EXCLUDED_DIRECTORIES
        for part in relative.parts[:-1]
    ):
        return False
    if path.name.startswith(".") and path.name not in ALLOWED_HIDDEN_FILES:
        return False
    if path == DESTINATION or path.suffix in {".pyc", ".pem", ".log"}:
        return False
    return not path.is_symlink()


def main():
    build_diagram()
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    # Keep a checked, compressed SQLite copy directly in the Git repository.
    shutil.copy2(ROOT / "instance/snapshot.sqlite.gz", DATABASE_DESTINATION)
    with ZipFile(DATASET_DESTINATION, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in DATASET_FILES:
            archive.write(path, path.relative_to(ROOT))
    files = sorted(
        path for path in ROOT.rglob("*") if path.is_file() and include_file(path)
    )
    with ZipFile(DESTINATION, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, Path("orggraph") / path.relative_to(ROOT))
    print(f"Packaged {len(files)} source files: {DESTINATION.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
