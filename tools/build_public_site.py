#!/usr/bin/env python3

from pathlib import Path
import html
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = Path(
    os.environ.get("COSMIC_WIKI", Path.cwd())
).resolve()

SOURCE = ROOT / "wiki" / "cosmic-laws"
OUTPUT = ROOT / "docs"

LAW_RE = re.compile(r"^LAW-RW-(\d{3})-.+\.md$")
SEQ_RE = re.compile(r"^SC-COSMIC-LAW-REWRITE-.+\.md$")


def fail(msg):
    print(f"STOP: {msg}", file=sys.stderr)
    raise SystemExit(1)


def title_from_text(text):
    m = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def extract_section(text, heading):
    m = re.search(
        rf"^##\s+{re.escape(heading)}\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )

    if not m:
        return ""

    start = m.end()

    nxt = re.search(
        r"^##\s+.+$",
        text[start:],
        re.MULTILINE,
    )

    end = start + nxt.start() if nxt else len(text)

    return text[start:end].strip()


def extract_summary(text):
    registry = extract_section(text, "Registry Record")

    if not registry:
        return ""

    m = re.search(
        r"^\|\s*summary\s*\|\s*(.*?)\s*\|\s*$",
        registry,
        re.MULTILINE | re.IGNORECASE,
    )

    return m.group(1).strip() if m else ""


def yaml_quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


if not SOURCE.is_dir():
    fail(f"missing source directory: {SOURCE}")

sources = sorted(SOURCE.glob("*.md"))

if len(sources) != 172:
    fail(f"expected 172 source pages; found {len(sources)}")

law_sources = sorted(
    [src for src in sources if LAW_RE.match(src.name)],
    key=lambda src: int(LAW_RE.match(src.name).group(1)),
)

law_nav = {}

for i, src in enumerate(law_sources):
    prev_src = law_sources[i - 1] if i > 0 else None
    next_src = (
        law_sources[i + 1]
        if i + 1 < len(law_sources)
        else None
    )

    law_nav[src.name] = {
        "prev": prev_src,
        "next": next_src,
    }

laws = []
sequences = []
search_records = []

tmp = Path(
    tempfile.mkdtemp(
        prefix=".public-site-",
        dir=str(ROOT),
    )
)

try:
    records_dir = tmp / "records"
    layouts_dir = tmp / "_layouts"
    assets_dir = tmp / "assets"

    records_dir.mkdir(parents=True)
    layouts_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    for src in sources:
        if src.name == "index.md":
            continue

        text = src.read_text(encoding="utf-8")
        title = title_from_text(text)

        if not title:
            fail(f"{src.name}: missing H1 title")

        summary = extract_summary(text)

        law_match = LAW_RE.match(src.name)

        fm = [
            "---",
            "layout: record",
            f"title: {yaml_quote(title)}",
            f"source_file: {yaml_quote(src.name)}",
            f"permalink: /records/{src.stem}.html",
        ]

        if law_match:
            number = int(law_match.group(1))
            nav = law_nav[src.name]

            fm.extend([
                "record_kind: law",
                f"law_number: {number}",
            ])

            if nav["prev"]:
                prev_text = nav["prev"].read_text(
                    encoding="utf-8"
                )
                prev_title = title_from_text(prev_text)

                fm.extend([
                    (
                        "prev_url: "
                        f"/records/{nav['prev'].stem}.html"
                    ),
                    (
                        "prev_title: "
                        f"{yaml_quote(prev_title)}"
                    ),
                ])

            if nav["next"]:
                next_text = nav["next"].read_text(
                    encoding="utf-8"
                )
                next_title = title_from_text(next_text)

                fm.extend([
                    (
                        "next_url: "
                        f"/records/{nav['next'].stem}.html"
                    ),
                    (
                        "next_title: "
                        f"{yaml_quote(next_title)}"
                    ),
                ])

        else:
            fm.append("record_kind: sequence")

        fm.extend(["---", ""])

        frontmatter = "\n".join(fm) + "\n"

        target = records_dir / src.name
        target.write_text(
            frontmatter + text,
            encoding="utf-8",
        )

        url = f"records/{src.stem}.html"

        row = {
            "title": title,
            "file": src.name,
            "url": url,
            "summary": summary,
            "text": text,
        }

        if LAW_RE.match(src.name):
            n = int(LAW_RE.match(src.name).group(1))
            row["number"] = n
            laws.append(row)

        elif SEQ_RE.match(src.name):
            sequences.append(row)

        search_records.append(row)

    if len(laws) != 144:
        fail(f"expected 144 law pages; found {len(laws)}")

    if len(sequences) != 27:
        fail(
            "expected 27 sequence/final records; "
            f"found {len(sequences)}"
        )

    laws.sort(key=lambda x: x["number"])
    sequences.sort(key=lambda x: x["file"])

    # -----------------------------------------------------
    # Build canonical sequence membership directly from the
    # "Records in This Sequence" section of each source record.
    # No law-to-sequence assignments are inferred or hard-coded.
    # -----------------------------------------------------

    laws_by_number = {
        law["number"]: law
        for law in laws
    }

    membership = {
        number: []
        for number in laws_by_number
    }

    for seq in sequences:
        records_section = extract_section(
            seq["text"],
            "Records in This Sequence",
        )

        member_numbers = [
            int(value)
            for value in re.findall(
                r"\[\[LAW-RW-(\d{3})-[^|\]]+\|",
                records_section,
            )
        ]

        if not member_numbers:
            fail(
                f"{seq['file']}: no law records found in "
                "'Records in This Sequence'"
            )

        if len(member_numbers) != len(set(member_numbers)):
            fail(
                f"{seq['file']}: duplicate law membership"
            )

        for number in member_numbers:
            if number not in laws_by_number:
                fail(
                    f"{seq['file']}: references missing "
                    f"LAW-RW-{number:03d}"
                )

            membership[number].append(seq["file"])

        seq["member_numbers"] = member_numbers

        first = member_numbers[0]
        last = member_numbers[-1]

        if member_numbers == list(range(first, last + 1)):
            if first == last:
                seq["law_range"] = f"LAW-RW-{first:03d}"
            else:
                seq["law_range"] = (
                    f"LAW-RW-{first:03d}–{last:03d}"
                )
        else:
            seq["law_range"] = " · ".join(
                f"LAW-RW-{number:03d}"
                for number in member_numbers
            )

    missing_membership = [
        number
        for number, parents in membership.items()
        if not parents
    ]

    duplicate_membership = {
        number: parents
        for number, parents in membership.items()
        if len(parents) > 1
    }

    if missing_membership:
        fail(
            "laws missing sequence membership: "
            + ", ".join(
                f"LAW-RW-{number:03d}"
                for number in missing_membership
            )
        )

    if duplicate_membership:
        details = "; ".join(
            (
                f"LAW-RW-{number:03d}: "
                + ", ".join(parents)
            )
            for number, parents
            in duplicate_membership.items()
        )

        fail(
            "laws assigned to multiple sequence records: "
            + details
        )

    # -----------------------------------------------------
    # Homepage
    # -----------------------------------------------------

    index = [
        "---",
        "layout: default",
        "title: Covenant of Harmonic Return",
        "---",
        "",
        '<section class="hero">',
        '  <p class="eyebrow">Covenant of Harmonic Return</p>',
        "  <h1>Cosmic Laws Registry</h1>",
        (
            '  <p class="hero-copy">'
            "144 Cosmic Laws organized through the "
            "Cosmic Law Rewrite Sequences."
            "</p>"
        ),
        '  <div class="hero-actions">',
        (
            '    <a class="button button-primary" '
            'href="search.html">Search the Laws</a>'
        ),
        (
            '    <a class="button" '
            'href="laws.html">Browse All 144 Laws</a>'
        ),
        "  </div>",
        "</section>",
        "",
        '<section class="registry-stats" '
        'aria-label="Registry overview">',
        '  <div><strong>144</strong><span>Cosmic Laws</span></div>',
        (
            '  <div><strong>26</strong>'
            '<span>Rewrite Sequences</span></div>'
        ),
        (
            '  <div><strong>1</strong>'
            '<span>Final Completion Segment</span></div>'
        ),
        "</section>",
        "",
        '<section id="sequences" class="sequence-section">',
        '  <div class="section-heading">',
        "    <h2>Cosmic Law Rewrite Sequences</h2>",
        (
            "    <p>Enter the registry through its "
            "canonical sequence records.</p>"
        ),
        "  </div>",
        '  <div class="sequence-grid">',
    ]

    for seq in sequences:
        title_html = html.escape(seq["title"])
        url_html = html.escape(
            seq["url"],
            quote=True,
        )
        range_html = html.escape(seq["law_range"])
        count = len(seq["member_numbers"])

        card_class = "sequence-card"

        if "-FINAL-" in seq["file"]:
            card_class += " final-card"

        index.extend([
            (
                f'    <a class="{card_class}" '
                f'href="{url_html}">'
            ),
            f'      <h3>{title_html}</h3>',
            (
                f'      <p class="sequence-range">'
                f"{range_html} · "
                f"{count} "
                f"{'law' if count == 1 else 'laws'}"
                "</p>"
            ),
            (
                '      <span class="sequence-card-link">'
                "Open sequence →"
                "</span>"
            ),
            "    </a>",
        ])

    index.extend([
        "  </div>",
        "</section>",
        "",
        '<section class="homepage-paths">',
        "  <h2>Browse the Registry</h2>",
        '  <div class="path-grid">',
        '    <a class="path-card" href="laws.html">',
        "      <strong>144 Cosmic Laws</strong>",
        (
            "      <span>Open the complete numerical "
            "law index →</span>"
        ),
        "    </a>",
        '    <a class="path-card" href="search.html">',
        "      <strong>Search</strong>",
        (
            "      <span>Search titles, IDs, summaries, "
            "and decree text →</span>"
        ),
        "    </a>",
        "  </div>",
        "</section>",
        "",
        '<section class="integrity-panel">',
        "  <h2>Publication Integrity</h2>",
        (
            "  <p>This website is a deterministic derived "
            "presentation layer generated from "
            "<code>wiki/cosmic-laws/</code>.</p>"
        ),
        (
            "  <p>The public-site generator does not amend "
            "the Cosmic Law or sequence records. "
            "LLM use in publication: none.</p>"
        ),
        "</section>",
        "",
    ])

    (tmp / "index.md").write_text(
        "\n".join(index),
        encoding="utf-8",
    )

    # -----------------------------------------------------
    # Complete numerical law index
    # -----------------------------------------------------

    laws_page = [
        "---",
        "layout: default",
        "title: 144 Cosmic Laws",
        "permalink: /laws.html",
        "---",
        "",
        "# 144 Cosmic Laws",
        "",
        (
            "Complete numerical index of the "
            "Cosmic Laws Registry."
        ),
        "",
        '<div class="law-index-grid">',
    ]

    for law in laws:
        title_html = html.escape(law["title"])
        url_html = html.escape(
            law["url"],
            quote=True,
        )

        laws_page.extend([
            (
                f'  <a class="law-index-item" '
                f'href="{url_html}">'
            ),
            (
                f'    <span>LAW-RW-'
                f'{law["number"]:03d}</span>'
            ),
            f"    <strong>{title_html}</strong>",
            "  </a>",
        ])

    laws_page.extend([
        "</div>",
        "",
    ])

    (tmp / "laws.md").write_text(
        "\n".join(laws_page),
        encoding="utf-8",
    )

    config = """title: Covenant of Harmonic Return
description: Deterministic public publication of the Cosmic Laws registry
markdown: kramdown
permalink: pretty
exclude:
  - README.md
"""
    (tmp / "_config.yml").write_text(
        config,
        encoding="utf-8",
    )

    default_layout = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ page.title }} · {{ site.title }}</title>
  <link rel="stylesheet" href="{{ '/assets/style.css' | relative_url }}">
