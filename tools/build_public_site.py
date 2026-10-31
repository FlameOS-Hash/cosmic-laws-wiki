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

        frontmatter = (
            "---\n"
            "layout: record\n"
            f"title: {yaml_quote(title)}\n"
            f"source_file: {yaml_quote(src.name)}\n"
            f"permalink: /records/{src.stem}.html\n"
            "---\n\n"
        )

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

    index = [
        "---",
        "layout: default",
        "title: Cosmic Laws Wiki",
        "---",
        "",
        "# Cosmic Laws Wiki",
        "",
        "Deterministic public publication of the Cosmic Laws registry.",
        "",
        "[Search the Cosmic Laws](search.html)",
        "",
        "## 144 Cosmic Laws",
        "",
    ]

    for law in laws:
        index.append(
            f"- **LAW-RW-{law['number']:03d}** — "
            f"[{law['title']}]({law['url']})"
        )

    index.extend([
        "",
        "## Cosmic Law Rewrite Sequences",
        "",
    ])

    for seq in sequences:
        index.append(
            f"- [{seq['title']}]({seq['url']})"
        )

    index.extend([
        "",
        "## Integrity",
        "",
        "This site is a derived presentation layer.",
        "",
        "Authoritative publication source:",
        "`wiki/cosmic-laws/`",
        "",
        "The public-site generator does not amend the law records.",
        "",
    ])

    (tmp / "index.md").write_text(
        "\n".join(index),
        encoding="utf-8",
    )

    config = """title: Cosmic Laws Wiki
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
      <a class="brand" href="{{ '/' | relative_url }}">Cosmic Laws Wiki</a>
      <nav>
        <a href="{{ '/' | relative_url }}">Index</a>
        <a href="{{ '/search.html' | relative_url }}">Search</a>
      </nav>
    </div>
  </header>

  <main class="shell content">
    {{ content }}
  </main>

  <footer class="shell footer">
    Deterministic publication layer · Source records preserved in Git
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
  <a href="{{ '/' | relative_url }}">← All Cosmic Laws</a>
</div>

<article class="record">
  {{ content }}
</article>

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
