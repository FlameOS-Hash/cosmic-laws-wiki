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
