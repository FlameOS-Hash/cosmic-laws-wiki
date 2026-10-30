#!/usr/bin/env python3

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(os.environ.get("COSMIC_WIKI", Path.cwd())).resolve()
CSV_ROOT = ROOT / "canonical" / "csv"
OUTPUT_ROOT = ROOT / "wiki" / "cosmic-laws"
MANIFEST_ROOT = ROOT / "manifests"

RECORD_FIELDS = [
    "id",
    "title",
    "record_type",
    "registry_role",
    "domain_id",
    "layer_id",
    "parent_record_id",
    "source_code",
    "status",
    "visibility",
    "summary",
]

DECREE_KEYS = (
    "rewrite",
    "full_decree",
    "decree",
    "full_text",
    "text",
)


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_metadata(raw, source, record_id, errors):
    if raw is None or raw == "":
        return {}

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append({
            "type": "invalid_metadata_json",
            "record_id": record_id,
            "source": str(source),
            "error": str(exc),
        })
        return {}

    if not isinstance(value, dict):
        errors.append({
            "type": "metadata_not_object",
            "record_id": record_id,
            "source": str(source),
        })
        return {}

    return value


def canonical_record(row):
    return {
        key: row.get(key, "")
        for key in RECORD_FIELDS
    } | {
        "metadata": row.get("metadata", "")
    }


def canonical_crosslink(row):
    keys = [
        "id",
        "source_record_id",
        "target_record_id",
        "relationship_type",
        "function_cluster_id",
        "domain_id",
        "status",
        "notes",
        "metadata",
    ]
    return {key: row.get(key, "") for key in keys}


def same_semantic_record(a, b):
    for key in RECORD_FIELDS:
        if a.get(key, "") != b.get(key, ""):
            return False

    try:
        ma = json.loads(a.get("metadata") or "{}")
        mb = json.loads(b.get("metadata") or "{}")
        return ma == mb
    except Exception:
        return a.get("metadata", "") == b.get("metadata", "")


def same_semantic_crosslink(a, b):
    keys = [
        "source_record_id",
        "target_record_id",
        "relationship_type",
        "function_cluster_id",
        "domain_id",
        "status",
        "notes",
    ]

    for key in keys:
        if a.get(key, "") != b.get(key, ""):
            return False

    try:
        ma = json.loads(a.get("metadata") or "{}")
        mb = json.loads(b.get("metadata") or "{}")
        return ma == mb
    except Exception:
        return a.get("metadata", "") == b.get("metadata", "")


def natural_key(value):
    parts = re.split(r"(\d+)", value or "")
    out = []
    for part in parts:
        if part.isdigit():
            out.append((0, int(part)))
        else:
            out.append((1, part))
    return out


def safe_filename(record_id):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", record_id)
    return cleaned.strip("._") or "record"


def markdown_escape_table(value):
    value = "" if value is None else str(value)
    return value.replace("|", "\\|").replace("\n", "<br>")


def wiki_ref(record_id, title, known_ids):
    if record_id in known_ids:
        label = title or record_id
        return f"[[{safe_filename(record_id)}|{label}]]"
    return f"`{record_id}`"


def get_decree(metadata):
    for key in DECREE_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value != "":
            return key, value
    return None, None


