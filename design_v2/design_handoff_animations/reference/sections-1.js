// NexusAI Apple-like — section renderers
// Reads global window.NEXUS_DATA. Uses Icon(), renderAreaChart(), etc.

(() => {
  const D = window.NEXUS_DATA;

  // ============================================================
  // OVERVIEW (Net Worth + Accounts)
  // ============================================================
  function renderOverview() {
    const hist = D.netWorthHistory;
    const start = hist[0].value;
    const now = hist[hist.length - 1].value;
    const delta = now - start;
    const deltaPct = (delta / start) * 100;
    const ytdStart = hist.find(h => h.date.getFullYear() === 2026)?.value || hist[Math.floor(hist.length / 2)].value;
    const ytdPct = ((now - ytdStart) / ytdStart) * 100;

    // top movers
    const movers = [...D.positions].sort((a, b) => b.plPct - a.plPct);
    const topGainers = movers.slice(0, 3);
    const topLosers = movers.slice(-3).reverse();

    return `
      <div class="grid g-overview">
        <!-- LEFT: Net Worth hero -->
        <div class="card hero">
          <div class="hero-label">Net Worth · All accounts</div>
          <div class="hero-number">
            <div class="hero-value">$${Math.floor(now).toLocaleString()}</div>
            <div class="hero-cents">.${String(Math.round((now % 1) * 100)).padStart(2, "0")}</div>
          </div>
          <div class="hero-controls">
            <div class="hero-delta">
              <span class="delta up">${Icon("trending_up", 12)} ${fmt$(delta, { signed: true, compact: true })} all-time</span>
              <span class="hero-since">YTD <span style="color:var(--green); font-weight:600">+${ytdPct.toFixed(1)}%</span></span>
            </div>
            <div class="range-pills" id="ow-range">
              ${["1M","3M","6M","YTD","1Y","2Y","ALL"].map((r,i) => `<button class="${i===6?'active':''}" data-r="${r}">${r}</button>`).join("")}
            </div>
          </div>
          <div class="chart-wrap" id="ow-chart"></div>
        </div>

        <!-- RIGHT: Allocation donut -->
        <div class="card card-pad">
          <div class="flex-between mb-m">
            <div>
              <div style="font-size:15px; font-weight:600;">Allocation</div>
              <div class="muted" style="font-size:12px; margin-top:2px;">By account type</div>
            </div>
          </div>
          <div style="display:flex; justify-content:center;">
            <div id="ow-donut" style="width:200px;"></div>
          </div>
          <div class="mt-m" id="ow-donut-legend"></div>
        </div>
      </div>

      <!-- Accounts -->
      <div class="grid g-2 mt-m">
        <div class="card">
          <div class="card-head"><h3>Accounts</h3>
            <button class="btn-ghost" id="ow-add-account">${Icon("plus", 12)} Add account</button>
          </div>
          <div class="card-body" id="ow-accounts"></div>
        </div>

        <div class="card">
          <div class="card-head"><h3>Movers</h3>
            <div class="meta">Top 3 each</div>
          </div>
          <div class="card-body">
            <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; margin-bottom:8px;">Gainers</div>
            ${topGainers.map(p => moverRow(p)).join("")}
            <div class="divider"></div>
            <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; margin-bottom:8px;">Losers</div>
            ${topLosers.map(p => moverRow(p)).join("")}
          </div>
        </div>
      </div>

      <!-- Sector breakdown -->
      <div class="card mt-m">
        <div class="card-head"><h3>Sector breakdown</h3>
          <div class="meta">${D.sectorWeights.length} sectors</div>
        </div>
        <div class="card-body">
          ${D.sectorWeights.slice(0, 8).map(s => `
            <div class="bar-row">
              <span>${s.sector}</span>
              <div class="bar-track"><div class="bar-fill" style="width:0%; background:${sectorColor(s.sector)};" data-w="${s.weight}"></div></div>
              <span class="t-right h-strong">${s.weight.toFixed(1)}%</span>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  function moverRow(p) {
    const sign = p.plPct >= 0 ? "up" : "down";
    return `
      <div style="display:grid; grid-template-columns:auto 1fr auto auto; gap:12px; align-items:center; padding:8px 0;">
        <div class="tkr-glyph">${p.ticker.slice(0, 3)}</div>
        <div>
          <div style="font-weight:600; font-size:13px;">${p.ticker}</div>
          <div class="muted" style="font-size:11px;">${p.sector}</div>
        </div>
        <div>${renderSparkline(syntheticSpark(p.plPct), { w: 60, h: 18 })}</div>
        <div class="delta ${sign}">${fmtPct(p.plPct)}</div>
      </div>
    `;
  }

  function syntheticSpark(plPct) {
    const out = [];
    let v = 100;
    for (let i = 0; i < 18; i++) {
      v += (plPct / 18) + (Math.sin(i * 0.6) * 1.5);
      out.push(v);
    }
    return out;
  }

  function sectorColor(name) {
    const colors = {
      "Technology": "#0a84ff",
      "ETF · S&P 500": "#30d158",
      "ETF · Growth": "#5e9eff",
      "ETF · Total Market": "#5ad97e",
      "Communications": "#b14aff",
      "Consumer Cyc.": "#ff9f0a",
      "Consumer Def.": "#ffd60a",
      "Financials": "#00c8a4",
      "Healthcare": "#ff5b9c",
      "Energy": "#ff453a",
      "ETF · Nasdaq": "#0a84ff",
      "ETF · Leveraged": "#ff375f",
      "ETF · International": "#5ac8fa",
      "Commodities": "#bf9d4e",
      "Crypto ETF": "#f7931a",
      "Cash/T-Bills": "#8e8e93",
      "Mutual Fund": "#6e6e73",
      "Industrials": "#a1a1a6",
    };
    return colors[name] || "#8e8e93";
  }

  function hydrateOverview() {
    const hist = D.netWorthHistory;
    // animate bars
    requestAnimationFrame(() => {
      document.querySelectorAll("[data-w]").forEach(el => {
        el.style.width = el.dataset.w + "%";
      });
    });

    // chart (default ALL)
    let currentRange = "ALL";
    const drawChart = () => {
      const slice = sliceByRange(hist, currentRange);
      const series = slice.map(h => ({ x: h.date, y: h.value }));
      renderAreaChart(document.getElementById("ow-chart"), series, {
        fmtY: (v) => "$" + (v / 1000).toFixed(0) + "K",
        fmtX: (d) => d.toLocaleDateString("en-US", { month: "short", year: "2-digit" }),
        fmtTip: (v) => fmt$(v, { dec: 0, compact: false }),
        color: "var(--accent)",
      });
    };
    drawChart();
    window.AppleSections._redraw = drawChart;
    const rangeEl = document.getElementById("ow-range");
    if (rangeEl && !rangeEl.dataset.bound) {
      rangeEl.dataset.bound = "1";
      rangeEl.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-r]");
      if (!btn) return;
      document.querySelectorAll("#ow-range button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentRange = btn.dataset.r;
      drawChart();
    });
    }

    // Donut
    refreshDonut();

    // Accounts list (editable balances + add/remove)
    renderAccounts();
    const addBtn = document.getElementById("ow-add-account");
    if (addBtn && !addBtn.dataset.bound) {
      addBtn.dataset.bound = "1";
      addBtn.addEventListener("click", showAddAccountForm);
    }
  }

  const ACCT_COLORS = { Taxable:"#0a84ff", Retirement:"#30d158", Cash:"#ff9f0a", Crypto:"#b14aff" };

  function accountSegments() {
    return D.accounts.map(a => ({ label: a.name, value: a.balance, color: ACCT_COLORS[a.type] || "#8e8e93" }));
  }

  function refreshDonut() {
    const segs = accountSegments();
    renderDonut(document.getElementById("ow-donut"), segs, {
      size: 200, stroke: 20, label: "NET WORTH", center: fmt$(D.netWorth, { compact: true }),
    });
    const legend = document.getElementById("ow-donut-legend");
    if (legend) legend.innerHTML = segs.map(s => `
      <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 0; font-size:12px;">
        <div class="flex" style="gap:8px;">
          <span class="dot" style="background:${s.color}; width:8px; height:8px;"></span>
          <span class="muted">${s.label}</span>
        </div>
        <span style="font-weight:600; font-variant-numeric:tabular-nums;">${D.netWorth ? ((s.value / D.netWorth) * 100).toFixed(1) : "0.0"}%</span>
      </div>
    `).join("");
  }

  // Recompute net worth + repaint hero number, delta, donut. Call after any account change.
  function recomputeOverview() {
    D.netWorth = D.accounts.reduce((s, a) => s + a.balance, 0);
    const heroEl = document.querySelector(".hero-value");
    if (heroEl) heroEl.textContent = "$" + Math.floor(D.netWorth).toLocaleString();
    const centsEl = document.querySelector(".hero-cents");
    if (centsEl) centsEl.textContent = "." + String(Math.round((D.netWorth % 1) * 100)).padStart(2, "0");
    refreshDonut();
    if (window.CommandPalette) window.CommandPalette.rebuild();
  }

  function showAddAccountForm() {
    const wrap = document.getElementById("ow-accounts");
    if (!wrap || wrap.querySelector(".account-add-form")) return;
    const form = document.createElement("div");
    form.className = "account-add-form";
    form.innerHTML = `
      <div class="aaf-grid">
        <input class="aaf-input" data-f="name" placeholder="Account name (e.g. Schwab Brokerage)"/>
        <input class="aaf-input" data-f="institution" placeholder="Institution"/>
        <select class="aaf-input" data-f="type">
          <option value="Taxable">Taxable</option>
          <option value="Retirement">Retirement</option>
          <option value="Cash">Cash</option>
          <option value="Crypto">Crypto</option>
        </select>
        <input class="aaf-input" data-f="balance" type="number" step="0.01" placeholder="Balance ($)"/>
      </div>
      <div class="aaf-actions">
        <button class="btn-ghost" data-cancel>Cancel</button>
        <button class="btn-primary" data-save>${Icon("check", 12)} Add account</button>
      </div>
    `;
    wrap.prepend(form);
    const nameInput = form.querySelector('[data-f="name"]');
    nameInput.focus();
    const close = () => form.remove();
    form.querySelector("[data-cancel]").addEventListener("click", close);
    form.querySelector("[data-save]").addEventListener("click", () => {
      const get = f => form.querySelector(`[data-f="${f}"]`).value.trim();
      const name = get("name") || "New Account";
      const balance = parseFloat(get("balance"));
      D.accounts.push({
        id: "acct-" + Date.now(),
        name,
        institution: get("institution") || "—",
        type: get("type"),
        balance: isNaN(balance) ? 0 : balance,
        _new: true,
      });
      close();
      renderAccounts();
      recomputeOverview();
    });
    form.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  }

  function renderAccounts() {
    const wrap = document.getElementById("ow-accounts");
    if (!wrap) return;
    wrap.innerHTML = D.accounts.map((a, i) => `
      <div class="account-row" data-idx="${i}">
        <div class="account-icon ${a.type.toLowerCase()}">${Icon(accountIcon(a.type), 18)}</div>
        <div class="account-info">
          <div class="account-name">${a.name}</div>
          <div class="account-meta">${a.institution} · ${a.type}</div>
        </div>
        <div class="account-balance">
          <div class="v" data-balance="${a.balance}">${fmt$(a.balance)}</div>
          <div class="e">${a._new ? "Just added" : "Updated today"}</div>
        </div>
        <div class="account-actions">
          <button class="acct-icon-btn" data-edit="${i}" title="Edit balance">${Icon("edit", 13)}</button>
          <button class="acct-icon-btn danger" data-remove="${i}" title="Remove account">${Icon("trash", 13)}</button>
        </div>
      </div>
    `).join("");

    wrap.querySelectorAll("[data-remove]").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = +btn.dataset.remove;
        const row = wrap.querySelector(`[data-idx="${idx}"]`);
        row.classList.add("removing");
        setTimeout(() => {
          D.accounts.splice(idx, 1);
          renderAccounts();
          recomputeOverview();
        }, 220);
      });
    });

    wrap.querySelectorAll("[data-edit]").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = +btn.dataset.edit;
        const row = wrap.querySelector(`[data-idx="${idx}"]`);
        const bal = row.querySelector(".account-balance");
        const current = D.accounts[idx].balance;
        bal.innerHTML = `<input class="account-edit-input" type="number" step="0.01" value="${current.toFixed(2)}"/>`;
        const input = bal.querySelector("input");
        input.focus(); input.select();
        const commit = () => {
          const v = parseFloat(input.value);
          if (!isNaN(v)) {
            D.accounts[idx].balance = v;
            bal.innerHTML = `<div class="v">${fmt$(v)}</div><div class="e">Updated just now</div>`;
            recomputeOverview();
          } else {
            bal.innerHTML = `<div class="v">${fmt$(current)}</div><div class="e">Updated today</div>`;
          }
        };
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") { input.value = current; commit(); } });
      });
    });
  }

  function accountIcon(type) {
    return ({ Taxable: "chart", Retirement: "target", Cash: "bank", Crypto: "coin" })[type] || "wallet";
  }

  function sliceByRange(hist, range) {
    if (range === "ALL") return hist;
    const months = ({ "1M": 1, "3M": 3, "6M": 6, "YTD": null, "1Y": 12, "2Y": 24 })[range];
    if (range === "YTD") return hist.filter(h => h.date.getFullYear() === 2026);
    return hist.slice(-Math.min(months, hist.length));
  }

  // ============================================================
  // ANALYZE
  // ============================================================
  function renderAnalyze() {
    const f = D.featured;
    return `
      <div class="grid g-analyze">
        <div>
          <div class="verdict ${f.signal.toLowerCase()}">
            <div class="verdict-inner">
              <div class="verdict-head">
                <div style="flex:1;">
                  <div class="flex gap-s">
                    <span class="verdict-pill">${f.signal}</span>
                    <span class="muted" style="font-size:12px;">CONFIDENCE · ${f.confidence.toUpperCase()}</span>
                    <span class="muted" style="font-size:12px;">${Icon("sparkles", 12)} Claude advisor</span>
                  </div>
                  <div class="verdict-ticker mt-s">${f.ticker} <span class="muted" style="font-size:15px; font-weight:500;">· ${f.name}</span></div>
                  <div class="verdict-meta mt-s">
                    <span>Price <span class="h-strong" style="color:var(--text);">${fmt$(f.price)}</span></span>
                    <span class="delta up">${fmtPct(f.changePct)}</span>
                    <span>Analyst target ${fmt$(f.target)} (${(((f.target - f.price)/f.price)*100).toFixed(1)}% upside)</span>
                  </div>
                </div>
              </div>
              <div class="verdict-thesis">${f.thesis}</div>
            </div>
          </div>

          <div class="card mt-m">
            <div class="card-head">
              <div class="flex gap-m">
                <h3>${f.ticker} · Price & technicals</h3>
                <div class="chart-legend">
                  <span class="lg"><span class="lg-line" style="background:var(--accent);"></span>Price</span>
                  <span class="lg"><span class="lg-line dashed" style="background:#ff9f0a;"></span>SMA 50</span>
                  <span class="lg"><span class="lg-line dashed" style="background:#b14aff;"></span>SMA 200</span>
                </div>
              </div>
              <div class="range-pills"><button>1M</button><button class="active">6M</button><button>1Y</button><button>5Y</button></div>
            </div>
            <div class="card-body">
              <div id="an-chart" style="height:280px;"></div>
            </div>
          </div>

          <div class="grid g-2 mt-m">
            <div class="card">
              <div class="card-head"><h3>Risks</h3></div>
              <div class="card-body">
                ${f.risks.map(r => `<div class="risk-item">${Icon("alert", 14)}<span>${r}</span></div>`).join("")}
              </div>
            </div>
            <div class="card">
              <div class="card-head"><h3>Catalysts</h3></div>
              <div class="card-body">
                ${f.catalysts.map(c => `<div class="risk-item" style="background:var(--green-soft);"><span style="color:var(--green);">${Icon("check", 14)}</span><span>${c}</span></div>`).join("")}
              </div>
            </div>
          </div>

          <div class="card mt-m">
            <div class="card-head"><h3>Analyst breakdown</h3><div class="meta">Generated from technicals + fundamentals + news</div></div>
            <div class="card-body">
              <div style="margin-bottom:14px;">
                <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; margin-bottom:4px;">Technical</div>
                <div style="font-size:13px; line-height:1.55;">${f.technical}</div>
              </div>
              <div style="margin-bottom:14px;">
                <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; margin-bottom:4px;">Fundamental</div>
                <div style="font-size:13px; line-height:1.55;">${f.fundamental}</div>
              </div>
              <div>
                <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; margin-bottom:4px;">News flow</div>
                <div style="font-size:13px; line-height:1.55;">${f.newsSummary}</div>
              </div>
            </div>
          </div>
        </div>

        <div>
          <div class="grid g-2" style="gap:10px;">
            <div class="stat-tile"><div class="label">Market Cap</div><div class="v">${f.marketCap}</div></div>
            <div class="stat-tile"><div class="label">P/E (FWD)</div><div class="v">${f.peFwd}</div></div>
            <div class="stat-tile"><div class="label">Beta</div><div class="v">${f.beta}</div></div>
            <div class="stat-tile"><div class="label">Div Yield</div><div class="v">${f.divYield}%</div></div>
          </div>

          <div class="card mt-m">
            <div class="card-head"><h3>Fundamentals</h3></div>
            <div class="card-body">
              ${fundRow("Sector", f.sector)}
              ${fundRow("Industry", f.industry)}
              ${fundRow("P/E trailing", f.pe)}
              ${fundRow("52w high", fmt$(f.high52))}
              ${fundRow("52w low", fmt$(f.low52))}
              ${fundRow("Annual div", "$" + f.annualDiv + "/yr")}
              ${fundRow("Street rating", f.rating)}
              ${fundRow("Next earnings", f.nextEarnings)}
            </div>
          </div>

          <div class="card mt-m">
            <div class="card-head"><h3>News</h3></div>
            <div class="card-body">
              ${D.news.filter(n => n.ticker === f.ticker || n.ticker === "MACRO").map(n => `
                <div class="news-item">
                  <span class="news-tag">${n.ticker}</span>
                  <div>
                    <div class="news-headline">${n.headline}</div>
                    <div class="news-meta">${n.source} · ${n.time}</div>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function fundRow(k, v) {
    return `<div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border); font-size:13px;">
      <span class="muted">${k}</span><span class="h-strong">${v}</span>
    </div>`;
  }

  function hydrateAnalyze() {
    const draw = () => {
      const data = D.featuredHistory.slice(-130); // 6 months
      renderMultiLineChart(document.getElementById("an-chart"), [
        { color: "var(--accent)", data: data.map(d => ({ x: d.date, y: d.close })) },
        { color: "#ff9f0a", dash: "4,3", data: data.map(d => ({ x: d.date, y: d.sma50 })) },
        { color: "#b14aff", dash: "4,3", data: data.map(d => ({ x: d.date, y: d.sma200 })) },
      ]);
    };
    draw();
    window.AppleSections._redraw = draw;
  }

  // expose
  window.AppleSections = { renderOverview, hydrateOverview, renderAnalyze, hydrateAnalyze, moverRow, sectorColor };
})();
