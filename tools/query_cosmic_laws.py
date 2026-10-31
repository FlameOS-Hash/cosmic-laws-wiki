#!/usr/bin/env python3

from pathlib import Path
import argparse
import os
import re
import sys


ROOT = Path(
    os.environ.get("COSMIC_WIKI", Path.cwd())
).resolve()

SOURCE_DIR = ROOT / "wiki" / "cosmic-laws"

LAW_FILE_RE = re.compile(
    r"^LAW-RW-(\d{3})-.+\.md$",
    re.IGNORECASE
)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by",
    "for", "from", "how", "in", "is", "it", "of", "on",
    "or", "that", "the", "this", "to", "was", "what",
    "when", "where", "which", "who", "why", "with",
    "law", "laws", "cosmic", "address", "addresses",
    "about", "related", "relate", "relevant", "please",
    "show", "tell", "me", "full", "decree"
}


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value).lower()
    ).strip()


def title_from_text(text):
    m = re.search(
        r"^#\s+(.+?)\s*$",
        text,
        re.MULTILINE
    )
    return m.group(1).strip() if m else ""


def extract_section(text, heading):
    m = re.search(
        rf"^##\s+{re.escape(heading)}\s*$",
        text,
        re.MULTILINE | re.IGNORECASE
    )

    if not m:
        return None

    start = m.end()

    next_heading = re.search(
        r"^##\s+.+$",
        text[start:],
        re.MULTILINE
    )

    end = (
        start + next_heading.start()
        if next_heading
        else len(text)
    )

    return text[start:end].strip()


def extract_summary(text):
    registry = extract_section(
        text,
        "Registry Record"
    )

    if not registry:
        return None

    m = re.search(
        r"^\|\s*summary\s*\|\s*(.*?)\s*\|\s*$",
        registry,
        re.MULTILINE | re.IGNORECASE
    )

    if m:
        return m.group(1).strip()

    m = re.search(
        r"^\s*summary\s*:\s*(.+?)\s*$",
        registry,
        re.MULTILINE | re.IGNORECASE
    )

    return m.group(1).strip() if m else None


def query_terms(question):
    words = re.findall(
        r"[A-Za-z0-9][A-Za-z0-9'-]*",
        question.lower()
    )

    result = []

    for word in words:
        if len(word) <= 2:
            continue

        if word in STOPWORDS:
            continue

        if re.fullmatch(r"law-rw-\d{3}", word):
            continue

        if word not in result:
            result.append(word)

    return result


def detect_explicit_id(question):
    m = re.search(
        r"\bLAW-RW-(\d{3})\b",
        question,
        re.IGNORECASE
    )

    if not m:
        return None

    return f"LAW-RW-{m.group(1)}"


def load_laws():
    laws = []

    for path in sorted(SOURCE_DIR.glob("LAW-RW-*.md")):
        match = LAW_FILE_RE.match(path.name)

        if not match:
            continue

        text = path.read_text(encoding="utf-8")

        laws.append({
            "number": int(match.group(1)),
            "id": f"LAW-RW-{int(match.group(1)):03d}",
            "path": path,
            "title": title_from_text(text),
            "summary": extract_summary(text),
            "decree": extract_section(text, "Full Decree"),
            "text": text,
        })

    if len(laws) != 144:
        die(
            f"expected 144 authoritative law pages; "
            f"found {len(laws)}"
        )

    return laws