</head>
<body>
  <header class="site-header">
    <div class="shell">
      <a class="brand" href="{{ '/' | relative_url }}">Covenant of Harmonic Return</a>
      <nav>
        <a href="{{ '/' | relative_url }}">Home</a>
        <a href="{{ '/laws.html' | relative_url }}">144 Laws</a>
        <a href="{{ '/' | relative_url }}#sequences">Sequences</a>
        <a href="{{ '/search.html' | relative_url }}">Search</a>
      </nav>
    </div>
  </header>

  <main class="shell content">
    {{ content }}
  </main>

  <footer class="shell footer">
    Cosmic Laws Registry · Deterministic publication layer · Source records preserved in Git
  </footer>
</body>
</html>
"""
    (layouts_dir / "default.html").write_text(
        default_layout,
        encoding="utf-8",
    )

    record_layout = """---
layout: default
---
<div class="record-nav">
  <a href="{{ '/laws.html' | relative_url }}">← 144 Cosmic Laws</a>
  <a href="{{ '/search.html' | relative_url }}">Search</a>
</div>

<article class="record">
  {{ content }}
</article>

{% if page.record_kind == "law" %}
<nav class="law-pager" aria-label="Cosmic Law navigation">
  <div class="law-pager-prev">
    {% if page.prev_url %}
      <span>Previous Law</span>
      <a href="{{ page.prev_url | relative_url }}">
        ← {{ page.prev_title }}
      </a>
    {% endif %}
  </div>

  <div class="law-pager-next">
    {% if page.next_url %}
      <span>Next Law</span>
      <a href="{{ page.next_url | relative_url }}">
        {{ page.next_title }} →
      </a>
    {% endif %}
  </div>
