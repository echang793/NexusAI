// NexusAI — "Update from screenshot". Drop or paste screenshots of a brokerage or
// account page; the server reads them with a local vision model (nothing leaves
// this machine), you review and edit what it read, see exactly what would change,
// and only then confirm. Opened by any element with [data-shot-open].
//
// Everything that comes back from the model or the server is escaped (esc())
// before it reaches innerHTML.

(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => (n == null || isNaN(n) ? "—" : "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const sh = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: 5 }));
  const INPUT = "padding:5px 7px;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:12px;box-sizing:border-box;";
  const toast = (m, k) => { if (window.NexusToast) NexusToast(m, k); };

  let S = null; // modal state; null when closed
  let previewTimer = null;
  let previewSeq = 0;

  // ------------------------------------------------------------------ state
  const targetValue = (t) => (!t || t.type === "skip" ? "skip" : t.type === "holdings" ? "h:" + t.bucket : "b:" + t.name);
  const targetOf = (v) => (v.startsWith("h:") ? { type: "holdings", bucket: v.slice(2) }
    : v.startsWith("b:") ? { type: "balance", name: v.slice(2) } : { type: "skip" });
  const itemsOf = () => S.accounts.map((a) => ({
    target: targetOf(a.target), mode: a.mode,
    account: { label: a.acct.label, institution: a.acct.institution, total_value: a.acct.total_value,
               positions_total: a.acct.positions_total, cash: a.acct.cash, positions: a.acct.positions },
  }));
  const anyChosen = () => S.accounts.some((a) => a.target !== "skip");

  function open() {
    if (S) return;
    S = { files: [], accounts: [], targets: { holdings: [], manual: [] }, plan: null, accept: false, applying: false, abort: new AbortController() };
    draw();
  }
  function close() {
    if (!S) return;
    S.abort.abort();
    clearTimeout(previewTimer);
    S = null;
    const m = document.getElementById("shot-modal");
    if (m) m.remove();
  }

  // ------------------------------------------------------------------ upload
  async function addFiles(list) {
    if (!S) return;
    const images = [...list].filter((f) => /^image\//.test(f.type));
    if (!images.length) { toast("Those weren't images", "err"); return; }
    const entries = images.map((f) => ({ file: f, name: f.name || "pasted screenshot", status: "queued", error: "" }));
    S.files.push(...entries);
    draw();
    for (const e of entries) {
      if (!S) return;
      e.status = "reading";
      e.t0 = Date.now();
      draw();
      try {
        const fd = new FormData();
        fd.append("file", e.file, e.name);
        const r = await fetch("/api/screenshot/parse", { method: "POST", body: fd, signal: S.abort.signal });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || !j.ok) throw new Error(j.error || "Could not read that screenshot");
        S.targets = j.targets;
        j.accounts.forEach((acct) => S.accounts.push({ acct, from: e.name, target: targetValue(acct.suggested), mode: "merge" }));
        e.status = "done";
      } catch (err) {
        if (!S) return;
        e.status = "failed";
        e.error = err.message;
      }
      if (!S) return;
      draw();
      schedulePreview();
    }
  }

  // ------------------------------------------------------------------ preview
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 300);
  }
  async function refreshPreview() {
    if (!S) return;
    if (!anyChosen()) { S.plan = null; paintPreview(); return; }
    const seq = ++previewSeq;
    try {
      const r = await fetch("/api/screenshot/preview", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: itemsOf() }), signal: S.abort.signal });
      const plan = await r.json();
      if (!S || seq !== previewSeq) return;
      S.plan = plan;
    } catch (e) {
      if (!S || seq !== previewSeq) return;
      S.plan = { ok: false, errors: ["Couldn't compute the preview: " + e.message], warnings: [], changes: [] };
    }
    paintPreview();
  }

  function renderChange(c) {
    if (c.kind === "balance") {
      return `<div class="card" style="padding:10px 12px;margin-bottom:8px;"><b>${esc(c.name)}</b>
        <span class="muted"> balance </span>${money(c.old)} → <b>${money(c.new)}</b></div>`;
    }
    const n = (s) => c.rows.filter((r) => r.status === s).length;
    const changed = c.rows.filter((r) => r.status !== "same");
    const recon = c.reconciled
      ? `<span style="color:var(--green)">✓ positions add up to the ${money(c.positions_total)} shown</span>`
      : c.positions_total != null
        ? `<span class="muted">positions ${money(c.computed_total)} vs ${money(c.positions_total)} shown${c.mode === "merge" ? " (fine if the list is partial)" : ""}</span>`
        : `<span class="muted">no total visible to check against</span>`;
    return `<div class="card" style="padding:10px 12px;margin-bottom:8px;">
      <div><b>${esc(c.label)}</b> <span class="muted">· ${esc(c.mode)}</span></div>
      <div style="font-size:12px;margin:4px 0;">${n("resized")} resized · ${n("added")} added · ${n("cost")} cost-only · ${c.removed.length} removed · ${c.rows.length - changed.length} unchanged</div>
      <div style="font-size:12px;margin-bottom:6px;">${recon}</div>
      ${c.cash ? `<div style="font-size:12px;margin-bottom:6px;">${esc(c.cash.name)} cash ${money(c.cash.old)} → <b>${money(c.cash.new)}</b></div>` : ""}
      ${(c.notes || []).map((t) => `<div class="muted" style="font-size:11px;">${esc(t)}</div>`).join("")}
      ${c.removed.length ? `<div style="font-size:12px;color:var(--red);margin-bottom:6px;">Removed: ${c.removed.map(esc).join(", ")}</div>` : ""}
      ${changed.length ? `<table class="tbl" style="font-size:12px;"><thead><tr><th>Ticker</th><th class="t-right">Shares</th><th class="t-right">Avg cost</th><th></th></tr></thead><tbody>
        ${changed.map((r) => `<tr><td>${esc(r.ticker)}</td>
          <td class="t-right">${r.old_shares == null ? "" : sh(r.old_shares) + " → "}<b>${sh(r.new_shares)}</b></td>
          <td class="t-right">${r.old_cost == null ? "" : money(r.old_cost) + " → "}${money(r.new_cost)}</td>
          <td class="muted">${r.cost_estimated ? "cost ≈ price (not shown)" : esc(r.status)}</td></tr>`).join("")}
        </tbody></table>` : ""}</div>`;
  }

  function paintPreview() {
    const el = document.getElementById("shot-preview");
    const btn = document.getElementById("shot-apply");
    if (!el || !S) return;
    const p = S.plan;
    if (!p) {
      el.innerHTML = `<div class="muted" style="font-size:12px;">${S.accounts.length ? "Choose where at least one screenshot's data should go." : "Add a screenshot to begin."}</div>`;
    } else {
      el.innerHTML =
        (p.errors.length ? `<div style="color:var(--red);font-size:12px;margin-bottom:8px;"><b>Can't apply yet</b><ul style="margin:4px 0 0 18px;padding:0;">${p.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : "") +
        (p.warnings.length ? `<div style="color:var(--orange,#ff9f0a);font-size:12px;margin-bottom:8px;"><b>Check these</b><ul style="margin:4px 0 0 18px;padding:0;">${p.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
          <label style="display:flex;gap:6px;align-items:center;margin-top:6px;color:var(--text);"><input type="checkbox" id="shot-accept" ${S.accept ? "checked" : ""}/> I checked these against the screenshot</label></div>` : "") +
        p.changes.map(renderChange).join("");
    }
    if (btn) btn.disabled = !(p && p.ok && (!p.warnings.length || S.accept)) || S.applying;
  }

  // ------------------------------------------------------------------ apply
  async function apply() {
    if (!S || S.applying) return;
    S.applying = true;
    paintPreview();
    try {
      const r = await fetch("/api/screenshot/apply", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: itemsOf(), accept_warnings: S.accept }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        S.plan = { ok: false, errors: j.errors || [j.error || "Apply failed"], warnings: j.warnings || [], changes: [] };
        S.applying = false;
        paintPreview();
        return;
      }
      close();
      toast("Updated — refreshing prices and totals", "ok");
      const reload = () => fetch("/api/snapshot").then((x) => x.json()).then((snap) => {
        if (snap.ok && window.Nexus && Nexus.applySnapshotData) Nexus.applySnapshotData(snap);
      }).catch(() => {});
      reload();
      setTimeout(reload, 3000);
    } catch (e) {
      S.applying = false;
      S.plan = { ok: false, errors: ["Apply failed: " + e.message], warnings: [], changes: [] };
      paintPreview();
    }
  }

  // ------------------------------------------------------------------ drawing
  function targetOptions(selected) {
    const o = (v, label) => `<option value="${esc(v)}" ${v === selected ? "selected" : ""}>${esc(label)}</option>`;
    return o("skip", "Skip this one") +
      S.targets.holdings.map((t) => o("h:" + t.bucket, t.label + " — holdings")).join("") +
      S.targets.manual.map((n) => o("b:" + n, n + " — balance")).join("");
  }

  function renderAccount(a, i) {
    const acct = a.acct;
    const isHold = a.target.startsWith("h:");
    const isBal = a.target.startsWith("b:");
    const head = `<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
      <div style="flex:1;min-width:160px;"><b>${esc(acct.label || acct.institution || "Account")}</b>
        <div class="muted" style="font-size:11px;">${esc(acct.institution || "")} ${acct.institution ? "· " : ""}from ${esc(a.from)}</div></div>
      <label style="font-size:12px;">Send to
        <select data-i="${i}" data-k="target" style="${INPUT}margin-left:4px;">${targetOptions(a.target)}</select></label></div>`;
    const problems = acct.problems && acct.problems.length
      ? `<div class="muted" style="font-size:11px;margin-bottom:6px;">Couldn't read ${acct.problems.length} row(s): ${acct.problems.slice(0, 3).map(esc).join("; ")}</div>` : "";
    let body = "";
    if (isBal) {
      body = `<label style="font-size:12px;">Balance <input data-i="${i}" data-k="total_value" value="${esc(acct.total_value ?? "")}" style="${INPUT}width:140px;"/></label>`;
    } else if (isHold) {
      body = `<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin-bottom:8px;">
        <label>Total of positions shown <input data-i="${i}" data-k="positions_total" value="${esc(acct.positions_total ?? "")}" style="${INPUT}width:120px;"/></label>
        <label>Cash <input data-i="${i}" data-k="cash" value="${esc(acct.cash ?? "")}" style="${INPUT}width:90px;"/></label>
        <label>Mode <select data-i="${i}" data-k="mode" style="${INPUT}">
          <option value="merge" ${a.mode === "merge" ? "selected" : ""}>Merge: update and add only</option>
          <option value="replace" ${a.mode === "replace" ? "selected" : ""}>Replace: remove positions not shown</option></select></label></div>
        <div style="max-height:260px;overflow:auto;"><table class="tbl" style="font-size:12px;"><thead><tr>
          <th>Ticker</th><th class="t-right">Shares</th><th class="t-right">Price</th><th class="t-right">Value</th><th class="t-right">Avg cost</th><th></th></tr></thead><tbody>
          ${acct.positions.map((p, r) => `<tr><td>${esc(p.symbol)}</td>
            ${["quantity", "price", "value", "avg_cost"].map((f) =>
              `<td class="t-right"><input data-i="${i}" data-r="${r}" data-k="${f}" value="${esc(p[f] ?? "")}" style="${INPUT}width:92px;text-align:right;"/></td>`).join("")}
            <td><button class="btn-ghost" data-rm="${i}:${r}" title="Don't use this row" style="padding:2px 6px;">✕</button></td></tr>`).join("")}
          </tbody></table></div>`;
    } else {
      body = `<div class="muted" style="font-size:12px;">This screenshot won't be used.</div>`;
    }
    return `<div class="card" style="padding:12px;margin-bottom:10px;">${head}${problems}${body}</div>`;
  }

  function draw() {
    if (!S) return;
    let m = document.getElementById("shot-modal");
    if (!m) {
      m = document.createElement("div");
      m.id = "shot-modal";
      m.style.cssText = "position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.45);display:flex;align-items:flex-start;justify-content:center;padding:4vh 12px;overflow:auto;";
      document.body.appendChild(m);
    }
    const files = S.files.map((f) => `<div style="font-size:12px;display:flex;gap:8px;"><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(f.name)}</span>
      <span style="color:${f.status === "failed" ? "var(--red)" : f.status === "done" ? "var(--green)" : "var(--text-2)"}">${
        f.status === "reading" ? "reading… (can take a minute)" : f.status === "failed" ? esc(f.error) : esc(f.status)}</span></div>`).join("");
    m.innerHTML = `<div class="card" style="width:min(860px,100%);padding:16px;background:var(--surface);">
      <div style="display:flex;align-items:center;margin-bottom:8px;"><h3 style="margin:0;flex:1;">Update from screenshot</h3>
        <button class="btn-ghost" id="shot-close" title="Close">✕</button></div>
      <div class="muted" style="font-size:12px;line-height:1.5;margin-bottom:10px;">Read locally by your Ollama vision model; nothing is sent anywhere and screenshots aren't saved.
        Nothing changes until you review and press Apply, and a backup is taken first. Add several screenshots of one account if its list scrolls.</div>
      <div id="shot-drop" style="border:1.5px dashed var(--border);border-radius:10px;padding:16px;text-align:center;cursor:pointer;margin-bottom:10px;">
        <div style="font-size:13px;">Drop screenshots here, click to choose, or paste (⌘V)</div>
        <input type="file" id="shot-file" accept="image/png,image/jpeg,image/webp" multiple hidden/></div>
      ${files ? `<div style="margin-bottom:10px;">${files}</div>` : ""}
      ${S.accounts.map(renderAccount).join("")}
      <h4 style="margin:12px 0 6px;">What will change</h4>
      <div id="shot-preview"></div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px;">
        <button class="btn-ghost" id="shot-cancel">Cancel</button>
        <button class="btn-primary" id="shot-apply" disabled>Apply changes</button></div></div>`;
    paintPreview();
  }

  // ------------------------------------------------------------------ events
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-shot-open]")) { open(); return; }
    if (!S) return;
    if (e.target.closest("#shot-close, #shot-cancel")) { close(); return; }
    if (e.target.closest("#shot-drop")) { document.getElementById("shot-file").click(); return; }
    if (e.target.closest("#shot-apply")) { apply(); return; }
    const rm = e.target.closest("[data-rm]");
    if (rm) {
      const [i, r] = rm.dataset.rm.split(":").map(Number);
      S.accounts[i].acct.positions.splice(r, 1);
      draw();
      schedulePreview();
    }
  });
  document.addEventListener("change", (e) => {
    if (!S) return;
    const t = e.target;
    if (t.id === "shot-file") { addFiles(t.files); t.value = ""; return; }
    if (t.id === "shot-accept") { S.accept = t.checked; paintPreview(); return; }
    if (t.dataset.i != null && (t.dataset.k === "target" || t.dataset.k === "mode")) {
      S.accounts[+t.dataset.i][t.dataset.k] = t.value;
      S.accept = false;
      draw();
      schedulePreview();
    }
  });
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (!S || t.dataset.i == null || ["target", "mode"].includes(t.dataset.k)) return;
    const acct = S.accounts[+t.dataset.i].acct;
    const v = t.value.trim() === "" ? null : t.value;
    if (t.dataset.r != null) acct.positions[+t.dataset.r][t.dataset.k] = v;
    else acct[t.dataset.k] = v;
    S.accept = false;
    schedulePreview();
  });
  document.addEventListener("dragover", (e) => { if (S && e.target.closest("#shot-drop")) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    if (S && e.target.closest("#shot-drop")) { e.preventDefault(); addFiles(e.dataTransfer.files); }
  });
  document.addEventListener("paste", (e) => {
    if (S && e.clipboardData && e.clipboardData.files.length) { e.preventDefault(); addFiles(e.clipboardData.files); }
  });
  document.addEventListener("keydown", (e) => {
    if (S && e.key === "Escape" && !S.accounts.length) close();
  });

  window.NexusScreenshot = { open, close };
})();
