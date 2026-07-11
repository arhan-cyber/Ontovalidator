(() => {
  const rawText = document.getElementById("rawText");
  const triplesRows = document.getElementById("triplesRows");
  const addRowBtn = document.getElementById("addRow");
  const settingsToggle = document.getElementById("settingsToggle");
  const settingsPanel = document.getElementById("settingsPanel");
  const embeddingModel = document.getElementById("embeddingModel");
  const svoExtractor = document.getElementById("svoExtractor");
  const topK = document.getElementById("topK");
  const form = document.getElementById("validateForm");
  const submitBtn = document.getElementById("submitBtn");
  const loadingIndicator = document.getElementById("loadingIndicator");
  const results = document.getElementById("results");
  const summaryEl = document.getElementById("summary");
  const verdictsEl = document.getElementById("verdicts");
  const errorBanner = document.getElementById("errorBanner");
  const errorText = document.getElementById("errorText");
  const errorDismiss = document.getElementById("errorDismiss");

  let isSubmitting = false;

  function makeRow() {
    const row = document.createElement("div");
    row.className = "triple-row";
    row.innerHTML = `
      <input type="text" class="t-subject" placeholder="subject" />
      <input type="text" class="t-relation" placeholder="relation" />
      <input type="text" class="t-object" placeholder="object" />
      <button type="button" class="btn danger removeRow">✕</button>
    `;
    row.querySelector(".removeRow").addEventListener("click", () => {
      if (triplesRows.children.length > 1) {
        row.remove();
      } else {
        row.querySelectorAll("input").forEach((i) => (i.value = ""));
      }
    });
    return row;
  }

  addRowBtn.addEventListener("click", () => {
    triplesRows.appendChild(makeRow());
  });

  triplesRows.appendChild(makeRow());

  settingsToggle.addEventListener("click", () => {
    const hidden = settingsPanel.hasAttribute("hidden");
    if (hidden) {
      settingsPanel.removeAttribute("hidden");
    } else {
      settingsPanel.setAttribute("hidden", "");
    }
    settingsToggle.setAttribute("aria-expanded", String(hidden));
  });

  errorDismiss.addEventListener("click", () => {
    errorBanner.setAttribute("hidden", "");
  });

  function showError(message) {
    errorText.textContent = message;
    errorBanner.removeAttribute("hidden");
  }

  function hideError() {
    errorBanner.setAttribute("hidden", "");
  }

  async function loadConfig() {
    try {
      const res = await fetch("/config");
      if (!res.ok) return;
      const cfg = await res.json();
      populateSelect(embeddingModel, cfg.available_embedding_models, cfg.embedding_model_name);
      populateSelect(svoExtractor, cfg.available_svo_extractors, cfg.svo_extractor_name);
    } catch (e) {
      // Non-fatal: dropdowns just stay empty if /config is unreachable.
    }
  }

  function populateSelect(select, options, defaultValue) {
    select.innerHTML = "";
    (options || []).forEach((opt) => {
      const el = document.createElement("option");
      el.value = opt;
      el.textContent = opt;
      if (opt === defaultValue) el.selected = true;
      select.appendChild(el);
    });
  }

  function collectTriples() {
    const rows = [...triplesRows.querySelectorAll(".triple-row")];
    const triples = [];
    for (const row of rows) {
      const subject = row.querySelector(".t-subject").value.trim();
      const relation = row.querySelector(".t-relation").value.trim();
      const object = row.querySelector(".t-object").value.trim();
      if (!subject && !relation && !object) continue; // skip fully-empty rows
      if (!subject || !relation || !object) {
        throw new Error("Each triple row needs a subject, relation, and object.");
      }
      triples.push({ subject, relation, object });
    }
    return triples;
  }

  function setLoading(loading) {
    isSubmitting = loading;
    submitBtn.disabled = loading;
    loadingIndicator.hidden = !loading;
  }

  function labelClass(label) {
    return `label-${(label || "unknown").toLowerCase()}`;
  }

  function renderResults(data) {
    const s = data.summary;
    summaryEl.innerHTML = `
      <span>Total <strong>${s.total_triples}</strong></span>
      <span>Supported <strong>${s.supported}</strong></span>
      <span>Contradicted <strong>${s.contradicted}</strong></span>
      <span>Partial <strong>${s.partial}</strong></span>
      <span>Unknown <strong>${s.unknown}</strong></span>
      <span>Avg score <strong>${s.avg_score.toFixed(2)}</strong></span>
    `;

    verdictsEl.innerHTML = "";
    for (const v of data.verdicts) {
      const card = document.createElement("div");
      card.className = "verdict-card";
      const evidenceItems = (v.evidence || [])
        .map(
          (e) => `
          <div class="evidence-item">
            [${e.chunk_id}] (${e.source}, conf ${e.confidence.toFixed(2)}, ${e.match_type})
            subj:${e.matched.subject} rel:${e.matched.relation} obj:${e.matched.object}<br/>
            ${escapeHtml(e.text)}
          </div>`
        )
        .join("");

      card.innerHTML = `
        <div class="verdict-title">
          <span class="label-dot ${labelClass(v.label)}"></span>
          <span>${escapeHtml(v.subject)} — ${escapeHtml(v.relation)} — ${escapeHtml(v.object)}</span>
          <span class="score">score ${v.score.toFixed(2)}</span>
        </div>
        <div class="rationale">${escapeHtml(v.rationale || "")}</div>
        <details>
          <summary>Evidence (${(v.evidence || []).length} chunks)</summary>
          ${evidenceItems || '<div class="evidence-item">No evidence.</div>'}
        </details>
      `;
      verdictsEl.appendChild(card);
    }

    results.hidden = false;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  }

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    if (isSubmitting) return;
    hideError();

    let triples;
    try {
      triples = collectTriples();
    } catch (e) {
      showError(e.message);
      return;
    }

    if (!rawText.value.trim()) {
      showError("Document text must not be empty.");
      return;
    }
    if (triples.length === 0) {
      showError("At least one triple is required.");
      return;
    }

    const payload = {
      raw_text: rawText.value,
      triples,
      top_k: Number(topK.value) || 5,
      embedding_model: embeddingModel.value || null,
      svo_extractor: svoExtractor.value || null,
    };

    setLoading(true);
    try {
      const res = await fetch("/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) {
        const err = body.error;
        const message =
          typeof err === "string"
            ? err
            : err?.detail
            ? `${err.error || "Error"}: ${JSON.stringify(err.detail)}`
            : JSON.stringify(err);
        showError(message);
        return;
      }
      renderResults(body);
    } catch (e) {
      showError("Network error: " + e.message);
    } finally {
      setLoading(false);
    }
  });

  loadConfig();
})();