</nav>
{% endif %}

<div class="record-source">
  Publication source: <code>wiki/cosmic-laws/{{ page.source_file }}</code>
</div>
"""
    (layouts_dir / "record.html").write_text(
        record_layout,
        encoding="utf-8",
    )

    search_page = """---
layout: default
title: Search
permalink: /search.html
---

# Search the Cosmic Laws

<input
  id="search-input"
  class="search-input"
  type="search"
  placeholder="Search law titles, IDs, summaries, or decree text..."
  autocomplete="off"
>

<div id="search-count" class="search-count"></div>
<div id="search-results"></div>

<script src="{{ '/assets/search.js' | relative_url }}"></script>
"""
    (tmp / "search.md").write_text(
        search_page,
        encoding="utf-8",
    )

    css = """
:root {
  color-scheme: light dark;
  --bg: #111;
  --panel: #191919;
  --text: #f3f3f3;
  --muted: #aaa;
  --line: #333;
  --accent: #ddd;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
}

.shell {
  width: min(1100px, calc(100% - 2rem));
  margin-inline: auto;
}

.site-header {
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}

.site-header .shell {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 64px;
  gap: 1rem;
}

.brand {
  font-weight: 700;
  text-decoration: none;
}

nav {
  display: flex;
  gap: 1rem;
}

