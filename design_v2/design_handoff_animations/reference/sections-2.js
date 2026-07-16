// NexusAI Apple-like — Portfolio, Watchlist, Advisor sections
(() => {
  const D = window.NEXUS_DATA;

  // ============================================================
  // PORTFOLIO
  // ============================================================
  function renderPortfolio() {
    const totalValue = D.positions.reduce((s, p) => s + p.value, 0);
    return `
      <div class="grid g-3 mb-m">
        <div class="stat-tile">
          <div class="label">Total value</div>
          <div class="v">${fmt$(totalValue, { dec: 2 })}</div>
          <div class="e">${D.positions.length} positions</div>
        </div>
        <div class="stat-tile">
          <div class="label">Total cost basis</div>
          <div class="v">${fmt$(D.totalCost, { dec: 2 })}</div>
          <div class="e">Across 4 accounts</div>
        </div>
        <div class="stat-tile">
          <div class="label">Unrealized P/L</div>
          <div class="v ${D.totalPL >= 0 ? 'pl-pos' : 'pl-neg'}">${fmt$(D.totalPL, { signed: true })}</div>
          <div class="e ${D.totalPL >= 0 ? 'pl-pos' : 'pl-neg'}">${fmtPct(D.totalPLPct)}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Holdings</h3>
          <div class="flex gap-s">
            <button class="btn-ghost">${Icon("plus", 12)} Import CSV</button>
            <button class="btn-primary">${Icon("sparkles", 12)} Analyze portfolio</button>
          </div>
        </div>
        <div style="overflow-x:auto;">
          <table class="tbl">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Account</th>
                <th class="t-right">Shares</th>
                <th class="t-right">Avg cost</th>
                <th class="t-right">Price</th>
                <th class="t-right">Value</th>
                <th class="t-right">Weight</th>
                <th class="t-right">P/L</th>
                <th class="t-right">Trend</th>
              </tr>
            </thead>
            <tbody>
              ${D.positions.map(p => `
                <tr data-row-ticker="${p.ticker}">
                  <td>
                    <div class="t-ticker">
                      <div class="tkr-glyph">${p.ticker.slice(0, 3)}</div>
                      <div>
                        <div>${p.ticker}</div>
                        <div class="muted" style="font-size:11px; font-weight:400;">${p.sector}</div>
                      </div>
                    </div>
                  </td>
                  <td><span class="muted">${p.account}</span></td>
                  <td class="t-right">${fmtNum(p.shares, 4)}</td>
                  <td class="t-right">${fmt$(p.avg_cost)}</td>
                  <td class="t-right h-strong">${fmt$(p.price)}</td>
                  <td class="t-right h-strong">${fmt$(p.value)}</td>
                  <td class="t-right">${p.weight.toFixed(2)}%</td>
                  <td class="t-right ${p.pl >= 0 ? 'pl-pos' : 'pl-neg'}">
                    <div style="font-weight:600;">${fmtPct(p.plPct)}</div>
                    <div style="font-size:11px;">${fmt$(p.pl, { signed: true, compact: true })}</div>
                  </td>
                  <td class="t-right">${renderSparkline(syntheticSpark(p.plPct), { w: 64, h: 18 })}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>

      <div class="grid g-2 mt-m">
        <div class="card">
          <div class="card-head"><h3>Risk metrics</h3><div class="meta">Trailing 2Y</div></div>
          <div class="card-body">
            <div class="grid g-3" style="gap:10px;">
              <div class="stat-tile"><div class="label">Portfolio Sharpe</div><div class="v">1.28</div><div class="e">vs SPY 1.04</div></div>
              <div class="stat-tile"><div class="label">Max drawdown</div><div class="v">−18.4%</div><div class="e">Oct 2024</div></div>
              <div class="stat-tile"><div class="label">Sortino</div><div class="v">1.82</div><div class="e">Strong downside-adj</div></div>
            </div>
            <div class="divider"></div>
            <div style="font-size:13px; color:var(--text-2); line-height:1.55;">
              Risk-adjusted returns outpace SPY thanks to your AI/semis concentration. But that concentration is also where the max-drawdown risk lives — see the Advisor for trim suggestions.
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h3>Concentration</h3><div class="meta">Position weight</div></div>
          <div class="card-body">
            ${D.positions.slice(0, 6).map(p => `
              <div class="bar-row">
                <span>${p.ticker}</span>
                <div class="bar-track"><div class="bar-fill" style="width:0%;" data-w="${p.weight}"></div></div>
                <span class="t-right h-strong">${p.weight.toFixed(2)}%</span>
              </div>
            `).join("")}
            <div class="risk-item mt-m">${Icon("alert", 14)}<span>Top 6 positions = ${D.positions.slice(0,6).reduce((s,p)=>s+p.weight,0).toFixed(1)}% of portfolio. Consider trimming any &gt;7%.</span></div>
          </div>
        </div>
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

  function hydratePortfolio() {
    requestAnimationFrame(() => {
      document.querySelectorAll("[data-w]").forEach(el => { el.style.width = el.dataset.w + "%"; });
    });
  }

  // ============================================================
  // WATCHLIST
  // ============================================================
  function renderWatchlist() {
    return `
      <div class="grid g-3 mb-m">
        <div class="stat-tile"><div class="label">Watching</div><div class="v">${D.watchlist.length}</div><div class="e">tickers</div></div>
        <div class="stat-tile"><div class="label">Alerts triggered</div><div class="v" style="color:var(--green);">1</div><div class="e">VNQ near buy target</div></div>
        <div class="stat-tile"><div class="label">Avg time held</div><div class="v">2.3<span style="font-size:14px; color:var(--text-2)"> mo</span></div><div class="e">on watchlist</div></div>
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Watchlist</h3>
          <button class="btn-primary">${Icon("plus", 12)} Add ticker</button>
        </div>
        <div>
          ${D.watchlist.map(w => {
            const buyHit = w.buyBelow && w.price <= w.buyBelow;
            const sellHit = w.sellAbove && w.price >= w.sellAbove;
            const status = buyHit ? "BUY target hit" : sellHit ? "SELL target hit" : "Monitoring";
            const dot = buyHit ? "green" : sellHit ? "red" : "amber";
            const buyDist = w.buyBelow ? ((w.price - w.buyBelow) / w.buyBelow * 100) : null;
            return `
              <div class="wl-row" data-row-ticker="${w.ticker}">
                <div class="t-ticker">
                  <div class="tkr-glyph">${w.ticker.slice(0, 3)}</div>
                  <div>
                    <div style="font-weight:600;">${w.ticker}</div>
                    <div class="muted" style="font-size:11px;">${w.note}</div>
                  </div>
                </div>
                <div>
                  <div style="font-weight:600; font-variant-numeric: tabular-nums;">${fmt$(w.price)}</div>
                  <div class="delta ${w.change >= 0 ? 'up' : 'down'}" style="font-size:11px; padding:1px 6px;">${fmtPct(w.change)}</div>
                </div>
                <div class="wl-target">
                  <span class="pill">BUY ≤ ${w.buyBelow ? '$' + w.buyBelow : '—'}</span>
                  ${w.sellAbove ? `<span class="pill">SELL ≥ $${w.sellAbove}</span>` : ''}
                  ${buyDist !== null ? `<span class="muted" style="font-size:11px;">${buyDist > 0 ? '+' : ''}${buyDist.toFixed(1)}%</span>` : ''}
                </div>
                <div class="wl-status">
                  <span class="dot ${dot}"></span>${status}
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </div>

      <div class="card mt-m">
        <div class="card-head"><h3>Macro & company news</h3></div>
        <div class="card-body">
          ${D.news.map(n => `
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
    `;
  }

  function hydrateWatchlist() {}

  // ============================================================
  // ADVISOR
  // ============================================================
  function renderAdvisor() {
    const plan = D.advisorPlan;
    return `
      <div class="grid" style="grid-template-columns: 1.5fr 1fr; gap: 16px;">
        <div>
          <!-- Profile chip -->
          <div class="card card-pad">
            <div class="flex-between">
              <div class="flex gap-m">
                <div class="avatar" style="width:42px; height:42px; font-size:16px;">${D.profile.name.split(" ").map(s=>s[0]).join("")}</div>
                <div>
                  <div style="font-weight:600; font-size:15px;">${D.profile.name}</div>
                  <div class="muted" style="font-size:12px;">${D.profile.age} · ${D.profile.risk} · ${D.profile.horizon}yr horizon · ${D.profile.goals.join(", ")}</div>
                </div>
              </div>
              <button class="btn-ghost">${Icon("edit", 12)} Edit profile</button>
            </div>
          </div>

          <!-- Fit assessment -->
          <div class="card mt-m hero" style="padding-top:22px;">
            <div class="flex gap-s">
              <span class="verdict-pill" style="background:var(--accent); color:white;">${Icon("sparkles", 11)} PLAN GENERATED</span>
              <span class="muted" style="font-size:11px;">Claude advisor · 2 min ago</span>
            </div>
            <div style="font-size:14px; line-height:1.6; margin-top:14px;">${plan.fit}</div>
          </div>

          <!-- Targets -->
          <div class="card mt-m">
            <div class="card-head"><h3>Target allocation</h3><div class="meta">Aggressive · 30yr horizon</div></div>
            <div class="card-body">
              ${plan.targets.map(t => `
                <div class="alloc-row">
                  <div class="label-cell">${t.category}</div>
                  <div class="vs">
                    <div style="flex:1;">
                      <div style="font-size:11px; color:var(--text-2); margin-bottom:2px;">Current ${t.current.toFixed(1)}% → Target ${t.target.toFixed(0)}%</div>
                      <div style="position:relative; height:8px; background:var(--surface-2); border-radius:4px; overflow:hidden;">
                        <div style="position:absolute; left:0; top:0; bottom:0; width:${t.current}%; background:${t.gap >= 0 ? 'var(--amber)' : 'var(--accent)'}; opacity:0.5;"></div>
                        <div style="position:absolute; left:${t.target}%; top:-2px; bottom:-2px; width:2px; background:var(--text);"></div>
                      </div>
                    </div>
                  </div>
                  <div class="alloc-gap ${t.gap >= 0 ? 'pos' : 'neg'}">${(t.gap > 0 ? '+' : '') + t.gap.toFixed(1)}%</div>
                  <div><span class="alloc-action ${t.gap < -3 ? 'increase' : t.gap > 3 ? 'reduce' : 'ontarget'}">${t.gap < -3 ? 'Buy' : t.gap > 3 ? 'Trim' : 'Hold'}</span></div>
                </div>
              `).join("")}
            </div>
          </div>

          <!-- Action items -->
          <div class="card mt-m">
            <div class="card-head"><h3>Action items</h3><div class="meta">In priority order</div></div>
            <div class="card-body">
              ${plan.actions.map(a => `
                <div class="action-item">
                  <div class="action-priority">${a.priority}</div>
                  <div>
                    <div class="action-title">
                      <span class="action-tag ${a.action}">${a.action}</span>
                      <span style="font-family:ui-monospace, 'SF Mono', monospace; font-size:13px;">${a.ticker}</span>
                    </div>
                    <div class="action-desc">${a.desc}</div>
                    <div class="action-reason">${a.reason}</div>
                  </div>
                  <button class="btn-ghost">${a.action === "buy" ? "Set buy alert" : a.action === "trim" ? "Set sell alert" : "Mark done"}</button>
                </div>
              `).join("")}
            </div>
          </div>

          <!-- Suggested tickers -->
          <div class="card mt-m">
            <div class="card-head"><h3>Suggested to fill gaps</h3></div>
            <div class="card-body">
              <div class="grid g-2">
                ${plan.suggested.map(s => `
                  <div class="suggested-card">
                    <div class="flex-between" style="align-items: flex-start;">
                      <div>
                        <div class="suggested-ticker">${s.ticker}</div>
                        <div class="suggested-cat">${s.category} · target ${s.weight}%</div>
                      </div>
                      <button class="btn-ghost" style="padding:5px 8px;">${Icon("plus", 12)}</button>
                    </div>
                    <div class="suggested-rationale">${s.rationale}</div>
                  </div>
                `).join("")}
              </div>
            </div>
          </div>

          <!-- Risks -->
          <div class="card mt-m mb-m">
            <div class="card-head"><h3>Risks to watch</h3></div>
            <div class="card-body">
              ${plan.risks.map(r => `<div class="risk-item">${Icon("alert", 14)}<span>${r}</span></div>`).join("")}
              <div class="muted mt-m" style="font-size:12px;">${Icon("info", 12)} Rebalance ${plan.rebalance.toLowerCase()}</div>
            </div>
          </div>
        </div>

        <!-- Chat panel -->
        <div>
          <div class="card chat-shell" style="position:sticky; top:84px;">
            <div class="card-head"><h3>${Icon("sparkles", 14)} Discuss with advisor</h3><div class="meta">Conversational</div></div>
            <div class="chat-stream" id="adv-stream">
              <div class="bubble assistant">
                I built your plan from your aggressive / 30yr profile + 44 holdings. Biggest gaps: <strong>international (−12pts)</strong> and <strong>bonds (−9pts)</strong>. Two semis-related names (NVDA, AVGO) and your leveraged ETFs are areas I'd reduce. Ask me anything — challenge me where you disagree.
                <div class="source">${Icon("sparkles", 10)} Claude</div>
              </div>
              ${D.chatSeed.map(m => `
                <div class="bubble ${m.role}">
                  ${m.content}${m.role === "assistant" ? `<div class="source">${Icon("sparkles", 10)} Claude</div>` : ""}
                </div>
              `).join("")}
            </div>
            <div class="chat-input">
              <input id="adv-input" placeholder="Ask anything about your plan..."/>
              <button class="btn-primary" id="adv-send">${Icon("send", 12)}</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function hydrateAdvisor() {
    const input = document.getElementById("adv-input");
    const stream = document.getElementById("adv-stream");
    const send = document.getElementById("adv-send");
    if (!input || !stream) return;

    const submit = () => {
      const v = input.value.trim();
      if (!v) return;
      stream.insertAdjacentHTML("beforeend", `<div class="bubble user">${v}</div>`);
      input.value = "";
      stream.scrollTop = stream.scrollHeight;
      setTimeout(() => {
        const replies = [
          "Good question. Based on your current allocation, the biggest leverage is on the international sleeve — VXUS at ~$26K closes the gap without touching anything you already love. Want me to model a 12-month DCA schedule?",
          "Fair point. If your conviction on the semis cycle is strong, holding NVDA full size is defensible — but I'd then want bonds and international up by a few points to balance the tail risk. Trade-off, not a hard rule.",
          "I'd watch the tax cost. If your gain on TQQQ is $3.5K, harvesting it now vs. waiting depends on whether you have offsetting losses elsewhere. INTC at −72% is one such candidate.",
        ];
        stream.insertAdjacentHTML("beforeend", `<div class="bubble assistant">${replies[Math.floor(Math.random()*replies.length)]}<div class="source">${Icon("sparkles", 10)} Claude</div></div>`);
        stream.scrollTop = stream.scrollHeight;
      }, 700);
    };
    send.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    stream.scrollTop = stream.scrollHeight;
  }

  // Merge
  Object.assign(window.AppleSections, { renderPortfolio, hydratePortfolio, renderWatchlist, hydrateWatchlist, renderAdvisor, hydrateAdvisor });
})();
