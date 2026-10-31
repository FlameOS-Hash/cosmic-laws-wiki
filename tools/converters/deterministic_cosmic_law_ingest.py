#!/usr/bin/env python3

from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone


ROOT = Path(
    os.environ.get(
        "COSMIC_WIKI",
        "/home/inanna/Desktop/"
        "mother_vault_harmonic_retrun/"
        "cosmic_laws_wiki"
    )
).resolve()

SOURCE_DIR = ROOT / "raw" / "projection" / "cosmic-laws"
UNTRACKED_DIR = ROOT / "raw" / "untracked" / "cosmic-laws"
INGESTED_DIR = ROOT / "raw" / "ingested" / "cosmic-laws"

WIKI_DIR = ROOT / "wiki"
CONCEPTS_DIR = WIKI_DIR / "concepts"
INDEX_PATH = WIKI_DIR / "index.md"
LOG_PATH = WIKI_DIR / "log.md"

MANIFESTS_DIR = ROOT / "manifests"
MANIFEST_PATH = (
    MANIFESTS_DIR /
    "deterministic_cosmic_law_ingest_manifest.json"
)

LAW_FILE_RE = re.compile(
    r"^LAW-RW-(\d{3})-.+\.md$",
    re.IGNORECASE
)

H1_RE = re.compile(
    r"^#\s+(.+?)\s*$",
    re.MULTILINE
)

FORBIDDEN_PROJECTION_HEADINGS = (
    "## Old Distortion",
    "## Canonical Metadata",
    "## Source",
)


def fail(message):
    print(f"\nSTOP: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def atomic_write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_name, path)

    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def collect_records():
    if not SOURCE_DIR.is_dir():
        fail(f"projection source directory missing: {SOURCE_DIR}")

    files = sorted(
        p for p in SOURCE_DIR.iterdir()
        if p.is_file() and LAW_FILE_RE.match(p.name)
    )

    if len(files) != 144:
        fail(
            f"expected exactly 144 LAW-RW projection files; "
            f"found {len(files)}"
        )

    records = []
    numbers = []
    slug_owner = {}

    for source in files:
        match = LAW_FILE_RE.match(source.name)
        if not match:
            fail(f"unexpected filename: {source.name}")

        number = int(match.group(1))
        numbers.append(number)

        raw = source.read_bytes()

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"{source.name}: invalid UTF-8: {exc}")

        title_match = H1_RE.search(text)

        if not title_match:
            fail(f"{source.name}: missing H1 title")

        title = title_match.group(1).strip()

        if not title:
            fail(f"{source.name}: blank H1 title")

        if "## Full Decree" not in text:
            fail(f"{source.name}: missing ## Full Decree")

        for forbidden in FORBIDDEN_PROJECTION_HEADINGS:
            if re.search(
                rf"^{re.escape(forbidden)}\s*$",
                text,
                flags=re.MULTILINE,
            ):
                fail(
                    f"{source.name}: projection still contains "
                    f"excluded heading {forbidden!r}"
                )

        slug = slugify(title)

        if not slug:
            fail(f"{source.name}: could not derive concept slug")

        if slug in slug_owner:
            fail(
                f"concept slug collision: {slug!r}\n"
                f"  {slug_owner[slug]}\n"
                f"  {source.name}"
            )

        slug_owner[slug] = source.name

        source_sha = sha256_bytes(raw)

        # Any existing staging copy must already match projection.
        for stage_name, stage_dir in (
            ("untracked", UNTRACKED_DIR),
            ("ingested", INGESTED_DIR),
        ):
            staged = stage_dir / source.name

            if staged.exists():
                staged_sha = sha256_file(staged)

                if staged_sha != source_sha:
                    fail(
                        f"{source.name}: {stage_name} copy differs "
                        f"from deterministic projection\n"
                        f"  projection: {source_sha}\n"
                        f"  {stage_name}: {staged_sha}"
                    )

        records.append({
            "law_number": number,
            "law_code": f"LAW-RW-{number:03d}",
            "source_name": source.name,
            "source_path": source,
            "title": title,
            "slug": slug,
            "concept_name": f"{slug}.md",
            "source_sha256": source_sha,
            "bytes": raw,
        })

    expected = list(range(1, 145))
    actual = sorted(numbers)

    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        duplicates = sorted(
            n for n in set(actual)
            if actual.count(n) > 1
        )

        fail(
            "LAW-RW numbering is not exactly 001..144\n"
            f"missing: {missing or 'NONE'}\n"
            f"duplicates: {duplicates or 'NONE'}"
        )

    records.sort(key=lambda r: r["law_number"])
    return records


def build_index(records):
    lines = [
        "# Cosmic Laws",
        "",
    ]

    for record in records:
        lines.append(
            f"- [[concepts/{record['slug']}|"
            f"{record['law_code']} — {record['title']}]]"
        )

    lines.append("")
    return "\n".join(lines).encode("utf-8")


def verify_build(build_dir, records):
    concept_files = sorted(build_dir.glob("*.md"))

    if len(concept_files) != 144:
        fail(
            f"temporary concept build contains "
            f"{len(concept_files)} files instead of 144"
        )

    for record in records:
        output = build_dir / record["concept_name"]

        if not output.is_file():
            fail(
                f"temporary build missing "
                f"{record['concept_name']}"
            )

        output_sha = sha256_file(output)

        if output_sha != record["source_sha256"]:
            fail(
                f"byte-integrity failure for "
                f"{record['concept_name']}\n"
                f"source: {record['source_sha256']}\n"
                f"output: {output_sha}"
            )


