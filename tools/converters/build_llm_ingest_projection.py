#!/usr/bin/env python3

from pathlib import Path
from collections import Counter
import shutil
import re
import sys

ROOT = Path(
    "/home/inanna/Desktop/mother_vault_harmonic_retrun/cosmic_laws_wiki"
)

SOURCE = ROOT / "wiki" / "cosmic-laws"
OUTPUT = ROOT / "raw" / "projection" / "cosmic-laws"

# These sections remain in the authoritative Markdown,
# but are intentionally excluded from the LLM ingestion copy.
EXCLUDED = {
    "Old Distortion",
    "Canonical Metadata",
    "Source",
}


def split_sections(text: str):
    """
    Returns:
      preamble: everything before the first ## heading
      sections: [(heading, body), ...]
    """
    lines = text.splitlines(keepends=True)

    preamble = []
    sections = []

    current_heading = None
    current_body = []

    for line in lines:
        m = re.match(r"^##\s+(.+?)\s*$", line)

        if m:
            if current_heading is None:
                if current_body:
                    preamble.extend(current_body)
            else:
                sections.append(
                    (current_heading, "".join(current_body))
                )

            current_heading = m.group(1).strip()
            current_body = []
            continue

        current_body.append(line)

    if current_heading is None:
        preamble.extend(current_body)
    else:
        sections.append(
            (current_heading, "".join(current_body))
        )

    return "".join(preamble), sections


def render_projection(text: str):
    preamble, sections = split_sections(text)

    out = [preamble.rstrip(), ""]

    excluded_found = []

    for heading, body in sections:
        if heading in EXCLUDED:
            excluded_found.append(heading)
            continue

        out.append(f"## {heading}")
        out.append("")
        out.append(body.strip())
        out.append("")

    return "\n".join(out).rstrip() + "\n", excluded_found


def main():
    if not SOURCE.exists():
        raise SystemExit(f"STOP: source missing: {SOURCE}")

    files = sorted(SOURCE.glob("*.md"))

    if len(files) != 172:
        raise SystemExit(
            f"STOP: expected 172 authoritative Markdown files, "
            f"found {len(files)}."
        )

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    OUTPUT.mkdir(parents=True)

    excluded_counts = Counter()

    for src in files:
        text = src.read_text(encoding="utf-8")

        projected, excluded = render_projection(text)

        for heading in excluded:
            excluded_counts[heading] += 1

        dst = OUTPUT / src.name
        dst.write_text(projected, encoding="utf-8")

    generated = sorted(OUTPUT.glob("*.md"))

    print("===== LLM INGEST PROJECTION =====")
    print("Authoritative files:", len(files))
    print("Projected files:    ", len(generated))
    print()

    print("Excluded sections:")
    for heading, count in sorted(excluded_counts.items()):
        print(f"  {heading}: {count}")

    print()
    print("OUTPUT:", OUTPUT)


if __name__ == "__main__":
    main()
