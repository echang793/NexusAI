// NexusAI Apple-like — Planning section (full FIRE, contributions, rebalance,
// tax-loss harvesting, dividend income, emergency fund, net worth percentile).
// Reads global window.NEXUS_DATA. Uses Icon(), fmt$(), fmtPct().

(() => {
  const D = window.NEXUS_DATA;

  function renderPlanning() {
    return `
      <div class="flex-between mb-m">
        <div class="muted" style="font-size:12px;">Full FIRE, contributions, rebalancing, tax-loss harvesting, dividends & context — reviewed as often as you like.</div>
        <button class="btn-ghost" id="planning-export-gains">${Icon("corner_down", 12)} Export unrealized gains CSV</button>
      </div>
      <div class="grid g-2">
        ${fireCard(D.fire)}
        ${contributionsCard(D.contributions)}
      </div>
      <div class="grid g-2 mt-m">
        ${rebalanceCard(D.rebalance)}
        ${emergencyFundCard(D.emergencyFund, D.netWorthPercentile, D.profile)}
      </div>
      <div class="grid g-2 mt-m">
        ${taxLossCard(D.taxLossHarvest)}
        ${dividendsCard(D.dividends)}
      </div>
    `;
  }

  function fireCard(f) {
    const fd = f || {};
    if (!fd.enabled) {
      return `
        <div class="card">
          <div class="card-head"><h3>Full FIRE</h3><div class="meta">With contributions</div></div>
          <div class="card-body">
            <div class="muted" style="font-size:13px; line-height:1.5;">
              Set your retirement age and annual spend in Settings (CoastFIRE section) to enable this.
            </div>
          </div>
        </div>
      `;
    }
    const mc = fd.monteCarlo || {};
    return `
      <div class="card">
        <div class="card-head"><h3>Full FIRE</h3><div class="meta">$${(fd.monthlyContribution || 0).toLocaleString()}/mo contribution</div></div>
        <div class="card-body">
          <div class="grid g-2" style="gap:10px;">
            <div class="stat-tile">
              <div class="label">Years to FIRE</div>
              <div class="v">${fd.yearsToFire === null ? "80+" : fd.yearsToFire}</div>
              <div class="e">${fd.fireAge ? `Age ${fd.fireAge}` : "Increase contributions"}</div>
            </div>
            <div class="stat-tile">
              <div class="label">Projected at retirement</div>
              <div class="v">${fmt$(fd.projectedAtRetirement, { compact: true })}</div>
              <div class="e">vs ${fmt$(fd.fireNumber, { compact: true })} target</div>
            </div>
          </div>
          ${mc.successPct != null ? `
          <div class="mt-m">
            <div class="flex-between" style="font-size:12px; color:var(--text-2); margin-bottom:4px;">
              <span>Monte Carlo success odds</span><span class="h-strong" style="color:var(--text);">${mc.successPct}%</span>
            </div>
            <div class="bar-track" style="height:8px;">
              <div class="bar-fill" style="width:${mc.successPct}%; background:${mc.successPct >= 70 ? "var(--green)" : mc.successPct >= 40 ? "#ff9f0a" : "var(--red)"};"></div>
            </div>
            <div class="muted mt-s" style="font-size:11px;">${mc.trials.toLocaleString()} simulated random-return paths — a probability, not a promise.</div>
          </div>` : ""}
        </div>
      </div>
    `;
  }

  function contributionsCard(c) {
    const cd = c || {};
    const rows = ["401k", "hsa", "roth"].map(k => {
      const x = cd[k] || { label: k, limit: 0, ytd: 0, room: 0, pctUsed: 0, maxed: false };
      const pct = Math.min(100, x.pctUsed);
      return `
        <div class="mb-m">
          <div class="flex-between" style="font-size:12px; margin-bottom:4px;">
            <span class="h-strong">${x.label}</span>
            <span class="muted">${fmt$(x.ytd, { compact: true })} / ${fmt$(x.limit, { compact: true })}</span>
          </div>
          <div class="bar-track" style="height:8px;">
            <div class="bar-fill" style="width:${pct}%; background:${x.maxed ? "var(--green)" : "var(--accent)"};"></div>
          </div>
          <div class="muted mt-s" style="font-size:11px;">${x.maxed ? "Maxed out ✅" : `${fmt$(x.room, { compact: true })} room left this year`}</div>
        </div>
      `;
    }).join("");
    return `
      <div class="card">
        <div class="card-head"><h3>Contribution room</h3><div class="meta">2025 IRS limits</div></div>
        <div class="card-body">
          ${rows}
          <div class="muted" style="font-size:11px;">YTD amounts are entered manually in Settings — no transaction feed to derive them from.</div>
        </div>
      </div>
    `;
  }

  function rebalanceCard(r) {
    const rd = r || {};
    return `
      <div class="card">
        <div class="card-head"><h3>Rebalance check</h3><div class="meta">Stock vs safe (cash/T-bills)</div></div>
        <div class="card-body">
          <div class="flex-between mb-m">
            <div><div class="muted" style="font-size:12px;">Actual stock exposure</div><div style="font-size:20px; font-weight:700;">${rd.actualStockPct}%</div></div>
            <div style="text-align:right;"><div class="muted" style="font-size:12px;">Target</div><div style="font-size:20px; font-weight:700;">${rd.targetStockPct}%</div></div>
          </div>
          <div class="bar-track" style="height:10px;">
            <div class="bar-fill" style="width:${Math.min(100, rd.actualStockPct)}%; background:${rd.onTarget ? "var(--green)" : "#ff9f0a"};"></div>
          </div>
          <div class="mt-s" style="font-size:12px; color:var(--text-2);">
            ${rd.onTarget
              ? "Within tolerance of target — no action needed."
              : `Drifted ${Math.abs(rd.drift).toFixed(1)}pt ${rd.drift > 0 ? "over" : "under"} target. Set target in Settings.`}
          </div>
        </div>
      </div>
    `;
  }

  function emergencyFundCard(ef, pct, profile) {
    const efd = ef || {};
    const pd = pct || {};
    return `
      <div class="card">
        <div class="card-head"><h3>Emergency fund & context</h3></div>
        <div class="card-body">
          <div class="flex-between mb-m">
            <div><div class="muted" style="font-size:12px;">Cash on hand</div><div style="font-size:20px; font-weight:700;">${fmt$(efd.cashTotal, { compact: true })}</div></div>
            <div style="text-align:right;"><div class="muted" style="font-size:12px;">Months covered</div>
              <div style="font-size:20px; font-weight:700; color:${efd.healthy ? "var(--green)" : "var(--red)"};">${efd.monthsCovered != null ? efd.monthsCovered : "—"}</div>
            </div>
          </div>
          <div class="muted" style="font-size:11px; margin-bottom:14px;">
            ${efd.monthlyExpense ? `Based on ${fmt$(efd.monthlyExpense, { compact: true })}/mo expense estimate — set exact figure in Settings.` : "Set a monthly expense estimate in Settings to enable this."}
            ${!efd.healthy && efd.monthsCovered != null ? " Under the common 3-month minimum." : ""}
          </div>
          <div class="divider"></div>
          <div class="flex-between mt-m">
            <div class="muted" style="font-size:12px;">Net worth percentile (age ${profile ? profile.age : "—"})</div>
            <div class="h-strong">~${pd.percentile || "—"}th</div>
          </div>
          <div class="muted" style="font-size:11px;">Rough estimate from aggregated public survey data — context only, not personalized advice.</div>
        </div>
      </div>
    `;
  }

  function taxLossCard(list) {
    const rows = list || [];
    return `
      <div class="card">
        <div class="card-head"><h3>Tax-loss harvesting</h3><div class="meta">${rows.length} candidate${rows.length === 1 ? "" : "s"}</div></div>
        <div class="card-body">
          ${rows.length === 0 ? `<div class="muted" style="font-size:13px;">No positions past your loss threshold right now.</div>` : rows.map(t => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border);">
              <div>
                <div style="font-weight:600; font-size:13px;">${t.ticker}</div>
                <div class="muted" style="font-size:11px;">${t.account}</div>
              </div>
              <div class="delta down">${fmtPct(t.plPct)}</div>
              <div class="t-right h-strong" style="min-width:80px;">${fmt$(Math.abs(t.unrealizedLoss), { compact: true })}</div>
            </div>
          `).join("")}
          <div class="muted mt-m" style="font-size:11px;">
            No purchase-date or sale history is tracked — can't split short/long-term or check wash sales. Verify against your broker before acting.
          </div>
        </div>
      </div>
    `;
  }

  function dividendsCard(d) {
    const dd = d || { annualIncome: 0, monthlyAvg: 0, topPayers: [] };
    return `
      <div class="card">
        <div class="card-head"><h3>Dividend income</h3><div class="meta">Projected annual</div></div>
        <div class="card-body">
          <div class="flex-between mb-m">
            <div><div class="muted" style="font-size:12px;">Annual</div><div style="font-size:20px; font-weight:700;">${fmt$(dd.annualIncome, { compact: true })}</div></div>
            <div style="text-align:right;"><div class="muted" style="font-size:12px;">Monthly avg</div><div style="font-size:20px; font-weight:700;">${fmt$(dd.monthlyAvg, { compact: true })}</div></div>
          </div>
          ${dd.topPayers.length ? dd.topPayers.map(p => `
            <div style="display:flex; justify-content:space-between; padding:6px 0; font-size:12px;">
              <span class="muted">${p.ticker}</span><span class="h-strong">${fmt$(p.annualIncome, { compact: true })}/yr</span>
            </div>
          `).join("") : `<div class="muted" style="font-size:12px;">Fetching dividend rates in the background — check back in a minute.</div>`}
        </div>
      </div>
    `;
  }

  function hydratePlanning() {
    requestAnimationFrame(() => {
      document.querySelectorAll("[data-w]").forEach(el => { el.style.width = el.dataset.w + "%"; });
    });
    const exportBtn = document.getElementById("planning-export-gains");
    if (exportBtn && !exportBtn.dataset.bound) {
      exportBtn.dataset.bound = "1";
      exportBtn.addEventListener("click", () => { window.location.href = "/api/export/gains"; });
    }
  }

  window.AppleSections = Object.assign(window.AppleSections || {}, { renderPlanning, hydratePlanning });
})();