def exact_record_answer(question, law):
    q = question.lower()

    wants_decree = "decree" in q
    wants_purpose = (
        "purpose" in q
        or "summary" in q
    )
    wants_governing = "governing records" in q
    wants_links = "linked laws" in q
    wants_crosslinks = (
        "crosslink" in q
        or "cross-link" in q
    )

    if not any([
        wants_decree,
        wants_purpose,
        wants_governing,
        wants_links,
        wants_crosslinks,
    ]):
        return None

    print("===== EXACT ID ROUTING =====")
    print(
        f"{law['id']} -> {law['path'].name}"
    )
    print()
    print(f"# {law['title']}")
    print()
    print("MODE: EXACT RECORD / NO LLM")
    print()

    if wants_decree:
        print("## Full Decree")
        print(
            law["decree"]
            or "[Full Decree section not found.]"
        )
        print()

    if wants_purpose:
        print("## Governing Purpose")

        if law["summary"]:
            print(law["summary"])
        else:
            print(
                "[No summary field found in "
                "Registry Record.]"
            )

        print()

    if wants_governing:
        print("## Governing Records")
        print(
            extract_section(
                law["text"],
                "Governing Records"
            )
            or "[Section not found.]"
        )
        print()

    if wants_links:
        print("## Linked Laws")
        print(
            extract_section(
                law["text"],
                "Linked Laws"
            )
            or "[Section not found.]"
        )
        print()

    if wants_crosslinks:
        print("## Registry Crosslinks")
        print(
            extract_section(
                law["text"],
                "Registry Crosslinks"
            )
            or "[Section not found.]"
        )
        print()

    print(
        f"Source: wiki/cosmic-laws/"
        f"{law['path'].name}"
    )

    return True


def term_score(term, law):
    title = law["title"].lower()
    summary = (law["summary"] or "").lower()
    decree = (law["decree"] or "").lower()

    score = 0
    locations = []

    title_words = set(
        re.findall(r"[a-z0-9]+", title)
    )

    if term in title_words:
        score += 100
        locations.append("title")
    elif term in title:
        score += 60
        locations.append("title")

    if term in summary:
        score += 30
        locations.append("summary")

    if term in decree:
        score += 15
        locations.append("full decree")

    return score, locations


def rank_laws(question, laws, limit):
    terms = query_terms(question)

    if not terms:
        die(
            "no searchable subject terms remained "
            "after normalization"
        )

    qnorm = " ".join(terms)

    # Prefer meaningful adjacent query concepts such as
    # "return access" over incidental occurrences of the
    # individual words somewhere in a decree.
    phrases = []

    for size in (3, 2):
        for i in range(len(terms) - size + 1):
            phrase = " ".join(
                terms[i:i + size]
            )

            if phrase not in phrases:
                phrases.append(phrase)

    scored = []

    for law in laws:
        total = 0
        coverage = 0
        title_hits = 0
        matched = {}

        title_norm = normalize(
            law["title"]
        )
        summary_norm = normalize(
            law["summary"] or ""
        )
        decree_norm = normalize(
            law["decree"] or ""
        )

        phrase_matches = []

        for phrase in phrases:
            if phrase in title_norm:
                total += 1200
                phrase_matches.append(
                    f"{phrase} (title)"
                )

            elif phrase in summary_norm:
                total += 700
                phrase_matches.append(
                    f"{phrase} (summary)"
                )

            elif phrase in decree_norm:
                total += 150
                phrase_matches.append(
                    f"{phrase} (full decree)"
                )

        for term in terms:
            score, locations = term_score(
                term,
                law
            )

            if score > 0:
                coverage += 1
                total += score
                matched[term] = locations

                if "title" in locations:
                    title_hits += 1

        if coverage == 0:
            continue

        total += coverage * 250
        total += title_hits * 75

        scored.append({
            **law,
            "score": total,
            "coverage": coverage,
            "matched": matched,
            "phrase_matches": phrase_matches,
        })

    scored.sort(
        key=lambda row: (
            -row["coverage"],
            -row["score"],
            row["number"],
        )
    )

    # Guarantee that every requested term gets a strong representative
    # where one exists, instead of allowing one repeated concept to
    # consume the whole result set.
    selected = []
    selected_ids = set()

    # FIRST: guarantee strongest exact multi-word query phrases
    # appearing in LAW TITLES. Example:
    # "return access" -> "Return Access Law".
    for phrase in phrases:
        title_phrase_candidates = [
            row for row in scored
            if phrase in normalize(row["title"])
        ]

        title_phrase_candidates.sort(
            key=lambda row: (
                -row["coverage"],
                -row["score"],
                row["number"],
            )
        )

        if title_phrase_candidates:
            candidate = title_phrase_candidates[0]

            if candidate["id"] not in selected_ids:
                selected.append(candidate)
                selected_ids.add(candidate["id"])

    # SECOND: guarantee a strong representative for each
    # individual requested term.
    for term in terms:
        candidates = [
            row for row in scored
            if term in row["matched"]
        ]

        candidates.sort(
            key=lambda row: (
                -(
                    1
                    if "title"
                    in row["matched"][term]
                    else 0
                ),
                -term_score(term, row)[0],
                row["number"],
            )
        )

        if candidates:
            candidate = candidates[0]

            if candidate["id"] not in selected_ids:
                selected.append(candidate)
                selected_ids.add(candidate["id"])

    for row in scored:
        if len(selected) >= limit:
            break

        if row["id"] in selected_ids:
            continue

        selected.append(row)
        selected_ids.add(row["id"])

    # Preserve selection priority:
    # 1. exact query phrase in title
    # 2. strongest title representative for each term
    # 3. remaining related laws by deterministic score
    return terms, selected[:limit]


