(() => {
  const data = window.SPEECH_PREVIEW_DATA;
  if (!data || !Array.isArray(data.words)) {
    document.body.innerHTML = '<div class="error-state"><h1>Preview data missing</h1><p>Run <code>python3 build_preview_data.py</code> and reload.</p></div>';
    return;
  }

  const state = { wordIndex: 0, view: "learner" };
  const wordNav = document.querySelector("#word-nav");
  const wordHeader = document.querySelector("#word-header");
  const methodNote = document.querySelector("#method-note");
  const senseList = document.querySelector("#sense-list");
  const otherSenses = document.querySelector("#other-senses");
  const wordPosition = document.querySelector("#word-position");

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const labelForProminence = (value) =>
    ({ dominant: "Dominant", common: "Common", occasional: "Occasional" })[value] || "Unseen";

  const labelForReview = (value) =>
    ({
      unaudited: "Unaudited corpus candidate",
      needs_review: "Flagged for review",
      known_mismatch: "Known wrong attachment",
    })[value] || value;

  function renderNav() {
    wordNav.innerHTML = data.words
      .map(
        (word, index) => `
          <button class="word-tab ${index === state.wordIndex ? "is-active" : ""}" type="button" data-word-index="${index}" aria-current="${index === state.wordIndex ? "true" : "false"}">
            <span class="word-tab-name">${escapeHtml(word.surface)}</span>
            <span class="word-tab-state ${escapeHtml(word.note.verdict)}" title="${escapeHtml(word.note.headline)}"></span>
          </button>`,
      )
      .join("");
  }

  function renderHeader(word) {
    wordHeader.innerHTML = `
      <header class="word-heading">
        <div>
          <div class="word-kicker"><span class="pos-chip">${escapeHtml(word.pos.toLowerCase())}</span> important senses first</div>
          <h1 class="word-title">${escapeHtml(word.surface)}</h1>
        </div>
        <a class="dictionary-link" href="${escapeHtml(word.spanishDictUrl)}" target="_blank" rel="noreferrer">Open SpanishDict <span aria-hidden="true">↗</span></a>
      </header>`;
  }

  function renderMethod(word) {
    const percentage = Math.round(word.coverage * 100);
    methodNote.innerHTML = `
      <section class="method-card ${escapeHtml(word.note.verdict)}">
        <div>
          <h2>${escapeHtml(word.note.headline)}</h2>
          <p>${escapeHtml(word.note.detail)}</p>
        </div>
        <div class="coverage" title="High-confidence unique assignments divided by all sampled occurrences">
          <strong>${percentage}%</strong>
          <span>usable sample</span>
        </div>
      </section>`;
  }

  function renderCanonical(example) {
    if (!example) {
      return '<div class="example-block"><p class="english-example">No canonical example is available.</p></div>';
    }
    return `
      <div class="example-block">
        <div class="example-label"><span>SpanishDict example</span><span class="verified-mark">authoritative attachment ✓</span></div>
        <p class="spanish-example" lang="es">${escapeHtml(example.spanish)}</p>
        <p class="english-example">${escapeHtml(example.english)}</p>
      </div>`;
  }

  function renderCandidate(candidate) {
    const review = candidate.review || { status: "unaudited" };
    return `
      <article class="candidate ${escapeHtml(review.status)}">
        <div class="candidate-status">
          <span>${escapeHtml(labelForReview(review.status))}</span>
          <span>line ${escapeHtml(candidate.source.corpusLine)}</span>
        </div>
        <p lang="es">${escapeHtml(candidate.spanish)}</p>
        <p class="translation">${escapeHtml(candidate.english)}</p>
        ${review.note ? `<p class="review-note">${escapeHtml(review.note)}</p>` : ""}
      </article>`;
  }

  function renderSense(sense, rank, word) {
    const candidates = sense.corpusCandidates.length
      ? `<div class="candidate-list">${sense.corpusCandidates.map(renderCandidate).join("")}</div>`
      : '<p class="no-candidates">No high-confidence corpus candidate survived for this sense.</p>';
    const context = sense.context ? ` <span class="sense-context">· ${escapeHtml(sense.context)}</span>` : "";
    return `
      <article class="sense-card">
        <div class="sense-main">
          <div class="sense-topline">
            <span class="rank">${rank}</span>
            <h2 class="sense-name">${escapeHtml(sense.translation)}${context}</h2>
            <span class="prominence ${escapeHtml(sense.prominence)}">${escapeHtml(labelForProminence(sense.prominence))}</span>
          </div>
          ${renderCanonical(sense.canonicalExample)}
        </div>
        <div class="evidence-strip">
          <div class="evidence-facts">
            <span class="fact">SD sense ${escapeHtml(sense.id)}</span>
            <span class="fact">${sense.acceptedCount}/${word.sampled} sampled</span>
            <span class="fact">${Math.round(sense.shareOfSample * 100)}% raw share</span>
            <span class="fact">model gate: unique + high</span>
          </div>
          ${candidates}
        </div>
      </article>`;
  }

  function renderOtherSenses(word) {
    if (!word.otherSenses.length) {
      otherSenses.innerHTML = "";
      return;
    }
    const rows = word.otherSenses
      .map((sense) => {
        const regions = sense.regions.length ? ` · ${sense.regions.join(", ")}` : "";
        const example = sense.canonicalExample;
        return `
          <article class="other-sense">
            <div>
              <h3>${escapeHtml(sense.translation)} <span class="sense-id">SD ${escapeHtml(sense.id)}</span></h3>
              <p>${escapeHtml(sense.context || "dictionary sense")}${escapeHtml(regions)}</p>
            </div>
            <div>
              <p lang="es">${escapeHtml(example?.spanish || "No SpanishDict example")}</p>
              <p>${escapeHtml(example?.english || "")}</p>
            </div>
          </article>`;
      })
      .join("");
    const summaryLabel = state.view === "evidence"
      ? `${word.otherSenses.length} other SpanishDict ${word.otherSenses.length === 1 ? "sense" : "senses"} — not evidenced in this small sample`
      : `More dictionary senses (${word.otherSenses.length})`;
    otherSenses.innerHTML = `
      <details class="other-senses">
        <summary>${summaryLabel}</summary>
        <div class="other-list">${rows}</div>
      </details>`;
  }

  function render() {
    const word = data.words[state.wordIndex];
    document.body.dataset.view = state.view;
    renderNav();
    renderHeader(word);
    renderMethod(word);
    senseList.innerHTML = word.importantSenses.map((sense, index) => renderSense(sense, index + 1, word)).join("");
    renderOtherSenses(word);
    wordPosition.textContent = `${state.wordIndex + 1} / ${data.words.length}`;
    document.querySelectorAll(".view-button").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === state.view);
      button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
    });
  }

  function chooseWord(index) {
    state.wordIndex = (index + data.words.length) % data.words.length;
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  wordNav.addEventListener("click", (event) => {
    const button = event.target.closest("[data-word-index]");
    if (button) chooseWord(Number(button.dataset.wordIndex));
  });
  document.querySelector("#previous-word").addEventListener("click", () => chooseWord(state.wordIndex - 1));
  document.querySelector("#next-word").addEventListener("click", () => chooseWord(state.wordIndex + 1));
  document.querySelectorAll(".view-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      render();
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") chooseWord(state.wordIndex + 1);
    if (event.key === "ArrowLeft") chooseWord(state.wordIndex - 1);
  });

  render();
})();
