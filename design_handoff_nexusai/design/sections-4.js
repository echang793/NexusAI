// NexusAI — "Money" sections: Cash Flow page, goals, budget, what-if planner,
// investment performance, portfolio check, why-net-worth-moved and the health
// banner. Reads window.NEXUS_DATA (server.py blocks: cashFlow, goals, budget,
// performance, portfolioCheck, whyItMoved, dailyNetWorth, health, categoryRules).
//
// Everything that comes from Plaid or the user (merchant names, goal names,
// account names) is escaped before it reaches innerHTML.

(() => {
  const D = window.NEXUS_DATA;

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const usd = (n, o = {}) => (n == null || isNaN(n) ? "—" : fmt$(n, { dec: 0, ...o }));
  const signed = (n) => (n == null || isNaN(n) ? "—" : fmt$(n, { dec: 0, signed: true }));
  // Compact signed money for narrow stat tiles: +$300, -$11.4K
  const signedK = (n) => (n == null || isNaN(n) ? "—" : (n > 0 ? "+" : "") + fmt$(n, { dec: 0, compact: true }));
  const pct1 = (n) => (n == null || isNaN(n) ? "—" : n.toFixed(1) + "%");
  const spct = (n) => (n == null || isNaN(n) ? "—" : (n > 0 ? "+" : "") + n.toFixed(1) + "%");
  const tone = (n) => (n > 0 ? "var(--green)" : n < 0 ? "var(--red)" : "var(--text-2)");
  const monthLabel = (m) => {
    const [y, mo] = m.split("-").map(Number);
    // "Oct ’26" — a bare "Oct 26" reads as October 26th
    return new Date(y, mo - 1, 1).toLocaleDateString("en-US", { month: "short" }) + " ’" + String(y).slice(2);
  };
  const dayLabel = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const INPUT = `padding:8px 10px; border-radius:8px; border:1px solid var(--border); background:var(--surface-2);
                 color:var(--text); font-size:13px; box-sizing:border-box;`;
  const note = (t) => `<div class="muted" style="font-size:11px; line-height:1.5;">${t}</div>`;
  const tile = (label, v, e = "", color = "") =>
    `<div class="stat-tile"><div class="label">${label}</div><div class="v" ${color ? `style="color:${color}"` : ""}>${v}</div>${e ? `<div class="e">${e}</div>` : ""}</div>`;
  const barRow = (label, value, max, text, color = "var(--accent)") => `
    <div class="bar-row">
      <span>${label}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${max > 0 ? Math.max(0, Math.min(100, value / max * 100)) : 0}%; background:${color};"></div></div>
      <span class="t-right h-strong">${text}</span>
    </div>`;

  // ---------------------------------------------------------------- Overview
  function healthBanner(h) {
    if (!h || h.ok || !(h.problems || []).length) return "";
    return `
      <div class="card mb-m" style="border-color:#ff9f0a;">
        <div class="card-body">
          <div class="flex gap-s" style="align-items:center; margin-bottom:6px; color:#ff9f0a; font-weight:600;">
            ${Icon("alert", 14)} Data check — ${h.problems.length} thing${h.problems.length === 1 ? "" : "s"} need attention
          </div>
          ${h.problems.map((p) => `<div style="font-size:12px; line-height:1.6;">• ${esc(p.message)}</div>`).join("")}
          ${note("These are what the nightly watchdog checks. Numbers below may be stale until fixed.")}
        </div>
      </div>`;
  }

  function whyCard(w) {
    if (!w || !w.available) {
      return `
        <div class="card">
          <div class="card-head"><h3>Why net worth moved</h3></div>
          <div class="card-body">${note("Needs at least two days of tracking. It fills in automatically as the daily refresh runs.")}</div>
        </div>`;
    }
    const movers = (w.movers || []).map((m) =>
      `<span class="muted" style="font-size:12px; margin-right:12px;">${esc(m.ticker)} <b style="color:${tone(m.market)}">${signed(m.market)}</b></span>`).join("");
    const other = (w.otherByAccount || []).map((a) =>
      `<div class="flex-between" style="font-size:12px; padding:3px 0;"><span class="muted">${esc(a.name)}</span><b style="color:${tone(a.change)}">${signed(a.change)}</b></div>`).join("");
    return `
      <div class="card">
        <div class="card-head"><h3>Why net worth moved</h3><div class="meta">${dayLabel(w.start)} → ${dayLabel(w.end)}</div></div>
        <div class="card-body">
          <div class="grid g-3" style="gap:10px;">
            ${tile("Market moves", signedK(w.market), w.marketPct != null ? spct(w.marketPct) + " on holdings" : "", tone(w.market))}
            ${tile("New shares bought", signedK(w.contributions), "money you put in")}
            ${tile("Other accounts", signedK(w.other), "cash, 401(k), checking", tone(w.other))}
          </div>
          ${movers ? `<div class="mt-m">${movers}</div>` : ""}
          ${other ? `<div class="mt-m">${other}</div>` : ""}
          <div class="mt-s">${note("Market vs money-in is exact: shares you buy never count as gains. The 401(k) is one lump balance, so its growth and contributions can't be separated.")}</div>
        </div>
      </div>`;
  }

  function dailyCard(series) {
    return `
      <div class="card">
        <div class="card-head"><h3>Daily net worth</h3><div class="meta">${(series || []).length} days tracked</div></div>
        <div class="card-body">
          <div id="ow-daily-chart" style="height:190px;"></div>
          ${(series || []).length < 3 ? note("The chart fills in as more days are recorded.") : ""}
        </div>
      </div>`;
  }

  function overviewTop() { return healthBanner(D.health); }
  function overviewMid() {
    return `<div class="grid g-2 mt-m">${whyCard(D.whyItMoved)}${dailyCard(D.dailyNetWorth)}</div>`;
  }
  function hydrateOverviewMoney() {
    const el = document.getElementById("ow-daily-chart");
    const s = (D.dailyNetWorth || []).map((p) => ({ x: new Date(p.date + "T12:00:00"), y: p.value }));
    if (el && s.length >= 2) {
      renderAreaChart(el, s, {
        fmtY: (v) => "$" + (v / 1000).toFixed(0) + "K",
        fmtX: (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        fmtTip: (v) => fmt$(v, { dec: 0 }),
        color: "var(--accent)",
      });
    } else if (el) {
      el.innerHTML = '<div class="chart-empty">Not enough days yet</div>';
    }
  }

  // --------------------------------------------------------------- Portfolio
  function performanceCard(p) {
    const t = p && p.total;
    if (!t) {
      return `<div class="card"><div class="card-head"><h3>Investment performance</h3></div>
        <div class="card-body">${note("Needs two days of tracking.")}</div></div>`;
    }
    const v = p.vsSpy || {};
    const accounts = Object.entries(p.byAccount || {}).map(([name, r]) =>
      `<div class="flex-between" style="font-size:12px; padding:4px 0;"><span class="muted">${esc(name)}</span>
        <b style="color:${tone(r.returnPct)}">${spct(r.returnPct)}</b></div>`).join("");
    const spy = v.covered
      ? `<div class="flex-between" style="font-size:12px;"><span class="muted">SPY, ${dayLabel(v.from)} → ${dayLabel(v.to)}</span><b>${spct(v.spyPct)}</b></div>
         <div class="flex-between" style="font-size:12px;"><span class="muted">You vs SPY</span><b style="color:${tone(v.excessPct)}">${spct(v.excessPct)} pts</b></div>`
      : note("SPY comparison starts once two days with a SPY price are recorded (tracking began recently).");
    return `
      <div class="card">
        <div class="card-head"><h3>Investment performance</h3><div class="meta">since ${dayLabel(p.since)}</div></div>
        <div class="card-body">
          <div class="grid g-2" style="gap:10px;">
            ${tile("Time-weighted return", spct(t.returnPct), `${t.days} days`, tone(t.returnPct))}
            ${tile("Market gain / loss", signedK(t.marketGain), "excludes deposits", tone(t.marketGain))}
          </div>
          <div class="mt-m">${spy}</div>
          <div class="divider"></div>
          ${accounts}
          <div class="mt-s">${note("Holdings only (Webull, Roth, HSA funds). Deposits and new shares are not counted as gains. The 401(k) is a single balance, so it's excluded. Annualized figures appear after a year of history.")}</div>
        </div>
      </div>`;
  }

  function portfolioCheckCard(a) {
    if (!a || !a.total) return "";
    const max = Math.max(1, ...((a.topStocks || []).map((s) => s.pct)));
    const stocks = (a.topStocks || []).map((s) => barRow(esc(s.ticker), s.pct, max, pct1(s.pct))).join("");
    const mix = Object.entries(a.allocation || {}).map(([k, v]) =>
      `<span class="muted" style="font-size:12px; margin-right:12px;">${esc(k)} <b style="color:var(--text)">${pct1(v)}</b></span>`).join("");
    const flags = (a.singleNameFlags || []).map((f) => `${esc(f.ticker)} ${pct1(f.pct)}`).join(", ");
    const loc = (a.location || []).slice(0, 3).map((x) =>
      `<div style="font-size:12px; padding:3px 0;">• <b>${esc(x.ticker)}</b> in ${esc(x.account)} — ${esc(x.why)}</div>`).join("");
    const r = a.risk || {};
    return `
      <div class="card">
        <div class="card-head"><h3>Portfolio check</h3><div class="meta">${a.effectiveN ? `≈ ${a.effectiveN} equal-sized positions` : ""}</div></div>
        <div class="card-body">
          <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; margin-bottom:6px;">
            Individual stocks · ${pct1(a.stocksPct)} of investments</div>
          ${stocks || note("No individual stocks.")}
          ${flags ? `<div class="mt-s" style="font-size:12px; color:#ff9f0a;">Above 10%: ${flags}</div>` : ""}
          <div class="divider"></div>
          <div>${mix}</div>
          ${r.sharpe != null ? `<div class="mt-s" style="font-size:12px;">Past-year risk: Sharpe <b>${r.sharpe}</b>${r.benchmarkSharpe != null ? ` vs ${r.benchmarkSharpe} for SPY` : ""}${r.maxDrawdown != null ? ` · worst drop ${Math.abs(r.maxDrawdown).toFixed(1)}%` : ""}</div>` : ""}
          ${(a.multiAccount || []).length ? `<div class="mt-s">${note(`${a.multiAccount.length} holdings appear in more than one account, so account views overstate how many separate bets you have.`)}</div>` : ""}
          ${loc ? `<div class="divider"></div><div class="muted" style="font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px;">Tax placement to consider</div>${loc}` : ""}
        </div>
      </div>`;
  }

  function portfolioMoney() {
    return `<div class="grid g-2 mt-m">${performanceCard(D.performance)}${portfolioCheckCard(D.portfolioCheck)}</div>`;
  }

  // --------------------------------------------------------------- Cash flow
  const CATEGORY_LABELS = {
    FOOD_AND_DRINK: "Food & drink", RENT_AND_UTILITIES: "Rent & utilities", GENERAL_MERCHANDISE: "Shopping",
    GENERAL_SERVICES: "Services", TRANSPORTATION: "Transportation", TRAVEL: "Travel", ENTERTAINMENT: "Entertainment",
    PERSONAL_CARE: "Personal care", MEDICAL: "Medical", HOME_IMPROVEMENT: "Home", LOAN_PAYMENTS: "Loan payments",
    BANK_FEES: "Bank fees", GOVERNMENT_AND_NON_PROFIT: "Government & giving", TRANSFER_OUT: "Transfer (not spending)",
    OTHER: "Other",
  };
  const catLabel = (c) => CATEGORY_LABELS[c] || (c || "").replace(/_/g, " ").toLowerCase().replace(/^./, (x) => x.toUpperCase());

  function cashflowSetup() {
    return `
      <div class="card">
        <div class="card-head"><h3>Cash flow</h3><div class="meta">Not connected yet</div></div>
        <div class="card-body">
          <div style="font-size:13px; line-height:1.6;">
            Spending, income and savings rate come from your bank's transactions. Your Chase link currently shares
            balances only. To add transactions (free on Plaid's trial plan), run this in a terminal and approve it in
            Plaid's own window — your bank login is never typed here:
          </div>
          <pre style="background:var(--surface-2); padding:10px 12px; border-radius:8px; font-size:12px; overflow:auto; margin:10px 0;">.venv/bin/python3 scripts/plaid_link.py --update 1 --products transactions</pre>
          ${note("The daily refresh then pulls transactions automatically. Credit cards link the same way with --products transactions (no --update) if they are at a different bank.")}
        </div>
      </div>`;
  }

  function budgetCard(b, cf) {
    const cfd = cf || {};
    const cats = new Set(Object.keys((b && (b.current || b.last) ? ((b.current || b.last).rows || []).reduce((o, r) => (o[r.category] = 1, o), {}) : {})));
    const last = (cfd.lastMonth && cfd.lastMonth.byCategory) || {};
    Object.keys(last).forEach((c) => cats.add(c));
    const targets = {};
    [(b && b.current), (b && b.last)].forEach((cmp) => ((cmp && cmp.rows) || []).forEach((r) => { targets[r.category] = r.target; }));
    const view = (b && (b.current || b.last)) || null;
    const rows = view ? view.rows.map((r) => `
      <div class="mb-m">
        <div class="flex-between" style="font-size:12px; margin-bottom:4px;">
          <span class="h-strong">${esc(catLabel(r.category))}</span>
          <span style="color:${r.over ? "var(--red)" : r.aheadOfPace ? "#ff9f0a" : "var(--text-2)"}">${usd(r.actual)} / ${usd(r.target)}${r.over ? " · over" : r.aheadOfPace ? " · ahead of pace" : ""}</span>
        </div>
        <div class="bar-track" style="height:8px;"><div class="bar-fill" style="width:${Math.min(100, r.pctUsed || 0)}%; background:${r.over ? "var(--red)" : r.aheadOfPace ? "#ff9f0a" : "var(--green)"};"></div></div>
      </div>`).join("") : "";
    const month = b && b.current ? b.currentMonth : b && b.last ? b.lastMonth : null;
    const editors = [...cats].sort().map((c) => `
      <label style="display:flex; align-items:center; justify-content:space-between; gap:10px; font-size:12px; padding:3px 0;">
        <span>${esc(catLabel(c))}</span>
        <input data-budget="${esc(c)}" type="number" min="0" step="10" value="${targets[c] != null ? targets[c] : ""}" placeholder="no limit" style="width:110px; ${INPUT}"/>
      </label>`).join("");
    return `
      <div class="card">
        <div class="card-head"><h3>Budget</h3><div class="meta">${month ? monthLabel(month) + (b.current ? " · month in progress" : "") : "Monthly targets"}</div></div>
        <div class="card-body">
          ${rows || note("Set a monthly target for any category below to see how you're tracking.")}
          ${view && view.unbudgeted > 0 ? note(`${usd(view.unbudgeted)} spent in categories without a target.`) : ""}
          <details class="mt-m"><summary style="cursor:pointer; font-size:12px; color:var(--accent);">Edit targets</summary>
            <div class="mt-s">${editors || note("Categories appear once transactions sync.")}</div>
            <div class="flex gap-s mt-s"><button class="btn-primary" id="budget-save">Save budget</button><span id="budget-status" class="muted" style="font-size:12px;"></span></div>
          </details>
        </div>
      </div>`;
  }

  function rulesCard(rules) {
    const list = (rules || []).map((r, i) => `
      <div class="flex-between" style="font-size:12px; padding:3px 0;">
        <span>"${esc(r.match)}" → <b>${esc(catLabel(r.category))}</b></span>
        <button class="btn-ghost" data-rule-del="${i}" title="Remove">${Icon("x", 12)}</button>
      </div>`).join("");
    const opts = Object.entries(CATEGORY_LABELS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    return `
      <div class="card">
        <div class="card-head"><h3>Category rules</h3><div class="meta">Fix miscategorized merchants</div></div>
        <div class="card-body">
          ${list || note("No rules yet. A rule recategorizes any transaction whose name contains the text. Send something to “Transfer (not spending)” to exclude it entirely.")}
          <div class="flex gap-s mt-m" style="flex-wrap:wrap;">
            <input id="rule-match" placeholder="merchant contains…" style="flex:1; min-width:140px; ${INPUT}"/>
            <select id="rule-cat" style="${INPUT}">${opts}</select>
            <button class="btn-primary" id="rule-add">Add rule</button>
          </div>
          <span id="rule-status" class="muted" style="font-size:12px;"></span>
        </div>
      </div>`;
  }

  function renderCashflow() {
    const cf = D.cashFlow || {};
    if (!cf.completeMonths && !cf.currentMonth) return cashflowSetup();
    const last = cf.lastMonth;
    const assumed = cf.assumedAnnualSpend
      ? `<div class="mt-m" style="font-size:12px; line-height:1.6;">
           Your real spending is <b style="color:${tone(-cf.spendVsAssumedPct)}">${Math.abs(cf.spendVsAssumedPct).toFixed(0)}% ${cf.spendVsAssumedPct <= 0 ? "below" : "above"}</b>
           the ${usd(cf.assumedAnnualSpend)}/yr in your plan. At your actual spend the 25× FIRE number is
           <b>${usd(cf.fireNumberAtActual, { compact: true })}</b> instead of ${usd(cf.assumedAnnualSpend * 25, { compact: true })}.
         </div>` : "";
    const cats = last ? Object.entries(last.byCategory).sort((a, b) => b[1] - a[1]).slice(0, 8) : [];
    const max = cats.length ? cats[0][1] : 1;
    return `
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px;">
        ${tile("Avg monthly spend", usd(cf.avgMonthlySpend), `${cf.completeMonths} full month${cf.completeMonths === 1 ? "" : "s"}`)}
        ${tile("Avg tracked income", usd(cf.avgMonthlyIncome), "salary & other income")}
        ${tile("Moved to investments", usd(cf.avgMonthlyInvested), "per month, avg")}
        ${tile("Left over each month", usd(cf.avgMonthlySurplus), "income − spending", tone(cf.avgMonthlySurplus))}
        ${tile("Savings rate", cf.avgSavingsRate == null ? "—" : pct1(cf.avgSavingsRate), "of tracked income")}
      </div>
      ${cf.investedExceedsIncome ? `<div class="mt-s" style="font-size:12px; color:#ff9f0a; line-height:1.5;">
        You move more into investments (${usd(cf.avgMonthlyInvested)}/mo) than the income these accounts see (${usd(cf.avgMonthlyIncome)}/mo).
        Transfers and deposits from accounts that aren't linked aren't counted as income, so the savings rate understates what you actually save.</div>` : ""}
      ${cf.shortHistory ? `<div class="mt-s">${note("Fewer than 3 full months of data so far — averages will firm up.")}</div>` : ""}
      ${assumed}
      <div class="grid g-2 mt-m">
        <div class="card">
          <div class="card-head"><h3>Spending by month</h3></div>
          <div class="card-body"><div id="cf-chart" style="height:210px;"></div></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>${last ? monthLabel(last.month) : "Last month"} by category</h3><div class="meta">${last ? usd(last.spending) + " total" : ""}</div></div>
          <div class="card-body">
            ${cats.map(([c, v]) => barRow(esc(catLabel(c)), v, max, usd(v))).join("") || note("No spending recorded.")}
            ${(cf.topMerchants || []).length ? `<div class="divider"></div><div class="muted" style="font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px;">Top merchants (3 mo)</div>${cf.topMerchants.map((m) => `<div class="flex-between" style="font-size:12px; padding:2px 0;"><span class="muted">${esc(m.merchant)}</span><b>${usd(m.amount)}</b></div>`).join("")}` : ""}
          </div>
        </div>
      </div>
      <div class="grid g-2 mt-m">${budgetCard(D.budget, cf)}${rulesCard(D.categoryRules)}</div>
      <div class="mt-m">${note("Transfers between your own accounts and credit-card payments are excluded so nothing is counted twice. Income is only what is categorized as income; 401(k) payroll deferrals never show up in your bank account.")}</div>`;
  }

  function hydrateCashflow() {
    const cf = D.cashFlow || {};
    const el = document.getElementById("cf-chart");
    if (el) {
      const skip = new Set([...(cf.partialMonths || []), cf.currentMonth ? cf.currentMonth.month : ""]);
      const months = Object.entries(cf.months || {}).filter(([m]) => !skip.has(m)).slice(-12);
      if (months.length) {
        renderBarChart(el, months.map(([m, v]) => ({ label: monthLabel(m), value: v.spending })), {
          fmtY: (v) => "$" + (v / 1000).toFixed(1) + "K", fmtBar: (v) => "$" + (v / 1000).toFixed(1) + "K", color: "var(--accent)" });
      } else { el.innerHTML = '<div class="chart-empty">No full months yet</div>'; }
    }
    bindOnce("budget-save", "click", async () => {
      const budget = {};
      document.querySelectorAll("[data-budget]").forEach((i) => { const v = parseFloat(i.value); if (v > 0) budget[i.dataset.budget] = v; });
      await save("/api/budget", { budget }, "budget-status");
    });
    bindOnce("rule-add", "click", async () => {
      const match = (document.getElementById("rule-match").value || "").trim();
      if (!match) return;
      const rules = [...(D.categoryRules || []), { match, category: document.getElementById("rule-cat").value }];
      await save("/api/category-rules", { rules }, "rule-status");
    });
    document.querySelectorAll("[data-rule-del]").forEach((b) => {
      if (b.dataset.bound) return;
      b.dataset.bound = "1";
      b.addEventListener("click", async () => {
        const rules = (D.categoryRules || []).filter((_, i) => i !== Number(b.dataset.ruleDel));
        await save("/api/category-rules", { rules }, "rule-status");
      });
    });
  }

  // ---------------------------------------------------------------- Planning
  function goalsCard(g) {
    const items = (g && g.items) || [];
    const sum = (g && g.summary) || {};
    const rows = items.map((x) => {
      const statusTxt = x.status === "done" ? "Reached 🎉" : x.status === "overdue" ? "Past its date"
        : x.requiredMonthly != null ? `${usd(x.requiredMonthly)}/mo needed` : "no target date";
      return `
        <div class="mb-m">
          <div class="flex-between" style="font-size:12px; margin-bottom:4px;">
            <span class="h-strong">${esc(x.name)}</span>
            <span class="muted">${usd(x.saved)} / ${usd(x.target)}${x.date ? " · by " + esc(x.date) : ""}
              <button class="btn-ghost" data-goal-del="${esc(x.id)}" title="Remove goal" style="margin-left:6px;">${Icon("x", 11)}</button></span>
          </div>
          <div class="bar-track" style="height:8px;"><div class="bar-fill" style="width:${x.pct}%; background:${x.status === "done" ? "var(--green)" : x.status === "overdue" ? "var(--red)" : "var(--accent)"};"></div></div>
          <div class="muted mt-s" style="font-size:11px;">${statusTxt}${x.missingAccounts && x.missingAccounts.length ? ` · account not found: ${esc(x.missingAccounts.join(", "))}` : ""}</div>
        </div>`;
    }).join("");
    const accts = (D.accounts || []).filter((a) => a.type !== "Debt").map((a) =>
      `<option value="${esc(a.name)}">${esc(a.name)}</option>`).join("");
    const fund = sum.fundable == null ? "" : sum.fundable
      ? `<div style="font-size:12px; color:var(--green);">Your ${usd(sum.monthlySurplus)}/mo left-over covers the ${usd(sum.totalRequiredMonthly)}/mo these goals need.</div>`
      : `<div style="font-size:12px; color:#ff9f0a;">These goals need ${usd(sum.totalRequiredMonthly)}/mo but you have about ${usd(sum.monthlySurplus)}/mo left over.</div>`;
    return `
      <div class="card">
        <div class="card-head"><h3>Savings goals</h3><div class="meta">${items.length} goal${items.length === 1 ? "" : "s"}</div></div>
        <div class="card-body">
          ${rows || note("Add a goal (house, car, trip…) to see how much to set aside each month.")}
          ${fund}
          <details class="mt-m"><summary style="cursor:pointer; font-size:12px; color:var(--accent);">Add a goal</summary>
            <div class="mt-s" style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
              <input id="goal-name" placeholder="Name" style="${INPUT}"/>
              <input id="goal-target" type="number" min="1" placeholder="Target $" style="${INPUT}"/>
              <input id="goal-date" type="date" style="${INPUT}"/>
              <input id="goal-extra" type="number" min="0" placeholder="Already set aside $ (optional)" style="${INPUT}"/>
              <select id="goal-linked" multiple size="3" style="${INPUT} grid-column:1 / span 2;" title="Accounts whose balance counts toward this goal (optional)">${accts}</select>
            </div>
            <div class="flex gap-s mt-s"><button class="btn-primary" id="goal-add">Add goal</button><span id="goal-status" class="muted" style="font-size:12px;"></span></div>
          </details>
        </div>
      </div>`;
  }

  function whatIfCard() {
    const c = D.coastFire || {}, f = D.fire || {};
    const v = {
      retire_age: c.retireAge || 55, annual_spend: c.annualSpend || 0,
      monthly_contribution: f.monthlyContribution || 0, return_pct: c.returnPct || 7,
    };
    const field = (id, label, val, step) => `<label style="font-size:12px;">${label}<br/>
      <input id="wi-${id}" type="number" step="${step}" value="${val}" style="width:100%; margin-top:3px; ${INPUT}"/></label>`;
    return `
      <div class="card">
        <div class="card-head"><h3>What-if planner</h3><div class="meta">Try a change, compare to your plan</div></div>
        <div class="card-body">
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            ${field("retire_age", "Retire at age", v.retire_age, 1)}
            ${field("annual_spend", "Annual spending $", v.annual_spend, 1000)}
            ${field("monthly_contribution", "Monthly investing $", v.monthly_contribution, 100)}
            ${field("return_pct", "Assumed return %", v.return_pct, 0.5)}
          </div>
          <div class="flex gap-s mt-m"><button class="btn-primary" id="wi-run">Compare</button><span id="wi-status" class="muted" style="font-size:12px;"></span></div>
          <div id="wi-out" class="mt-m"></div>
        </div>
      </div>`;
  }

  function renderWhatIf(j) {
    const row = (label, a, b, fmt, d) => `
      <tr><td class="muted" style="padding:4px 8px 4px 0;">${label}</td><td style="text-align:right; padding:4px 8px;">${fmt(a)}</td>
      <td style="text-align:right; padding:4px 8px; font-weight:600;">${fmt(b)}</td>
      <td style="text-align:right; padding:4px 0 4px 8px; color:${d == null || d === 0 ? "var(--text-3)" : tone(d)};">${d == null ? "—" : d === 0 ? "same" : (d > 0 ? "+" : "") + (Math.abs(d) >= 1000 ? Math.round(d).toLocaleString() : d)}</td></tr>`;
    const money = (n) => usd(n, { compact: true });
    const age = (n) => (n == null ? "never" : "age " + n);
    const odds = (n) => (n == null ? "—" : n.toFixed(0) + "%");
    const B = j.baseline, S = j.scenario, d = j.delta;
    return `
      <table style="width:100%; font-size:12px; border-collapse:collapse;">
        <tr class="muted"><th></th><th style="text-align:right; padding:4px 8px;">Plan</th><th style="text-align:right; padding:4px 8px;">What-if</th><th></th></tr>
        ${row("FIRE number", B.fireNumber, S.fireNumber, money, d.fireNumber)}
        ${row("Reach FIRE at", B.fireAge, S.fireAge, age, d.fireAge)}
        ${row("Balance at retirement", B.projectedAtRetirement, S.projectedAtRetirement, money, d.projectedAtRetirement)}
        ${row("Chance of reaching FIRE number", B.fullFireOddsPct, S.fullFireOddsPct, odds, d.fullFireOddsPct)}
        ${row("CoastFIRE (stop investing today)", B.coastOddsPct, S.coastOddsPct, odds, d.coastOddsPct)}
      </table>
      <div class="mt-s">${note("Simulated random yearly returns (15% swings) — a probability, not a promise. Nothing here is saved.")}</div>`;
  }

  async function save(url, body, statusId) {
    const st = document.getElementById(statusId);
    if (st) st.textContent = "Saving…";
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.error || "failed");
      const snap = await (await fetch("/api/snapshot")).json();
      if (snap.ok && window.Nexus && Nexus.applySnapshotData) Nexus.applySnapshotData(snap);
    } catch (e) {
      if (st) st.textContent = "Couldn't save: " + e.message;
    }
  }

  function bindOnce(id, evt, fn) {
    const el = document.getElementById(id);
    if (el && !el.dataset.bound) { el.dataset.bound = "1"; el.addEventListener(evt, fn); }
  }

  function planningMoney() {
    return `<div class="grid g-2 mt-m">${goalsCard(D.goals)}${whatIfCard()}</div>`;
  }

  function hydratePlanningMoney() {
    bindOnce("goal-add", "click", async () => {
      const name = (document.getElementById("goal-name").value || "").trim();
      const target = parseFloat(document.getElementById("goal-target").value);
      if (!name || !(target > 0)) { document.getElementById("goal-status").textContent = "Name and a target are required"; return; }
      const linked = [...document.getElementById("goal-linked").selectedOptions].map((o) => o.value);
      const stored = await currentGoals();
      const goals = [...stored, { name, target, date: document.getElementById("goal-date").value || "",
        linked, extra: parseFloat(document.getElementById("goal-extra").value) || 0 }];
      await save("/api/goals", { goals }, "goal-status");
    });
    document.querySelectorAll("[data-goal-del]").forEach((b) => {
      if (b.dataset.bound) return;
      b.dataset.bound = "1";
      b.addEventListener("click", async () => {
        const stored = await currentGoals();
        await save("/api/goals", { goals: stored.filter((g) => g.id !== b.dataset.goalDel) }, "goal-status");
      });
    });
    bindOnce("wi-run", "click", async () => {
      const num = (id) => parseFloat(document.getElementById("wi-" + id).value);
      const body = { retire_age: num("retire_age"), annual_spend: num("annual_spend"),
        monthly_contribution: num("monthly_contribution"), return_pct: num("return_pct") };
      const st = document.getElementById("wi-status");
      st.textContent = "Running…";
      try {
        const r = await fetch("/api/whatif", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const j = await r.json();
        if (!r.ok || !j.ok) throw new Error(j.error || "failed");
        document.getElementById("wi-out").innerHTML = renderWhatIf(j);
        st.textContent = "";
      } catch (e) { st.textContent = "Couldn't run: " + e.message; }
    });
  }

  // The dashboard payload's goal rows carry progress only; the raw goals
  // (linked accounts, extra) are read back from GET /api/goals so edits never
  // drop them.
  async function currentGoals() {
    try {
      const r = await fetch("/api/goals");
      const j = await r.json();
      return j.goals || [];
    } catch (e) { return []; }
  }

  window.AppleSections = Object.assign(window.AppleSections || {}, {
    renderCashflow, hydrateCashflow, overviewTop, overviewMid, hydrateOverviewMoney,
    portfolioMoney, planningMoney, hydratePlanningMoney,
  });
})();