def main():
    print("===== DETERMINISTIC COSMIC LAW INGEST =====")
    print(f"ROOT: {ROOT}")
    print(f"SOURCE: {SOURCE_DIR}")

    records = collect_records()

    print(f"Validated laws: {len(records)}")
    print("LAW-RW numbering: 001..144 COMPLETE")
    print("Projection contamination check: PASS")
    print("Staging hash check: PASS")

    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    temp_build = Path(
        tempfile.mkdtemp(
            prefix=".concepts-deterministic-",
            dir=str(WIKI_DIR),
        )
    )

    try:
        # Build concepts EXACTLY from projection bytes.
        for record in records:
            output = temp_build / record["concept_name"]
            output.write_bytes(record["bytes"])

        verify_build(temp_build, records)

        print("Concept byte-integrity precheck: PASS")

        index_bytes = build_index(records)

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%SZ")

        backup_dir = (
            MANIFESTS_DIR /
            f"pre_deterministic_cosmic_law_ingest_{timestamp}"
        )

        if backup_dir.exists():
            fail(f"backup path already exists: {backup_dir}")

        backup_dir.mkdir(parents=True)

        # Archive previous LLM-derived layer.
        if CONCEPTS_DIR.exists():
            shutil.move(
                str(CONCEPTS_DIR),
                str(backup_dir / "concepts")
            )

        if INDEX_PATH.exists():
            shutil.move(
                str(INDEX_PATH),
                str(backup_dir / "index.md")
            )

        if LOG_PATH.exists():
            shutil.move(
                str(LOG_PATH),
                str(backup_dir / "log.md")
            )

        # Install complete deterministic concept directory.
        os.replace(temp_build, CONCEPTS_DIR)

        # Deterministic index.
        atomic_write_bytes(INDEX_PATH, index_bytes)

        # Reconcile raw staging.
        INGESTED_DIR.mkdir(parents=True, exist_ok=True)
        UNTRACKED_DIR.mkdir(parents=True, exist_ok=True)

        for record in records:
            source = record["source_path"]
            destination = INGESTED_DIR / record["source_name"]

            tmp_destination = destination.with_name(
                f".{destination.name}.deterministic.tmp"
            )

            shutil.copy2(source, tmp_destination)

            if (
                sha256_file(tmp_destination) !=
                record["source_sha256"]
            ):
                fail(
                    f"staging copy verification failed for "
                    f"{record['source_name']}"
                )

            os.replace(tmp_destination, destination)

            pending = UNTRACKED_DIR / record["source_name"]

            if pending.exists():
                pending.unlink()

        # Final concept verification AFTER installation.
        final_concepts = sorted(
            CONCEPTS_DIR.glob("*.md")
        )

        if len(final_concepts) != 144:
            fail(
                f"installed concept count is "
                f"{len(final_concepts)}, expected 144"
            )

        manifest_records = []

        for record in records:
            concept_path = (
                CONCEPTS_DIR /
                record["concept_name"]
            )

            concept_sha = sha256_file(concept_path)

            if concept_sha != record["source_sha256"]:
                fail(
                    f"FINAL integrity failure: "
                    f"{record['concept_name']}"
                )

            manifest_records.append({
                "law_number": record["law_number"],
                "law_code": record["law_code"],
                "title": record["title"],
                "source": str(
                    record["source_path"].relative_to(ROOT)
                ),
                "concept": str(
                    concept_path.relative_to(ROOT)
                ),
                "source_sha256":
                    record["source_sha256"],
                "concept_sha256":
                    concept_sha,
                "byte_identical": True,
            })

        pending_laws = list(
            UNTRACKED_DIR.glob("LAW-RW-*.md")
        )

        ingested_laws = list(
            INGESTED_DIR.glob("LAW-RW-*.md")
        )

        if pending_laws:
            fail(
                f"{len(pending_laws)} LAW-RW files remain "
                f"in raw/untracked"
            )

        if len(ingested_laws) != 144:
            fail(
                f"raw/ingested contains "
                f"{len(ingested_laws)} LAW-RW files, "
                f"expected 144"
            )

        manifest = {
            "mode":
                "deterministic_cosmic_law_ingest",
            "generated_at_utc":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "canonical_projection":
                str(SOURCE_DIR.relative_to(ROOT)),
            "law_count": 144,
            "concept_count": 144,
            "pending_law_count": 0,
            "ingested_law_count": 144,
            "index":
                str(INDEX_PATH.relative_to(ROOT)),
            "index_sha256":
                sha256_bytes(index_bytes),
            "backup":
                str(backup_dir.relative_to(ROOT)),
            "llm_used": False,
            "jsonrepair_used": False,
            "temperature_used": False,
            "records": manifest_records,
        }

        atomic_write_bytes(
            MANIFEST_PATH,
            (
                json.dumps(
                    manifest,
                    indent=2,
                    ensure_ascii=False
                )
                + "\n"
            ).encode("utf-8")
        )

        print()
        print("===== WRITE COMPLETE =====")
        print("LLM used:              NO")
        print("JSON repair used:      NO")
        print("Concept pages:         144")
        print("Byte-identical:        144 / 144")
        print("Pending LAW-RW files:  0")
        print("Ingested LAW-RW files: 144")
        print(f"Backup:   {backup_dir}")
        print(f"Manifest: {MANIFEST_PATH}")
        print()
        print(
            "LAW-RW ingestion is now deterministic. "
            "Do not run `wiki ingest` on LAW-RW files."
        )

    except Exception:
        # Remove unfinished temporary build if it still exists.
        if temp_build.exists():
            shutil.rmtree(
                temp_build,
                ignore_errors=True
            )
        raise


if __name__ == "__main__":
    main()