a {
  color: var(--accent);
}

.content {
  padding-block: 2.5rem 5rem;
}

h1, h2, h3 {
  line-height: 1.2;
}

h2 {
  margin-top: 2.5rem;
  border-bottom: 1px solid var(--line);
  padding-bottom: .4rem;
}

table {
  border-collapse: collapse;
  width: 100%;
  overflow-x: auto;
  display: block;
}

th, td {
  border: 1px solid var(--line);
  padding: .5rem .7rem;
  vertical-align: top;
}

code {
  overflow-wrap: anywhere;
}

.record-nav,
.record-source,
.search-count {
  color: var(--muted);
  margin-bottom: 1.5rem;
}

.record-nav {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}

.law-pager {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2rem;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 1.5rem 0;
  margin-top: 3rem;
}

.law-pager span {
  display: block;
  color: var(--muted);
  font-size: .85rem;
  margin-bottom: .35rem;
}

.law-pager-next {
  text-align: right;
}

@media (max-width: 650px) {
  .law-pager {
    grid-template-columns: 1fr;
  }

  .law-pager-next {
    text-align: left;
  }
}

.record-source {
  border-top: 1px solid var(--line);
  margin-top: 3rem;
  padding-top: 1rem;
}

.search-input {
  width: 100%;
  font: inherit;
  padding: .9rem 1rem;
  margin: 1rem 0 1.5rem;
  border: 1px solid var(--line);
  border-radius: 6px;
}

