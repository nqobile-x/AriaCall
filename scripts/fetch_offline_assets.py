"""Download the Python engine (Pyodide) so Practice mode works with no internet at all.

Run this once while online:

    python scripts/fetch_offline_assets.py --dry-run     # show what would be downloaded and how big it is
    python scripts/fetch_offline_assets.py               # download into api/static/vendor/pyodide/

After that Aria serves the engine itself (the Practice tab detects it automatically) and it is
never fetched from a CDN. Files land in a git-ignored folder, so nothing is added to a deployment.
Every package wheel is verified against the SHA-256 in Pyodide's own lock file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VERSION = "v0.26.4"
BASE = f"https://cdn.jsdelivr.net/pyodide/{VERSION}/full/"
CORE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
DEFAULT_PACKAGES = ["pandas", "numpy"]
DEFAULT_DEST = Path(__file__).resolve().parent.parent / "api" / "static" / "vendor" / "pyodide"


def resolve_packages(lock: dict, names: list[str]) -> list[str]:
    """Names plus every dependency, each once, dependencies first."""
    packages = lock["packages"]
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        key = name.lower().replace("_", "-")
        if key in seen:
            return
        if key not in packages:
            raise KeyError(f"Package '{name}' is not in Pyodide {VERSION}")
        seen.add(key)
        for dep in packages[key].get("depends", []):
            visit(dep)
        ordered.append(key)

    for name in names:
        visit(name)
    return ordered


def plan(lock: dict, names: list[str]) -> list[dict]:
    """Every file to fetch: core files (no checksum published) then verified package wheels."""
    items = [{"file": f, "sha256": None} for f in CORE_FILES]
    for key in resolve_packages(lock, names):
        entry = lock["packages"][key]
        items.append({"file": entry["file_name"], "sha256": entry.get("sha256")})
    return items


def _client():
    import httpx

    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, connect=10.0))


def fetch_lock(client) -> dict:
    response = client.get(BASE + "pyodide-lock.json")
    response.raise_for_status()
    return response.json()


def _remote_size(client, url: str) -> int:
    """Total size via a 1-byte range request (HEAD omits Content-Length on this CDN)."""
    response = client.get(url, headers={"Range": "bytes=0-0"})
    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        return int(content_range.rsplit("/", 1)[1])
    return int(response.headers.get("content-length", 0))


def dry_run(items: list[dict], client) -> int:
    total = 0
    for item in items:
        size = _remote_size(client, BASE + item["file"])
        total += size
        print(f"  {size / 1_048_576:7.1f} MB  {item['file']}")
    print(f"\nTotal: {total / 1_048_576:.1f} MB from {BASE}")
    return total


def download(items: list[dict], dest: Path, client) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in items:
        target = dest / item["file"]
        if target.exists() and target.stat().st_size > 0 and _matches(target, item["sha256"]):
            print(f"  have  {item['file']}")
            continue
        print(f"  get   {item['file']}")
        response = client.get(BASE + item["file"])
        response.raise_for_status()
        data = response.content
        if item["sha256"] and hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise SystemExit(f"Checksum mismatch for {item['file']}: refusing to save a corrupted or tampered file.")
        target.write_bytes(data)
    print(f"\nDone. Files are in {dest}\nRestart Aria; the Practice tab will now run Python with no internet.")


def _matches(path: Path, sha256: str | None) -> bool:
    return sha256 is None or hashlib.sha256(path.read_bytes()).hexdigest() == sha256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="list files and sizes without downloading")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--packages", nargs="*", default=DEFAULT_PACKAGES, help="Python packages to include")
    args = parser.parse_args(argv)
    with _client() as client:
        items = plan(fetch_lock(client), args.packages)
        if args.dry_run:
            dry_run(items, client)
        else:
            download(items, args.dest, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
