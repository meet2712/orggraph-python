"""Export the Flask pages as static HTML, optionally under a URL path."""

import argparse
from contextlib import closing
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from database import connect, read_index  # noqa: E402


def prefix_worker_paths(output: Path, base_path: str) -> None:
    """Point the browser SQL worker at files inside the project site."""
    replacements = {
        "sql-workbench.js": {
            'new Worker("/sql-worker.js?v=2")': f'new Worker("{base_path}/sql-worker.js?v=2")',
        },
        "sql-worker.js": {
            'importScripts("/vendor/sql-wasm.js")': f'importScripts("{base_path}/vendor/sql-wasm.js")',
            '`/vendor/${file}`': f'`{base_path}/vendor/${{file}}`',
            'fetch("/database/snapshot.sqlite.gz")': f'fetch("{base_path}/database/snapshot.sqlite.gz")',
        },
    }
    for filename, paths in replacements.items():
        target = output / filename
        source = target.read_text(encoding="utf-8")
        for old, new in paths.items():
            if old not in source:
                raise ValueError(f"Expected path not found in {filename}: {old}")
            source = source.replace(old, new)
        target.write_text(source, encoding="utf-8")


def export_site(base_path: str = "") -> None:
    base_path = base_path.rstrip("/")
    if not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", base_path):
        raise ValueError("base path must contain only URL path segments")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package-source.py")],
        cwd=ROOT,
        check=True,
    )
    app.config["TESTING"] = True
    with closing(connect(app.config["DATABASE"], readonly=True)) as connection:
        index = read_index(connection)
    # The export is a fixed snapshot. Reuse one view result while rendering 505
    # pages; normal Flask requests continue to query the live views.
    app.config["STATIC_EXPORT_INDEX"] = index
    routes = [
        ("/", "index.html"),
        ("/results.html", "results.html"),
        ("/approach.html", "approach.html"),
        ("/data.html", "data.html"),
        ("/schema.html", "schema.html"),
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
                html = response.data.decode("utf-8")
                if base_path:
                    html = html.replace('href="/', f'href="{base_path}/')
                    html = html.replace('src="/', f'src="{base_path}/')
                    html = html.replace('data="/', f'data="{base_path}/')
                target.write_text("\n".join(line.strip() for line in html.splitlines() if line.strip()), encoding="utf-8")

        public = ROOT / "public"
        for filename in ("style.css", "app.js", "workbench.css", "sql-workbench.js", "sql-worker.js", "database-erd.svg", "database-erd-full.svg", "database-view-flow.svg", "database-erd.mmd", "database-schema.json"):
            shutil.copy2(public / filename, output / filename)
        if base_path:
            prefix_worker_paths(output, base_path)
        shutil.copytree(public / "downloads", output / "downloads")
        shutil.copytree(public / "vendor", output / "vendor")
        (output / "database").mkdir()
        shutil.copy2(app.config["DATABASE_SNAPSHOT"], output / "database" / "snapshot.sqlite.gz")
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-path", default="", help="URL path prefix, e.g. /orggraph-python")
    export_site(parser.parse_args().base_path)