.search-result {
  padding: 1rem 0;
  border-bottom: 1px solid var(--line);
}

.search-result h3 {
  margin: 0 0 .3rem;
}

.search-result p {
  color: var(--muted);
  margin: 0;
}


.hero {
  padding: 3rem 0 2.5rem;
  border-bottom: 1px solid var(--line);
}

.eyebrow {
  margin: 0 0 .5rem;
  color: var(--muted);
  font-size: .82rem;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
}

.hero h1 {
  margin: 0;
  font-size: clamp(2.2rem, 7vw, 4.8rem);
  max-width: 900px;
}

.hero-copy {
  color: var(--muted);
  font-size: 1.1rem;
  max-width: 700px;
  margin: 1.2rem 0 0;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: .8rem;
  margin-top: 1.75rem;
}

.button {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .75rem 1rem;
  text-decoration: none;
  font-weight: 650;
}

.button-primary {
  border-color: var(--accent);
}

.registry-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  margin: 2rem 0 4rem;
}

.registry-stats div {
  background: var(--panel);
  padding: 1.5rem;
}

.registry-stats strong {
  display: block;
  font-size: 2rem;
  line-height: 1;
}

.registry-stats span {
  display: block;
  color: var(--muted);
  margin-top: .45rem;
}

.section-heading {
  margin-bottom: 1.5rem;
}

.section-heading h2 {
  margin-bottom: .5rem;
}

.section-heading p {
  color: var(--muted);
  margin: 0;
}

.sequence-grid {
  display: grid;
  grid-template-columns: repeat(
    auto-fit,
    minmax(280px, 1fr)
  );
  gap: 1rem;
}

.sequence-card {
  display: block;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  padding: 1.25rem;
  text-decoration: none;
}

.sequence-card:hover,
.path-card:hover,
.law-index-item:hover {
  border-color: var(--accent);
}

.sequence-card h3 {
  margin: 0;
  font-size: 1.05rem;
}

.sequence-range {
  color: var(--muted);
  margin: .65rem 0 1rem;
  font-size: .9rem;
}

.sequence-card-link {
  font-weight: 650;
}

.final-card {
  border-width: 2px;
}

.homepage-paths,
.integrity-panel {
  margin-top: 4rem;
}

.path-grid {
  display: grid;
  grid-template-columns: repeat(
    auto-fit,
    minmax(260px, 1fr)
  );
  gap: 1rem;
}

.path-card {
  display: block;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  padding: 1.25rem;
  text-decoration: none;
}

.path-card strong,
.path-card span {
  display: block;
}

.path-card span {
  color: var(--muted);
  margin-top: .4rem;
}

.integrity-panel {
  border-top: 1px solid var(--line);
  padding-top: 1rem;
  color: var(--muted);
}

