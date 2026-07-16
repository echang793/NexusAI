// Shared portfolio data — real holdings from portfolio.json with plausible May 2026 prices.
// All three designs read from this file.

window.NEXUS_DATA = (() => {
  const profile = {
    name: "Alex Chen",
    age: 26,
    risk: "Aggressive",
    horizon: 30,
    goals: ["Retirement", "Wealth building", "Income"],
    income_stability: "Stable",
    emergency_fund: true,
    notes: "Saving for potential child expenses and early retirement",
  };

  // ticker, shares, avg_cost, current_price, sector, account
  const HOLDINGS = [
    ["NVDA", 33.3223, 95.76, 188.42, "Technology", "Brokerage"],
    ["VOO", 66.1567, 517.28, 668.10, "ETF · S&P 500", "Brokerage"],
    ["VUG", 91.8218, 57.29, 98.40, "ETF · Growth", "Roth IRA"],
    ["VTI", 17.4363, 264.22, 345.20, "ETF · Total Market", "Roth IRA"],
    ["AAPL", 14.1963, 213.04, 258.30, "Technology", "Brokerage"],
    ["PLTR", 25.0970, 78.57, 142.85, "Technology", "Brokerage"],
    ["MSFT", 5.9394, 352.26, 495.10, "Technology", "Brokerage"],
    ["AMZN", 10.4033, 150.29, 235.40, "Consumer Cyc.", "Brokerage"],
    ["META", 1.7279, 484.50, 718.90, "Communications", "Brokerage"],
    ["GOOG", 11.0835, 123.52, 245.10, "Communications", "Brokerage"],
    ["COST", 3.7421, 966.52, 1082.00, "Consumer Def.", "Brokerage"],
    ["AVGO", 7.3141, 242.37, 385.60, "Technology", "Brokerage"],
    ["TSLA", 5.6677, 372.81, 421.40, "Consumer Cyc.", "Brokerage"],
    ["JPM", 5.6195, 174.80, 325.20, "Financials", "Brokerage"],
    ["SPY", 8.6539, 479.94, 670.30, "ETF · S&P 500", "Brokerage"],
    ["QQQ", 2.3655, 392.26, 605.80, "ETF · Nasdaq", "Brokerage"],
    ["BRK-B", 4.2135, 404.73, 545.20, "Financials", "Brokerage"],
    ["TQQQ", 16.0000, 34.48, 98.40, "ETF · Leveraged", "Brokerage"],
    ["UPRO", 7.3694, 70.04, 148.60, "ETF · Leveraged", "Brokerage"],
    ["GLD", 6.2647, 322.82, 415.30, "Commodities", "Brokerage"],
    ["FBTC", 2.0000, 59.01, 115.40, "Crypto ETF", "Brokerage"],
    ["VXUS", 37.5736, 71.09, 86.40, "ETF · International", "Roth IRA"],
    ["WMT", 3.7446, 56.00, 112.80, "Consumer Def.", "Brokerage"],
    ["PANW", 5.1156, 153.38, 410.20, "Technology", "Brokerage"],
    ["CRWD", 1.2572, 365.88, 448.30, "Technology", "Brokerage"],
    ["ABBV", 2.1527, 151.21, 215.40, "Healthcare", "Brokerage"],
    ["FXAIX", 3.8100, 239.29, 315.40, "Mutual Fund", "401(k)"],
    ["MRVL", 6.7258, 113.69, 98.20, "Technology", "Brokerage"],
    ["AMD", 1.2716, 184.02, 145.30, "Technology", "Brokerage"],
    ["INTC", 5.0000, 118.15, 32.40, "Technology", "Brokerage"],
    ["APLD", 13.8543, 45.58, 32.80, "Technology", "Brokerage"],
    ["DRAM", 15.0000, 43.84, 25.40, "Technology", "Brokerage"],
    ["VSAT", 17.0000, 25.74, 18.30, "Communications", "Brokerage"],
    ["CVX", 1.0788, 165.02, 158.40, "Energy", "Brokerage"],
    ["RNMBY", 5.0000, 234.81, 310.20, "Industrials", "Brokerage"],
    ["FMAO", 12.0000, 21.66, 28.40, "Financials", "Brokerage"],
    ["SPYM", 2.0000, 57.35, 72.10, "ETF · S&P 500", "Brokerage"],
    ["SGOV", 10.0000, 100.41, 100.52, "Cash/T-Bills", "Brokerage"],
    ["MU", 7.4623, 657.73, 124.30, "Technology", "Brokerage"],  // odd avg_cost from source
    ["SNDK", 5.9413, 561.34, 248.20, "Technology", "Brokerage"],
    ["FFLEX", 22.0760, 22.20, 24.10, "Mutual Fund", "401(k)"],
    ["NON40OAA1", 28.2520, 528.73, 612.40, "Mutual Fund", "401(k)"],
    ["NON40OAA2", 283.8550, 4.14, 5.20, "Mutual Fund", "401(k)"],
    ["NON40OM1R", 2661.4850, 13.49, 15.40, "Mutual Fund", "401(k)"],
  ];

  const positions = HOLDINGS.map(([ticker, shares, avg_cost, price, sector, account]) => {
    const value = shares * price;
    const cost = shares * avg_cost;
    const pl = value - cost;
    const plPct = cost === 0 ? 0 : (pl / cost) * 100;
    return { ticker, shares, avg_cost, price, sector, account, value, cost, pl, plPct };
  });

  const portfolioValue = positions.reduce((s, p) => s + p.value, 0);
  positions.forEach(p => { p.weight = (p.value / portfolioValue) * 100; });
  positions.sort((a, b) => b.value - a.value);

  const totalCost = positions.reduce((s, p) => s + p.cost, 0);
  const totalPL = portfolioValue - totalCost;
  const totalPLPct = (totalPL / totalCost) * 100;

  // Accounts (user can edit these)
  const accounts = [
    { id: "brokerage", name: "Fidelity Brokerage", type: "Taxable", balance: positions.filter(p => p.account === "Brokerage").reduce((s,p)=>s+p.value,0), institution: "Fidelity" },
    { id: "roth", name: "Roth IRA", type: "Retirement", balance: positions.filter(p => p.account === "Roth IRA").reduce((s,p)=>s+p.value,0), institution: "Fidelity" },
    { id: "401k", name: "401(k) — Employer", type: "Retirement", balance: positions.filter(p => p.account === "401(k)").reduce((s,p)=>s+p.value,0), institution: "Fidelity NetBenefits" },
    { id: "checking", name: "Checking", type: "Cash", balance: 18420.50, institution: "Chase" },
    { id: "savings", name: "HYSA", type: "Cash", balance: 42150.00, institution: "Marcus" },
    { id: "crypto", name: "Crypto Wallet", type: "Crypto", balance: 8740.20, institution: "Coinbase" },
  ];

  const netWorth = accounts.reduce((s, a) => s + a.balance, 0);

  // Synthesize 24 months of net worth history with sensible growth + a couple drawdowns
  const netWorthHistory = (() => {
    const months = 24;
    const target = netWorth;
    const start = target * 0.42;
    const out = [];
    let v = start;
    for (let i = 0; i < months; i++) {
      const t = i / (months - 1);
      const trend = start + (target - start) * (t * t * (3 - 2 * t)); // smoothstep
      const noise = (Math.sin(i * 1.3) + Math.sin(i * 0.7)) * 0.018 * trend;
      const drawdown = (i === 6 ? -0.06 : i === 14 ? -0.04 : 0) * trend;
      v = trend + noise + drawdown;
      const d = new Date(2024, 5 + i, 1);
      out.push({ date: d, value: Math.round(v) });
    }
    out[out.length - 1].value = Math.round(target);
    return out;
  })();

  // Watchlist
  const watchlist = [
    { ticker: "NVDA", price: 188.42, buyBelow: 160, sellAbove: 220, note: "Trim into strength", change: 2.3 },
    { ticker: "TSM",  price: 215.40, buyBelow: 195, sellAbove: null, note: "Quality semis exposure", change: 0.9 },
    { ticker: "SCHD", price: 28.40,  buyBelow: 26,  sellAbove: null, note: "Dividend growth — for income sleeve", change: -0.2 },
    { ticker: "BND",  price: 73.20,  buyBelow: 72,  sellAbove: null, note: "Build bond allocation", change: 0.1 },
    { ticker: "VNQ",  price: 84.30,  buyBelow: 85,  sellAbove: null, note: "REIT exposure for diversification", change: -2.1 },
    { ticker: "DIS",  price: 112.30, buyBelow: 105, sellAbove: 140,  note: "Watching parks recovery", change: 1.4 },
  ];

  // Mock company news
  const news = [
    { headline: "NVIDIA Q1 results crush estimates as data-center revenue jumps 78%", source: "Reuters", time: "2h", ticker: "NVDA" },
    { headline: "Apple unveils Vision Air at $1,499 — analysts split on near-term sales impact", source: "Bloomberg", time: "5h", ticker: "AAPL" },
    { headline: "Fed minutes signal one more cut likely by Q3", source: "WSJ", time: "8h", ticker: "MACRO" },
    { headline: "Palantir wins $480M DoD AI contract, shares pop 6%", source: "CNBC", time: "1d", ticker: "PLTR" },
    { headline: "Microsoft Copilot enterprise seats surpass 18M", source: "The Information", time: "1d", ticker: "MSFT" },
    { headline: "Meta opens Llama 4 weights, raises capex guidance", source: "FT", time: "2d", ticker: "META" },
  ];

  // Featured ticker (for Analyze tab) — AAPL
  const featured = {
    ticker: "AAPL",
    name: "Apple Inc.",
    price: 258.30,
    change: 1.84,
    changePct: 0.72,
    sector: "Technology",
    industry: "Consumer Electronics",
    marketCap: "$3.89T",
    pe: 31.4,
    peFwd: 28.2,
    beta: 1.18,
    high52: 268.40,
    low52: 168.30,
    divYield: 0.42,
    annualDiv: 1.08,
    target: 275.00,
    rating: "Buy",
    nextEarnings: "2026-07-30 (64d)",
    signal: "BUY",
    action: "BUY",
    confidence: "medium",
    thesis: "Vision Air launch + Services hitting 24% margin gives a clear earnings tailwind into FY27. RSI at 41 and a recent SMA50 reclaim above SMA200 set up a constructive entry. Suggest DCA across 3 tranches over 6 weeks rather than a single buy — IV is elevated heading into the July print.",
    technical: "Golden cross confirmed Apr 18. RSI 41.2 — neither overbought nor oversold. MACD histogram flipped positive 9 days ago. Trading 4% below the analyst target.",
    fundamental: "P/E 31.4 is rich vs the 10-yr median of 26, but justified by Services growth and a $110B annual buyback. Margins expanding; net cash position $48B.",
    newsSummary: "Vision Air ($1,499) launches Sept 12. iPhone 18 cycle expected stronger than 17. China unit sales stabilizing per latest Counterpoint data.",
    risks: ["Regulatory pressure on App Store fees in the EU and US", "China demand soft after 4 consecutive quarters of YoY declines", "Premium valuation leaves little room for execution slippage"],
    catalysts: ["Vision Air launch Sept 12 — first mass-market spatial product", "iPhone 18 Pro super-cycle expected H2 FY27", "Services revenue inflecting toward $110B run-rate"],
  };

  // Daily price series for featured (last 250 days)
  const featuredHistory = (() => {
    const days = 250;
    const out = [];
    let p = 168;
    for (let i = 0; i < days; i++) {
      const trend = 168 + (258 - 168) * (i / (days - 1));
      const wobble = Math.sin(i * 0.11) * 6 + Math.sin(i * 0.27) * 3;
      const noise = (Math.random() - 0.5) * 2.4;
      p = trend + wobble + noise;
      const d = new Date(2025, 7, 1);
      d.setDate(d.getDate() + i);
      out.push({ date: d, close: +p.toFixed(2) });
    }
    out[out.length - 1].close = 258.30;
    // SMA50 and SMA200
    out.forEach((row, i) => {
      const s50 = out.slice(Math.max(0, i - 49), i + 1);
      const s200 = out.slice(Math.max(0, i - 199), i + 1);
      row.sma50 = s50.reduce((s, r) => s + r.close, 0) / s50.length;
      row.sma200 = i >= 199 ? s200.reduce((s, r) => s + r.close, 0) / 200 : null;
    });
    return out;
  })();

  // Sector aggregation
  const sectorWeights = (() => {
    const m = {};
    positions.forEach(p => { m[p.sector] = (m[p.sector] || 0) + p.weight; });
    return Object.entries(m).map(([sector, weight]) => ({ sector, weight })).sort((a, b) => b.weight - a.weight);
  })();

  // Advisor plan (rule-based result for aggressive / 30yr horizon)
  const advisorPlan = {
    fit: "Your portfolio is well-aligned with an aggressive 30-year retirement strategy, though it leans heavily into US tech — NVDA, AAPL, MSFT, GOOG, META, AVGO together are ~28% of net worth. Leveraged ETFs (TQQQ, UPRO) add convex tech exposure on top of that. Diversifiers (international, bonds, real assets) are present but underweight vs your stated goals.",
    targets: [
      { category: "US Equities", target: 65, current: 71.4, gap: 6.4 },
      { category: "International", target: 18, current: 6.2, gap: -11.8 },
      { category: "Bonds", target: 10, current: 1.1, gap: -8.9 },
      { category: "Real Assets / Crypto", target: 5, current: 7.8, gap: 2.8 },
      { category: "Cash / Defensive", target: 2, current: 13.5, gap: 11.5 },
    ],
    actions: [
      { priority: 1, action: "buy", ticker: "VXUS", desc: "Add ~$26,000 to reach 18% international", reason: "Closes the largest gap; you're 12pts under target on ex-US developed + emerging." },
      { priority: 2, action: "buy", ticker: "BND", desc: "Add ~$19,000 across 6 months via DCA", reason: "Stability ballast as you build toward family expenses. Even aggressive investors benefit from 10% bond floor." },
      { priority: 3, action: "trim", ticker: "TQQQ", desc: "Trim ~50% of TQQQ position", reason: "Leveraged ETFs decay over time. Lock the +185% gain on half; recycle into VTI/VXUS." },
      { priority: 4, action: "trim", ticker: "NVDA", desc: "Trim ~25% to lock $3,100/share avg gain", reason: "NVDA alone is 7.4% of net worth; concentration risk has crept up." },
      { priority: 5, action: "hold", ticker: "VOO/VTI", desc: "Hold core ETF stack", reason: "Forms a clean low-cost beta core; no action needed." },
    ],
    suggested: [
      { ticker: "VXUS", category: "International", weight: 18, rationale: "Total ex-US — broadest international exposure for the lowest fee." },
      { ticker: "BND",  category: "Bonds", weight: 10, rationale: "Total US bond market — your stability sleeve." },
      { ticker: "SCHD", category: "Dividend Growth", weight: 4, rationale: "Aligns with your income goal without sacrificing growth." },
      { ticker: "VNQ",  category: "Real Assets", weight: 3, rationale: "REIT exposure to round out the alternatives sleeve." },
    ],
    risks: [
      "Tech concentration: 6 names ≈ 28% of net worth",
      "Leveraged ETFs (TQQQ, UPRO) carry path-dependent decay; not buy-and-hold",
      "International + bonds materially below target",
      "INTC, MU and a few others are deep underwater — review tax-loss harvesting before year end",
    ],
    rebalance: "Quarterly, or when any category drifts >5% from target.",
  };

  // Chat seed
  const chatSeed = [
    { role: "user", content: "Why are you suggesting I trim NVDA when it's up 96%?" },
    { role: "assistant", content: "Two reasons. First, NVDA alone is 7.4% of your net worth — your overall semi/AI cluster (NVDA + AVGO + MU + AMD + MRVL) is ~13%. That's concentrated for a 26-year-old building toward family expenses. Second, you've made $3,100/share in gain; trimming 25% locks ~$25K of that without exiting the thesis. You'd still hold 25 shares and stay long the AI buildout. That said — if you have unused long-term capital loss carryforward, the trim is more efficient. If not, and you're in a high tax bracket, deferring is reasonable. Want me to look at a 15% trim instead?" },
  ];

  return {
    profile, positions, accounts,
    portfolioValue, totalCost, totalPL, totalPLPct, netWorth, netWorthHistory,
    watchlist, news, featured, featuredHistory, sectorWeights, advisorPlan, chatSeed,
  };
})();

// Helpers
window.fmt$ = (n, opts = {}) => {
  if (n == null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (opts.compact && abs >= 1_000_000) return (n >= 0 ? "$" : "-$") + (abs / 1_000_000).toFixed(2) + "M";
  if (opts.compact && abs >= 10_000) return (n >= 0 ? "$" : "-$") + (abs / 1_000).toFixed(1) + "K";
  const sign = n < 0 ? "-" : (opts.signed ? "+" : "");
  return sign + "$" + abs.toLocaleString("en-US", { minimumFractionDigits: opts.dec ?? 2, maximumFractionDigits: opts.dec ?? 2 });
};
window.fmtPct = (n, signed = true) => {
  if (n == null || isNaN(n)) return "—";
  const sign = n > 0 && signed ? "+" : "";
  return sign + n.toFixed(2) + "%";
};
window.fmtNum = (n, dec = 2) => {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
};
