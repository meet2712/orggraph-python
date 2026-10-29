"""Render the Flask pages as static HTML for the hosted preview."""

from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402


def export_site() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package-source.py")],
        cwd=ROOT,
        check=True,
    )
    app.config["TESTING"] = True
    index = app.config["DATASET_INDEX"]
    routes = [
        ("/", "index.html"),
        ("/results.html", "results.html"),
        ("/approach.html", "approach.html"),
    ]
    routes.extend(
        (f"/companies/{company['id']}.html", f"companies/{company['id']}.html")
        for company in index["companies"]
    )

    # Finish the new export before replacing the previous one.
    with TemporaryDirectory(prefix=".orggraph-export-", dir=ROOT) as temporary:
        output = Path(temporary)
        with app.test_client() as client:
            for url, filename in routes:
                response = client.get(url)
                if response.status_code != 200:
                    raise RuntimeError(f"Could not render {url}: {response.status_code}")
                target = output / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(response.data)

        public = ROOT / "public"
        for filename in ("style.css", "app.js"):
            shutil.copy2(public / filename, output / filename)
        shutil.copytree(public / "downloads", output / "downloads")
        favicon = public / "favicon.svg"
        if favicon.exists():
            shutil.copy2(favicon, output / favicon.name)

        destination = ROOT / "dist"
        if destination.is_symlink():
            raise RuntimeError("The export directory must not be a symbolic link")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(output, destination)

    print(f"Exported {len(routes)} pages to dist/")


if __name__ == "__main__":
    export_site()
