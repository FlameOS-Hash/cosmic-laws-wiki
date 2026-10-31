#!/usr/bin/env python3

from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys


ROOT = Path(
    os.environ.get("COSMIC_WIKI", Path.cwd())
).resolve()

SOURCE = ROOT / "wiki" / "cosmic-laws"
PUBLIC = ROOT / "docs"
RELEASES = ROOT / "releases"


def die(message):
    print(f"STOP: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path):
    digest = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def git_head():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def tree_manifest(root):
    rows = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(root).as_posix()
        rows.append(
            f"{sha256(path)}  {rel}"
        )

    return rows


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--release",
        required=True,
        help="numeric release ID, for example 0001",
    )

    args = parser.parse_args()

    number = args.release.strip()

    if not number.isdigit():
        die("release ID must contain digits only")

    release_id = f"cosmic-laws-{number}"

    if not SOURCE.is_dir():
        die("missing wiki/cosmic-laws")

    if not PUBLIC.is_dir():
        die("missing docs public build")

    if not (PUBLIC / ".cosmic-laws-derived").exists():
        die(
            "docs is not marked as a deterministic "
            "Cosmic Laws derived build"
        )

    source_pages = sorted(SOURCE.glob("*.md"))
    law_pages = sorted(SOURCE.glob("LAW-RW-*.md"))

    if len(source_pages) != 172:
        die(
            "expected 172 authoritative pages; "
            f"found {len(source_pages)}"
        )

    if len(law_pages) != 144:
        die(
            "expected 144 Cosmic Laws; "
            f"found {len(law_pages)}"
        )

    RELEASES.mkdir(parents=True, exist_ok=True)

    target = RELEASES / release_id
    staging = RELEASES / f".{release_id}.staging"

    if target.exists():
        die(
            f"{target} already exists; "
            "published release directories are immutable"
        )

    if staging.exists():
        die(
            f"stale staging directory exists: {staging}"
        )

    staging.mkdir()

    try:
        public_target = staging / "public"

        shutil.copytree(
            PUBLIC,
            public_target,
            copy_function=shutil.copy2,
        )

        source_rows = []

        for path in source_pages:
            rel = path.relative_to(ROOT).as_posix()

            source_rows.append(
                f"{sha256(path)}  {rel}"
            )

        source_manifest = (
            staging / "SOURCE_WIKI.sha256"
        )

        source_manifest.write_text(
            "\n".join(source_rows) + "\n",
            encoding="utf-8",
        )

        release_data = {
            "release_id": release_id,
            "authority": "Mother Vault",
            "authoritative_source": "wiki/cosmic-laws",
            "public_build": "docs",
            "source_commit": git_head(),
            "law_count": 144,
            "authoritative_page_count": 172,
            "mirror_policy": "read-only",
            "signature_namespace": "cosmic-laws-release",
            "llm_used": False,
        }

        release_json = staging / "RELEASE.json"

        release_json.write_text(
            json.dumps(
                release_data,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        rows = [
            f"{sha256(release_json)}  RELEASE.json",
            (
                f"{sha256(source_manifest)}  "
                "SOURCE_WIKI.sha256"
            ),
        ]

        for row in tree_manifest(public_target):
            digest, rel = row.split("  ", 1)

            rows.append(
                f"{digest}  public/{rel}"
            )

        manifest = staging / "MANIFEST.sha256"

        manifest.write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )

        staging.rename(target)

    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    print("===== RELEASE BUILD COMPLETE =====")
    print(f"Release:             {release_id}")
    print("Canonical laws:      144")
    print("Authoritative pages: 172")
    print("Mirror policy:       READ-ONLY")
    print("LLM used:            NO")
    print(f"Output:              {target}")


if __name__ == "__main__":
    main()
