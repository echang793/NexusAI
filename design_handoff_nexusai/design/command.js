// ⌘K command palette — jump to sections, tickers, accounts.
(() => {
  const D = window.NEXUS_DATA;
  let items = [];      // full searchable index
  let filtered = [];
  let sel = 0;

  function buildIndex() {
    const out = [];
    // Sections
    [
      ["overview", "Overview", "Net worth & accounts", "home"],
      ["analyze", "Analyze", "Single-stock deep dive", "chart"],
      ["portfolio", "Portfolio", "All 44 holdings", "wallet"],
      ["watchlist", "Watchlist", "Tracked tickers", "eye"],
      ["advisor", "Advisor", "Your AI plan + chat", "sparkles"],
    ].forEach(([id, title, sub, icon]) => out.push({
      kind: "section", label: title, sub, icon, key: title.toLowerCase(),
      run: () => Nexus.navigateTo(id),
    }));

    // Holdings tickers
    D.positions.forEach(p => out.push({
      kind: "ticker", label: p.ticker, sub: `${p.sector} · ${fmt$(p.value, { compact: true })} · ${fmtPct(p.plPct)}`,
      glyph: p.ticker.slice(0, 3), key: (p.ticker + " " + p.sector).toLowerCase(),
      run: () => Nexus.flashTicker(p.ticker),
    }));

    // Watchlist tickers not already in holdings
    D.watchlist.forEach(w => {
      if (D.positions.some(p => p.ticker === w.ticker)) return;
      out.push({
        kind: "ticker", label: w.ticker, sub: `Watchlist · ${w.note}`,
        glyph: w.ticker.slice(0, 3), key: (w.ticker + " " + w.note).toLowerCase(),
        run: () => Nexus.flashTicker(w.ticker),
      });
    });

    // Accounts
    D.accounts.forEach(a => out.push({
      kind: "account", label: a.name, sub: `${a.institution} · ${fmt$(a.balance, { compact: true })}`,
      icon: "bank", key: (a.name + " " + a.institution).toLowerCase(),
      run: () => Nexus.navigateTo("overview"),
    }));

    return out;
  }

  function render() {
    const wrap = document.getElementById("cmdk-results");
    if (!filtered.length) {
      wrap.innerHTML = `<div class="cmdk-empty">No matches</div>`;
      return;
    }
    // group by kind in stable order
    const groups = { section: "Sections", ticker: "Tickers", account: "Accounts" };
    let html = "";
    let flatIndex = 0;
    Object.keys(groups).forEach(kind => {
      const rows = filtered.filter(f => f.kind === kind);
      if (!rows.length) return;
      html += `<div class="cmdk-group">${groups[kind]}</div>`;
      rows.forEach(r => {
        const idx = filtered.indexOf(r);
        const left = r.glyph
          ? `<span class="cmdk-glyph">${r.glyph}</span>`
          : `<span class="cmdk-ico">${Icon(r.icon || "search", 16)}</span>`;
        html += `
          <div class="cmdk-item ${idx === sel ? "active" : ""}" data-idx="${idx}">
            ${left}
            <div class="cmdk-text">
              <div class="cmdk-label">${r.label}</div>
              <div class="cmdk-sub">${r.sub}</div>
            </div>
            <span class="cmdk-enter">${Icon("corner_down", 13)}</span>
          </div>`;
        flatIndex++;
      });
    });
    wrap.innerHTML = html;
    const activeEl = wrap.querySelector(".cmdk-item.active");
    if (activeEl) activeEl.scrollIntoViewIfNeeded?.() ?? activeEl.scrollIntoView?.({ block: "nearest" });
  }

  function filter(q) {
    q = q.trim().toLowerCase();
    if (!q) { filtered = items.slice(0, 8); }
    else {
      filtered = items
        .map(it => {
          const k = it.key;
          let score = -1;
          if (it.label.toLowerCase().startsWith(q)) score = 0;
          else if (k.startsWith(q)) score = 1;
          else if (k.includes(q)) score = 2;
          return { it, score };
        })
        .filter(x => x.score >= 0)
        .sort((a, b) => a.score - b.score)
        .map(x => x.it)
        .slice(0, 20);
    }
    sel = 0;
    render();
  }

  function open() {
    const ov = document.getElementById("cmdk");
    ov.hidden = false;
    requestAnimationFrame(() => ov.classList.add("show"));
    const input = document.getElementById("cmdk-input");
    input.value = "";
    filter("");
    setTimeout(() => input.focus(), 30);
  }
  function close() {
    const ov = document.getElementById("cmdk");
    ov.classList.remove("show");
    setTimeout(() => { ov.hidden = true; }, 180);
  }
  function isOpen() { return !document.getElementById("cmdk").hidden; }

  function choose(idx) {
    const it = filtered[idx];
    if (!it) return;
    close();
    setTimeout(() => it.run(), 60);
  }

  window.CommandPalette = {
    init() {
      items = buildIndex();
      document.getElementById("cmdk-icon").innerHTML = Icon("search", 16);

      document.getElementById("cmd-trigger").addEventListener("click", open);
      document.getElementById("cmd-trigger").addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
      });

      const input = document.getElementById("cmdk-input");
      input.addEventListener("input", () => filter(input.value));
      input.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, filtered.length - 1); render(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); render(); }
        else if (e.key === "Enter") { e.preventDefault(); choose(sel); }
        else if (e.key === "Escape") { e.preventDefault(); close(); }
      });

      const results = document.getElementById("cmdk-results");
      results.addEventListener("click", (e) => {
        const row = e.target.closest("[data-idx]");
        if (row) choose(+row.dataset.idx);
      });
      results.addEventListener("mousemove", (e) => {
        const row = e.target.closest("[data-idx]");
        if (row && +row.dataset.idx !== sel) { sel = +row.dataset.idx; render(); }
      });

      // Click backdrop to close
      document.getElementById("cmdk").addEventListener("click", (e) => {
        if (e.target.id === "cmdk") close();
      });

      // Global ⌘K / Ctrl+K
      window.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          isOpen() ? close() : open();
        }
      });
    },
    // allow rebuilding index after account add/remove
    rebuild() { items = buildIndex(); },
  };
})();