.law-index-grid {
  display: grid;
  grid-template-columns: repeat(
    auto-fit,
    minmax(300px, 1fr)
  );
  gap: .65rem;
  margin-top: 2rem;
}

.law-index-item {
  display: block;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: .9rem 1rem;
  text-decoration: none;
}

.law-index-item span {
  display: block;
  color: var(--muted);
  font-size: .8rem;
  letter-spacing: .04em;
  margin-bottom: .25rem;
}

.law-index-item strong {
  display: block;
}

@media (max-width: 700px) {
  .site-header .shell {
    align-items: flex-start;
    flex-direction: column;
    padding-block: .9rem;
  }

  .site-header nav {
    flex-wrap: wrap;
  }

  .registry-stats {
    grid-template-columns: 1fr;
  }

  .hero {
    padding-top: 1.5rem;
  }
}

.footer {
  color: var(--muted);
  border-top: 1px solid var(--line);
  padding-block: 1.5rem 3rem;
}
"""
    (assets_dir / "style.css").write_text(
        css.strip() + "\n",
        encoding="utf-8",
    )

    # Keep search deterministic and entirely client-side.
    search_json = []

    for row in search_records:
        search_json.append({
            "title": row["title"],
            "file": row["file"],
            "url": row["url"],
            "summary": row["summary"],
            "text": row["text"],
        })

    (tmp / "search-index.json").write_text(
        json.dumps(
            search_json,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    search_js = r"""
(async () => {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const count = document.getElementById("search-count");

  const response = await fetch("search-index.json");
  const records = await response.json();

  function normalize(value) {
    return String(value || "").toLowerCase();
  }

  function search(query) {
    const terms = normalize(query)
      .split(/\s+/)
      .filter(Boolean);

    if (!terms.length) {
      results.innerHTML = "";
      count.textContent = "";
      return;
    }

    const ranked = records
      .map(record => {
        const title = normalize(record.title);
        const file = normalize(record.file);
        const summary = normalize(record.summary);
        const text = normalize(record.text);

        let score = 0;

        for (const term of terms) {
          if (file.includes(term)) score += 100;
          if (title.includes(term)) score += 80;
          if (summary.includes(term)) score += 30;
          if (text.includes(term)) score += 5;
        }

        return { record, score };
      })
      .filter(item => item.score > 0)
      .sort((a, b) =>
        b.score - a.score ||
        a.record.title.localeCompare(b.record.title)
      )
      .slice(0, 30);

    count.textContent =
      `${ranked.length} result${ranked.length === 1 ? "" : "s"} shown`;

    results.innerHTML = ranked.map(({ record }) => `
      <div class="search-result">
        <h3><a href="${record.url}">${escapeHtml(record.title)}</a></h3>
        <p>${escapeHtml(record.summary || record.file)}</p>
      </div>
    `).join("");
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  input.addEventListener("input", () => {
    search(input.value);
  });
})();
"""
    (assets_dir / "search.js").write_text(
        search_js.strip() + "\n",
        encoding="utf-8",
    )

    (tmp / ".cosmic-laws-derived").write_text(
        "Generated from wiki/cosmic-laws. Do not edit by hand.\n",
        encoding="utf-8",
    )

    # Replace only a previously generated docs directory.
    if OUTPUT.exists():
        marker = OUTPUT / ".cosmic-laws-derived"

        if not marker.exists():
            fail(
                "docs/ already exists but is not marked as "
                "a generated Cosmic Laws site"
            )

        shutil.rmtree(OUTPUT)

    shutil.move(str(tmp), str(OUTPUT))

    print("===== PUBLIC SITE BUILD COMPLETE =====")
    print("Authoritative source pages: 172")
    print("Public law pages:           144")
    print("Sequence/final pages:        27")
    print("Search index:                YES")
    print("LLM used:                    NO")
    print("Canonical files modified:    NO")
    print(f"Output: {OUTPUT}")

except Exception:
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    raise