def scan_csvs():
    records = {}
    crosslinks = {}
    source_files = {}
    source_imports = []
    review_rows = []
    unknown_rows = []
    conflicts = []
    errors = []

    csv_files = sorted(CSV_ROOT.rglob("*.csv"))

    if not csv_files:
        print(f"ERROR: no CSV files found under:\n{CSV_ROOT}", file=sys.stderr)
        sys.exit(1)

    for path in csv_files:
        file_hash = sha256_file(path)
        source_files[str(path.relative_to(ROOT))] = file_hash

        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
            headers = set(reader.fieldnames or [])

        name_lower = path.name.lower()

        for row in rows:
            # Ignore completely blank CSV rows.
            # A populated row with no required ID is still reported below.
            if not any(
                str(value).strip()
                for value in row.values()
                if value is not None
            ):
                continue

            table_name = (row.get("table_name") or "").strip()

            if table_name == "registry_records":
                kind = "record"
            elif table_name == "registry_crosslinks":
                kind = "crosslink"
            elif table_name == "source_imports":
                kind = "source_import"
            elif "review" in name_lower:
                kind = "review"
            elif "source_import" in name_lower:
                kind = "source_import"
            elif (
                "source_record_id" in headers
                and "target_record_id" in headers
                and "relationship_type" in headers
            ):
                kind = "crosslink"
            elif (
                "record_type" in headers
                and "registry_role" in headers
                and "metadata" in headers
            ):
                kind = "record"
            else:
                kind = "unknown"

            if kind == "record":
                rid = row.get("id", "")
                if not rid:
                    errors.append({
                        "type": "record_missing_id",
                        "source": str(path),
                    })
                    continue

                item = canonical_record(row)
                item["_source_file"] = str(path.relative_to(ROOT))
                item["_source_sha256"] = file_hash

                if rid in records:
                    if not same_semantic_record(records[rid], item):
                        conflicts.append({
                            "type": "duplicate_record_conflict",
                            "id": rid,
                            "first_source": records[rid]["_source_file"],
                            "second_source": item["_source_file"],
                        })
                else:
                    records[rid] = item

            elif kind == "crosslink":
                xid = row.get("id", "")
                if not xid:
                    errors.append({
                        "type": "crosslink_missing_id",
                        "source": str(path),
                    })
                    continue

                item = canonical_crosslink(row)
                item["_source_file"] = str(path.relative_to(ROOT))
                item["_source_sha256"] = file_hash

                # The authored crosslink ID is not necessarily unique.
                # One ID may carry multiple relationship roles
                # (for example governed_by and linked_to_law).
                #
                # Preserve the authored ID unchanged and use a private
                # semantic fingerprint only as the converter's internal key.
                payload = {
                    key: value
                    for key, value in item.items()
                    if not key.startswith("_")
                }

                semantic_hash = hashlib.sha256(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()

                internal_key = f"{xid}@@{semantic_hash}"

                # Exact semantic duplicates collapse for display.
                # Distinct relationships sharing the authored ID survive.
                if internal_key not in crosslinks:
                    crosslinks[internal_key] = item

            elif kind == "source_import":
                source_imports.append({
                    **row,
                    "_source_file": str(path.relative_to(ROOT)),
                    "_source_sha256": file_hash,
                })

            elif kind == "review":
                review_rows.append({
                    **row,
                    "_source_file": str(path.relative_to(ROOT)),
                    "_source_sha256": file_hash,
                })

            else:
                unknown_rows.append({
                    **row,
                    "_source_file": str(path.relative_to(ROOT)),
                    "_source_sha256": file_hash,
                })

    return {
        "records": records,
        "crosslinks": crosslinks,
        "source_files": source_files,
        "source_imports": source_imports,
        "review_rows": review_rows,
        "unknown_rows": unknown_rows,
        "conflicts": conflicts,
        "errors": errors,
    }


def render_record_page(record_id, record, records, crosslinks, errors):
    title = record.get("title") or record_id
    metadata_raw = record.get("metadata", "")
    metadata = parse_metadata(
        metadata_raw,
        record["_source_file"],
        record_id,
        errors,
    )

    decree_key, decree = get_decree(metadata)

    known_ids = set(records)

    lines = []
    lines.append(f"# {title}")
    lines.append("")

    lines.append("## Registry Record")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")

    for key in RECORD_FIELDS:
        value = record.get(key, "")
        if value != "":
            lines.append(
                f"| {key} | {markdown_escape_table(value)} |"
            )

    lines.append("")

    if decree is not None:
        lines.append("## Full Decree")
        lines.append("")
        # DO NOT ALTER decree contents.
        lines.append(decree)
        lines.append("")

    old_distortion = metadata.get("old_distortion")
    if isinstance(old_distortion, str) and old_distortion != "":
        lines.append("## Old Distortion")
        lines.append("")
        lines.append(old_distortion)
        lines.append("")

    governing = metadata.get("governing_records")
    if isinstance(governing, list) and governing:
        lines.append("## Governing Records")
        lines.append("")
        for item in governing:
            item = str(item)
            target = records.get(item, {})
            lines.append(
                f"- {wiki_ref(item, target.get('title', ''), known_ids)}"
            )
        lines.append("")

    linked_laws = metadata.get("linked_laws")
    if isinstance(linked_laws, list) and linked_laws:
        lines.append("## Linked Laws")
        lines.append("")
        for item in linked_laws:
            item = str(item)
            target = records.get(item, {})
            lines.append(
                f"- {wiki_ref(item, target.get('title', ''), known_ids)}"
            )
        lines.append("")

    children = [
        child
        for child in records.values()
        if child.get("parent_record_id") == record_id
    ]

    if children:
        children.sort(key=lambda r: natural_key(r.get("id", "")))

        lines.append("## Records in This Sequence")
        lines.append("")
        for child in children:
            cid = child["id"]
            lines.append(
                f"- [[{safe_filename(cid)}|{child.get('title') or cid}]]"
            )
        lines.append("")

        complete_children = []
        for child in children:
            child_metadata = parse_metadata(
                child.get("metadata", ""),
                child["_source_file"],
                child["id"],
                errors,
            )
            _, child_decree = get_decree(child_metadata)
            if child_decree is not None:
                complete_children.append((child, child_decree))

        if complete_children:
            lines.append("## Complete Law Texts")
            lines.append("")

            for child, child_decree in complete_children:
                lines.append(
                    f"### {child.get('title') or child['id']}"
                )
                lines.append("")
                lines.append(f"`{child['id']}`")
                lines.append("")
                # DO NOT ALTER child decree contents.
                lines.append(child_decree)
                lines.append("")

    related_crosslinks = [
        x
        for x in crosslinks.values()
        if x.get("source_record_id") == record_id
        or x.get("target_record_id") == record_id
    ]

    if related_crosslinks:
        related_crosslinks.sort(
            key=lambda x: natural_key(x.get("id", ""))
        )

        lines.append("## Registry Crosslinks")
        lines.append("")
        lines.append("| Relationship | Source | Target | Status |")
        lines.append("|---|---|---|---|")

        for x in related_crosslinks:
            src = x.get("source_record_id", "")
            dst = x.get("target_record_id", "")
            rel = x.get("relationship_type", "")
            status = x.get("status", "")

            src_title = records.get(src, {}).get("title", "")
            dst_title = records.get(dst, {}).get("title", "")

            src_ref = wiki_ref(src, src_title, known_ids)
            dst_ref = wiki_ref(dst, dst_title, known_ids)

            lines.append(
                "| "
                + markdown_escape_table(rel)
                + " | "
                + markdown_escape_table(src_ref)
                + " | "
                + markdown_escape_table(dst_ref)
                + " | "
                + markdown_escape_table(status)
                + " |"
            )

        lines.append("")

    if metadata_raw != "":
        lines.append("## Canonical Metadata")
        lines.append("")
        lines.append("```json")
        # Keep original CSV metadata string, not regenerated metadata.
        lines.append(metadata_raw)
        lines.append("```")
        lines.append("")

    lines.append("## Source")
    lines.append("")
    lines.append(f"- CSV: `{record['_source_file']}`")
    lines.append(f"- SHA-256: `{record['_source_sha256']}`")
    lines.append("")

    return "\n".join(lines), decree_key, decree


def render_index(records):
    sequences = [
        r for r in records.values()
        if r.get("record_type") == "law_rewrite_sequence"
    ]
    laws = [
        r for r in records.values()
        if r.get("record_type") == "cosmic_law_rewrite"
    ]
    others = [
        r for r in records.values()
        if r.get("record_type")
        not in {"law_rewrite_sequence", "cosmic_law_rewrite"}
    ]

    sequences.sort(key=lambda r: natural_key(r["id"]))
    laws.sort(key=lambda r: natural_key(r["id"]))
    others.sort(key=lambda r: natural_key(r["id"]))

    lines = ["# Cosmic Laws Wiki Index", ""]

    if sequences:
        lines += ["## Sequences", ""]
        for r in sequences:
            lines.append(
                f"- [[{safe_filename(r['id'])}|{r.get('title') or r['id']}]]"
            )
        lines.append("")

    if laws:
        lines += ["## Laws", ""]
        for r in laws:
            lines.append(
                f"- [[{safe_filename(r['id'])}|{r.get('title') or r['id']}]]"
            )
        lines.append("")

    if others:
        lines += ["## Other Registry Records", ""]
        for r in others:
            lines.append(
                f"- [[{safe_filename(r['id'])}|{r.get('title') or r['id']}]]"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Convert canonical Cosmic Law registry CSVs to Markdown."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write generated Markdown pages. Default is preview only.",
    )
    args = parser.parse_args()

    data = scan_csvs()

    records = data["records"]
    crosslinks = data["crosslinks"]

    fatal_conflicts = [
        c for c in data["conflicts"]
        if c.get("type") == "duplicate_record_conflict"
    ]

    crosslink_variants = [
        c for c in data["conflicts"]
        if c.get("type") == "duplicate_crosslink_variant"
    ]

    if fatal_conflicts:
        print("ABORT: conflicting duplicate registry records detected.")
        print(json.dumps(
            fatal_conflicts,
            indent=2,
            ensure_ascii=False,
        ))
        sys.exit(2)

    render_errors = list(data["errors"])
    pages = {}
    missing_full_decree = []

    for record_id in sorted(records, key=natural_key):
        record = records[record_id]

        page, decree_key, decree = render_record_page(
            record_id,
            record,
            records,
            crosslinks,
            render_errors,
        )

        pages[safe_filename(record_id) + ".md"] = page

        if (
            record.get("record_type") == "cosmic_law_rewrite"
            and decree is None
        ):
            missing_full_decree.append(record_id)

    pages["index.md"] = render_index(records)

    existing_conflicts = []

    if args.write:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)

        # Safety gate: never silently overwrite a differing generated page.
        for filename, content in pages.items():
            target = OUTPUT_ROOT / filename
            if target.exists():
                current = target.read_text(encoding="utf-8")
                if current != content:
                    existing_conflicts.append(str(target))

        if existing_conflicts:
            print("ABORT: existing Markdown pages differ from proposed output.")
            print("No files were changed.")
            for path in existing_conflicts:
                print(f"  {path}")
            sys.exit(3)

        for filename, content in pages.items():
            target = OUTPUT_ROOT / filename
            target.write_text(content, encoding="utf-8")

    manifest = {
        "wiki_root": str(ROOT),
        "canonical_csv_root": str(CSV_ROOT),
        "output_root": str(OUTPUT_ROOT),
        "record_count": len(records),
        "crosslink_count": len(crosslinks),
        "source_import_row_count": len(data["source_imports"]),
        "review_row_count": len(data["review_rows"]),
        "unknown_row_count": len(data["unknown_rows"]),
        "source_files": data["source_files"],
        "missing_full_decree": missing_full_decree,
        "errors": render_errors,
        "duplicate_crosslink_variants": crosslink_variants,
        "mode": "write" if args.write else "preview",
    }

    if args.write:
        manifest_path = MANIFEST_ROOT / "cosmic_law_conversion_manifest.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

    print("===== COSMIC LAW CONVERTER =====")
    print(f"Wiki root:        {ROOT}")
    print(f"CSV source:       {CSV_ROOT}")
    print(f"Output:           {OUTPUT_ROOT}")
    print(f"Records:          {len(records)}")
    print(f"Crosslinks:       {len(crosslinks)}")
    print(f"Pages proposed:   {len(pages)}")
    print(f"Source imports:   {len(data['source_imports'])}")
    print(f"Review rows:      {len(data['review_rows'])}")
    print(f"Unknown rows:     {len(data['unknown_rows'])}")
    print(f"Missing decrees:  {len(missing_full_decree)}")
    print(f"Parse errors:     {len(render_errors)}")
    print(f"Crosslink ID variants: {len(crosslink_variants)}")
    print()

    if missing_full_decree:
        print("LAW RECORDS WITH NO FULL DECREE FIELD:")
        for rid in missing_full_decree:
            print(f"  {rid}")
        print()

    if render_errors:
        print("PARSE/SCHEMA WARNINGS:")
        print(json.dumps(render_errors, indent=2, ensure_ascii=False))
        print()

    if args.write:
        print("WRITE COMPLETE.")
        print(
            "Manifest:",
            MANIFEST_ROOT / "cosmic_law_conversion_manifest.json",
        )
    else:
        print("PREVIEW ONLY — no Markdown files were written.")
        print("Run again with --write after reviewing these counts.")


if __name__ == "__main__":
    main()