def deterministic_search_answer(
    question,
    laws,
    limit
):
    terms, results = rank_laws(
        question,
        laws,
        limit
    )

    print(
        "===== DETERMINISTIC LAW SEARCH ====="
    )
    print(
        "Query terms: "
        + ", ".join(terms)
    )
    print("Mode: NO LLM")
    print()

    if not results:
        print(
            "No authoritative law pages matched "
            "the requested terms."
        )
        return

    print("Relevant laws found:")
    print()

    for row in results:
        matched_terms = []

        for term, locations in row["matched"].items():
            matched_terms.append(
                f"{term} ({', '.join(locations)})"
            )

        print(
            f"### {row['id']} — {row['title']}"
        )

        print(
            "Matched: "
            + "; ".join(matched_terms)
        )

        if row.get("phrase_matches"):
            print(
                "Phrase matches: "
                + "; ".join(
                    row["phrase_matches"]
                )
            )

        if row["summary"]:
            print()
            print("Registry summary:")
            print(row["summary"])

        print()
        print(
            f"Source: wiki/cosmic-laws/"
            f"{row['path'].name}"
        )
        print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic read-only query tool "
            "for the Cosmic Laws Wiki"
        )
    )

    parser.add_argument(
        "question",
        nargs="+"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=6,
        help="Maximum deterministic search results"
    )

    args = parser.parse_args()

    if args.limit < 1 or args.limit > 20:
        die("--limit must be between 1 and 20")

    question = " ".join(
        args.question
    ).strip()

    laws = load_laws()

    explicit_id = detect_explicit_id(
        question
    )

    if explicit_id:
        matches = [
            law for law in laws
            if law["id"] == explicit_id
        ]

        if len(matches) != 1:
            die(
                f"{explicit_id}: expected one exact "
                f"authoritative record; found {len(matches)}"
            )

        law = matches[0]

        if exact_record_answer(
            question,
            law
        ):
            return

        print("===== EXACT ID ROUTING =====")
        print(
            f"{law['id']} -> {law['path'].name}"
        )
        print()
        print(f"# {law['title']}")
        print()
        print("MODE: EXACT RECORD / NO LLM")
        print()

        if law["summary"]:
            print("## Registry Summary")
            print(law["summary"])
            print()

        print("## Full Decree")
        print(
            law["decree"]
            or "[Full Decree section not found.]"
        )
        print()

        print(
            f"Source: wiki/cosmic-laws/"
            f"{law['path'].name}"
        )

        return

    deterministic_search_answer(
        question,
        laws,
        args.limit
    )


if __name__ == "__main__":
    main()
