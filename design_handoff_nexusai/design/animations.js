// ============================================================
// NexusAI — UX animation enhancements
// Layers on top of the existing dashboard without changing data.
// Each feature is independently toggleable + replayable.
// ============================================================

(() => {
  const SPEED_MAP = { slow: 0.6, normal: 1, fast: 1.6 };
  const LS_KEY = "nexus_anim_v1";

  const DEFAULTS = {
    master: true,
    section: true,
    reveal: true,
    counters: true,
    charts: true,
    donut: true,
    bars: true,
    sparks: true,
    nav: true,
    pills: true,
    hover: true,
    typing: true,
    pulse: true,
    theme: true,
    speed: "normal",
  };

  let state = loadState();
  function loadState() {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(LS_KEY) || "{}") }; }
    catch (e) { return { ...DEFAULTS }; }
  }
  function save() { try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch (e) {} }

  // ============================================================
  // Apply state to body data-attributes (CSS reads these)
  // ============================================================
  function applyState() {
    const body = document.body;
    body.setAttribute("data-anim-master",  state.master ? "on" : "off");
    body.setAttribute("data-anim-section", state.section ? "on" : "off");
    body.setAttribute("data-anim-reveal",  state.reveal ? "on" : "off");
    body.setAttribute("data-anim-charts",  state.charts ? "on" : "off");
    body.setAttribute("data-anim-donut",   state.donut ? "on" : "off");
    body.setAttribute("data-anim-bars",    state.bars ? "on" : "off");
    body.setAttribute("data-anim-sparks",  state.sparks ? "on" : "off");
    body.setAttribute("data-anim-nav",     state.nav ? "on" : "off");
    body.setAttribute("data-anim-pills",   state.pills ? "on" : "off");
    body.setAttribute("data-anim-hover",   state.hover ? "on" : "off");
    body.style.setProperty("--anim-speed", SPEED_MAP[state.speed] || 1);
  }

  // ============================================================
  // Utilities
  // ============================================================
  const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

  function countUp(el, to, opts = {}) {
    if (!el) return;
    const dur = (opts.duration || 1200) / (SPEED_MAP[state.speed] || 1);
    const dec = opts.decimals ?? 0;
    const prefix = opts.prefix || "";
    const suffix = opts.suffix || "";
    const isCurrency = opts.currency;
    const startVal = opts.from ?? 0;
    if (!state.master || !state.counters) {
      el.textContent = isCurrency
        ? prefix + Math.floor(to).toLocaleString() + suffix
        : prefix + to.toFixed(dec) + suffix;
      return;
    }
    const t0 = performance.now();
    el.classList.add("counting");
    function frame(now) {
      const t = Math.min(1, (now - t0) / dur);
      const v = startVal + (to - startVal) * easeOutCubic(t);
      el.textContent = isCurrency
        ? prefix + Math.floor(v).toLocaleString() + suffix
        : prefix + v.toFixed(dec) + suffix;
      if (t < 1) requestAnimationFrame(frame);
      else { el.classList.remove("counting"); }
    }
    requestAnimationFrame(frame);
  }

  // Mark an SVG path for stroke-dash draw-in
  function animatePath(pathEl, opts = {}) {
    if (!pathEl) return;
    try {
      const len = pathEl.getTotalLength();
      pathEl.style.setProperty("--len", len);
      pathEl.classList.remove("path-draw");
      // restart animation
      void pathEl.getBoundingClientRect();
      pathEl.classList.add("path-draw");
    } catch (e) { /* svg not laid out */ }
  }

  // Post-process a chart container — apply draw-in to its line paths + fade-in to area.
  function animateChartInContainer(container) {
    if (!container) return;
    const svg = container.querySelector("svg");
    if (!svg) return;
    // The line path is the non-area path (no fill, has stroke)
    const paths = [...svg.querySelectorAll("path")];
    paths.forEach((p) => {
      const fill = p.getAttribute("fill");
      const stroke = p.getAttribute("stroke");
      if (stroke && stroke !== "none" && (!fill || fill === "none")) {
        animatePath(p);
      } else if (fill && fill.startsWith("url(")) {
        p.classList.remove("area-fade");
        void p.getBoundingClientRect();
        p.classList.add("area-fade");
      }
    });
  }

  // Stagger bar widths: delay each bar in DOM order within its container
  function staggerBars(scope = document) {
    const bars = scope.querySelectorAll(".bar-fill[data-w]");
    if (!bars.length) return;
    // Group by parent .card to stagger per-card
    const byParent = new Map();
    bars.forEach((bar) => {
      const card = bar.closest(".card") || document;
      if (!byParent.has(card)) byParent.set(card, []);
      byParent.get(card).push(bar);
    });
    byParent.forEach((list) => {
      list.forEach((bar, i) => {
        bar.style.width = "0%";
        const delay = state.master && state.bars ? i * 60 : 0;
        bar.style.transitionDelay = delay + "ms";
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            bar.style.width = bar.dataset.w + "%";
          });
        });
      });
    });
  }

  // Sparkline post-process: attach --len to polyline for draw-in
  function animateSparks(scope = document) {
    const sparks = scope.querySelectorAll(".spark polyline");
    sparks.forEach((p, i) => {
      try {
        const len = p.getTotalLength();
        p.style.setProperty("--len", len);
        p.style.animationDelay = (i % 8) * 40 + "ms";
        p.classList.remove("anim-restart");
        void p.getBoundingClientRect();
        p.classList.add("anim-restart");
      } catch (e) {}
    });
  }

  // Sliding nav indicator
  function setupNavIndicator() {
    const nav = document.getElementById("nav");
    if (!nav || nav.querySelector(".nav-indicator")) return;
    const indicator = document.createElement("div");
    indicator.className = "nav-indicator";
    nav.appendChild(indicator);
    moveNavIndicator(indicator);
  }
  function moveNavIndicator(indicator) {
    const nav = document.getElementById("nav");
    if (!nav) return;
    indicator = indicator || nav.querySelector(".nav-indicator");
    if (!indicator) return;
    const active = nav.querySelector(".nav-item.active");
    if (!active) { indicator.classList.remove("ready"); return; }
    const navRect = nav.getBoundingClientRect();
    const itemRect = active.getBoundingClientRect();
    indicator.style.top = (itemRect.top - navRect.top) + "px";
    indicator.style.height = itemRect.height + "px";
    indicator.classList.add("ready");
  }

  // Range pill sliding indicator
  function setupPillIndicators() {
    document.querySelectorAll(".range-pills").forEach((pills) => {
      if (pills.querySelector(".pill-indicator")) return;
      const ind = document.createElement("div");
      ind.className = "pill-indicator";
      pills.prepend(ind);
      movePillIndicator(pills);
      pills.addEventListener("click", () => requestAnimationFrame(() => movePillIndicator(pills)));
    });
  }
  function movePillIndicator(pills) {
    const ind = pills.querySelector(".pill-indicator");
    if (!ind) return;
    const active = pills.querySelector("button.active");
    if (!active) { ind.classList.remove("ready"); return; }
    const pillsRect = pills.getBoundingClientRect();
    const r = active.getBoundingClientRect();
    ind.style.left = (r.left - pillsRect.left) + "px";
    ind.style.width = r.width + "px";
    ind.classList.add("ready");
  }

  // Card reveal on intersect
  let revealObs;
  function setupReveal() {
    if (revealObs) revealObs.disconnect();
    if (!state.master || !state.reveal) return;
    revealObs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          // Restart animation: remove if present, force reflow, re-add.
          e.target.classList.remove("card-enter");
          void e.target.getBoundingClientRect();
          e.target.classList.add("card-enter");
          revealObs.unobserve(e.target);
        }
      });
    }, { threshold: 0.05, root: document.querySelector(".main") });
    document.querySelectorAll(".content .card").forEach((card, i) => {
      // Stagger via animation-delay so it works even if IO fires all at once
      card.style.animationDelay = (i * 40) + "ms";
      revealObs.observe(card);
    });
  }
  function replayReveal() {
    document.querySelectorAll(".content .card").forEach((c) => {
      c.classList.remove("card-enter");
    });
    // Force reflow so the next add restarts the animation
    void document.body.getBoundingClientRect();
    setupReveal();
  }

  // Trigger the one-shot section enter animation on a freshly-activated section.
  // Belt-and-suspenders: animationend listener + setTimeout fallback so the
  // class is always cleaned up even if the animation never advances
  // (throttled tab, reduced-motion, snapshot capture).
  function playSectionEnter(sec) {
    if (!sec) return;
    sec.classList.remove("section-enter");
    void sec.getBoundingClientRect();
    sec.classList.add("section-enter");
    let cleared = false;
    const clear = () => {
      if (cleared) return;
      cleared = true;
      sec.classList.remove("section-enter");
      sec.removeEventListener("animationend", clear);
    };
    sec.addEventListener("animationend", clear);
    setTimeout(clear, 1200);
  }

  // Streaming/typing chat reply
  function streamText(el, text, opts = {}) {
    return new Promise((resolve) => {
      const charsPerTick = opts.charsPerTick || 2;
      const tick = (opts.tick || 18) / (SPEED_MAP[state.speed] || 1);
      el.classList.add("cursor-blink");
      let i = 0;
      const it = setInterval(() => {
        i += charsPerTick;
        el.textContent = text.slice(0, i);
        if (i >= text.length) {
          clearInterval(it);
          el.classList.remove("cursor-blink");
          resolve();
        }
      }, tick);
    });
  }

  // Theme swap with View Transitions
  function swapTheme(nextTheme, originEl) {
    const apply = () => {
      document.body.setAttribute("data-theme", nextTheme);
      // sync sidebar toggle visual + tweaks
      document.querySelectorAll("[data-theme-set]").forEach(b => b.classList.toggle("active", b.dataset.themeSet === nextTheme));
      // re-tint charts since CSS vars changed
      if (window.AppleSections && window.AppleSections._redraw) {
        requestAnimationFrame(() => { try { window.AppleSections._redraw(); } catch (e) {} });
      }
      if (window.NexusTweaks && window.NexusTweaks.syncTheme) window.NexusTweaks.syncTheme(nextTheme);
    };
    if (state.master && state.theme && document.startViewTransition) {
      let cx = "50%", cy = "50%";
      if (originEl) {
        const r = originEl.getBoundingClientRect();
        cx = (r.left + r.width / 2) + "px";
        cy = (r.top + r.height / 2) + "px";
      }
      document.documentElement.style.setProperty("--tx", cx);
      document.documentElement.style.setProperty("--ty", cy);
      document.startViewTransition(apply);
    } else {
      apply();
    }
  }

  // Live price flash — simulate ticking on watchlist/portfolio
  let priceTickerId = null;
  function startPriceTicker() {
    stopPriceTicker();
    if (!state.master || !state.pulse) return;
    priceTickerId = setInterval(() => {
      // Pick a couple visible price cells and bump them
      const targets = [
        ...document.querySelectorAll("#section-watchlist .wl-row [style*='tabular-nums']"),
        ...document.querySelectorAll("#section-portfolio .tbl td.h-strong"),
      ].filter(el => el.offsetParent !== null);
      if (!targets.length) return;
      const pick = targets[Math.floor(Math.random() * Math.min(targets.length, 12))];
      if (!pick) return;
      const up = Math.random() > 0.5;
      pick.classList.remove("tick-up", "tick-down");
      void pick.getBoundingClientRect();
      pick.classList.add(up ? "tick-up" : "tick-down");
    }, 1600);
  }
  function stopPriceTicker() {
    if (priceTickerId) clearInterval(priceTickerId);
    priceTickerId = null;
  }

  // Add pulse to triggered watchlist alert dots
  function pulseAlertDots() {
    document.querySelectorAll("#section-watchlist .wl-row").forEach((row) => {
      const status = row.querySelector(".wl-status");
      if (!status) return;
      const txt = status.textContent;
      const dot = status.querySelector(".dot");
      if (!dot) return;
      if (state.master && state.pulse && /hit/i.test(txt)) dot.classList.add("pulse");
      else dot.classList.remove("pulse");
    });
  }

  // Topbar title swap
  function swapTopbarTitle(text) {
    const el = document.getElementById("topbar-title");
    if (!el) return;
    if (!state.master || !state.section) { el.textContent = text; return; }
    el.classList.add("swapping");
    setTimeout(() => {
      el.textContent = text;
      el.classList.remove("swapping");
    }, 180);
  }

  // ============================================================
  // PATCH renderers so newly drawn SVG gets animated automatically
  // ============================================================
  function patchRenderers() {
    if (window.__nexusRenderersPatched) return;
    window.__nexusRenderersPatched = true;

    const origArea = window.renderAreaChart;
    const origMulti = window.renderMultiLineChart;
    const origDonut = window.renderDonut;

    window.renderAreaChart = function (container, series, opts) {
      origArea(container, series, opts);
      if (state.master && state.charts) animateChartInContainer(container);
    };
    window.renderMultiLineChart = function (container, series, opts) {
      origMulti(container, series, opts);
      if (state.master && state.charts) animateChartInContainer(container);
    };
    window.renderDonut = function (container, segments, opts) {
      // We rewrite the donut so each wedge sweeps in independently.
      const size = opts.size || 220;
      const stroke = opts.stroke || 22;
      const r = (size - stroke) / 2 - 2;
      const cx = size / 2, cy = size / 2;
      const total = segments.reduce((s, x) => s + x.value, 0);
      const circ = 2 * Math.PI * r;
      let offset = 0;
      let segs = "";
      if (total <= 0) {
        segs = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="${stroke}"/>`;
      } else {
        segments.forEach((s, i) => {
          const len = (s.value / total) * circ;
          const gap = circ - len;
          const delay = state.master && state.donut ? (i * 90) : 0;
          const useAnim = state.master && state.donut;
          if (useAnim) {
            segs += `<circle class="donut-seg" cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="${stroke}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})" style="--len:${len}; --gap:${gap}; --circ:${circ}; --d:${delay}ms;"/>`;
          } else {
            segs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="${stroke}" stroke-dasharray="${len} ${gap}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})"/>`;
          }
          offset += len;
        });
      }
      container.innerHTML = `<svg class="donut" viewBox="0 0 ${size} ${size}">${segs}
        <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="11" fill="var(--text-2)" font-weight="600" letter-spacing="0.06em">${opts.label || ""}</text>
        <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="22" font-weight="700" fill="var(--text)" letter-spacing="-0.02em">${opts.center || ""}</text>
      </svg>`;
    };
  }

  // ============================================================
  // Hook into AppleSections hydration
  // ============================================================
  function patchHydrate() {
    if (!window.AppleSections || window.__nexusHydratePatched) return;
    window.__nexusHydratePatched = true;
    const AS = window.AppleSections;

    const wrap = (name, after) => {
      const orig = AS[name];
      if (!orig) return;
      AS[name] = function (...args) {
        const r = orig.apply(this, args);
        try { after(); } catch (e) { console.warn(name + " anim hook failed", e); }
        return r;
      };
    };

    wrap("hydrateOverview", () => {
      // Hero count-up
      const D = window.NEXUS_DATA;
      const heroEl = document.querySelector(".hero-value");
      const centsEl = document.querySelector(".hero-cents");
      if (heroEl && D) {
        countUp(heroEl, Math.floor(D.netWorth), { prefix: "$", currency: true, duration: 1400 });
        if (centsEl) {
          centsEl.style.opacity = "0";
          setTimeout(() => {
            centsEl.style.transition = "opacity 400ms ease";
            centsEl.style.opacity = "1";
          }, 900);
        }
      }
      // Bars stagger (sector breakdown)
      requestAnimationFrame(() => staggerBars(document.getElementById("section-overview")));
      // Sparklines in movers
      requestAnimationFrame(() => animateSparks(document.getElementById("section-overview")));
      // Range pills indicator
      setTimeout(() => setupPillIndicators(), 0);
    });

    wrap("hydrateAnalyze", () => {
      requestAnimationFrame(() => setupPillIndicators());
    });

    wrap("hydratePortfolio", () => {
      const D = window.NEXUS_DATA;
      // Stat tiles count-up
      const tiles = document.querySelectorAll("#section-portfolio .stat-tile .v");
      if (tiles[0] && D) countUp(tiles[0], D.positions.reduce((s, p) => s + p.value, 0), { prefix: "$", currency: true, suffix: "", duration: 1200 });
      if (tiles[1] && D) countUp(tiles[1], D.totalCost, { prefix: "$", currency: true, duration: 1200 });
      // P/L tile — leave as-is (signed currency, fmt$ output)
      requestAnimationFrame(() => staggerBars(document.getElementById("section-portfolio")));
      requestAnimationFrame(() => animateSparks(document.getElementById("section-portfolio")));
    });

    wrap("hydrateWatchlist", () => {
      pulseAlertDots();
      // Stat tiles count-up
      const tiles = document.querySelectorAll("#section-watchlist .stat-tile .v");
      if (tiles[0]) countUp(tiles[0], window.NEXUS_DATA.watchlist.length, { duration: 800 });
    });

    wrap("hydrateAdvisor", () => {
      // Replace chat submit with streaming
      const input = document.getElementById("adv-input");
      const stream = document.getElementById("adv-stream");
      const send = document.getElementById("adv-send");
      if (!input || !stream || !send) return;

      // Clone to strip existing listeners (we re-attach the REAL /api/chat call
      // below, with the typing animation layered on top of the live LLM reply).
      const newSend = send.cloneNode(true);
      send.parentNode.replaceChild(newSend, send);
      const newInput = input.cloneNode(true);
      input.parentNode.replaceChild(newInput, input);

      const MAX_MSG = 2000;
      const history = [...(window.NEXUS_DATA && NEXUS_DATA.chatSeed ? NEXUS_DATA.chatSeed : [])];

      async function submit() {
        const v = newInput.value.trim();
        if (!v) return;
        if (v.length > MAX_MSG) { newInput.value = v.slice(0, MAX_MSG); return; }

        // User bubble — textContent is XSS-safe
        const u = document.createElement("div");
        u.className = "bubble user appear";
        u.textContent = v;
        stream.appendChild(u);
        newInput.value = "";
        newSend.disabled = true;
        stream.scrollTop = stream.scrollHeight;

        // Typing indicator
        const typing = document.createElement("div");
        typing.className = "bubble assistant typing appear";
        typing.innerHTML = "<span></span><span></span><span></span>";
        stream.appendChild(typing);
        stream.scrollTop = stream.scrollHeight;

        // Live token streaming via SSE
        let reply = "";
        let firstToken = true;
        const textNode = document.createTextNode("");
        try {
          const r = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: v, history }),
          });
          const reader = r.body.getReader();
          const dec = new TextDecoder();
          let buf = "";
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const lines = buf.split("\n\n");
            buf = lines.pop();
            for (const block of lines) {
              const m = block.match(/^data: (.*)$/s);
              if (!m) continue;
              let obj; try { obj = JSON.parse(m[1]); } catch { continue; }
              if (obj.done) continue;
              if (obj.delta) {
                if (firstToken) {  // swap typing dots → live text node
                  firstToken = false;
                  typing.classList.remove("typing");
                  typing.style.width = "";
                  typing.textContent = "";
                  typing.classList.add("cursor-blink");
                  typing.appendChild(textNode);
                }
                reply += obj.delta;
                textNode.textContent = reply;
                stream.scrollTop = stream.scrollHeight;
              }
            }
          }
        } catch (e) { /* fall through */ }

        typing.classList.remove("cursor-blink");
        if (!reply) { typing.classList.remove("typing"); typing.textContent = "Advisor unavailable right now."; }

        history.push({ role: "user", content: v });
        history.push({ role: "assistant", content: reply || "(no response)" });

        const src = document.createElement("div");
        src.className = "source";
        src.innerHTML = `${window.Icon ? window.Icon("sparkles", 10) : ""} Claude`;
        typing.appendChild(src);
        newSend.disabled = false;
        stream.scrollTop = stream.scrollHeight;
      }

      newSend.addEventListener("click", submit);
      newInput.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });

      // Animate existing bubbles in on first render
      [...stream.querySelectorAll(".bubble")].forEach((b, i) => {
        b.classList.add("appear");
        b.style.animationDelay = (i * 80) + "ms";
      });
    });
  }

  // ============================================================
  // Intercept nav + theme + topbar title
  // ============================================================
  function patchNexusNav() {
    if (!window.Nexus || window.__nexusNavPatched) return;
    window.__nexusNavPatched = true;
    const orig = window.Nexus.navigateTo;
    window.Nexus.navigateTo = function (sec) {
      orig(sec);
      moveNavIndicator();
      playSectionEnter(document.querySelector(".section.active"));
      const el = document.getElementById("topbar-title");
      if (el) {
        el.classList.add("swapping");
        requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("swapping")));
      }
    };
  }

  // Theme button — intercept clicks on sidebar toggle, swap via View Transition
  function patchThemeToggle() {
    const tt = document.getElementById("theme-toggle");
    if (!tt || tt.dataset.animPatched) return;
    tt.dataset.animPatched = "1";
    tt.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-theme-set]");
      if (!btn) return;
      // Intercept BEFORE default handler? The existing handler in index.html already swaps.
      // Strategy: we leave the existing handler alone and just trigger the visual reveal here.
      // The original handler sets the attribute synchronously. By calling swapTheme we re-do
      // it inside startViewTransition() for the reveal effect.
      if (state.master && state.theme && document.startViewTransition) {
        e.stopImmediatePropagation();
        e.preventDefault();
        swapTheme(btn.dataset.themeSet, btn);
      }
    }, true);
  }

  // ============================================================
  // REPLAY registry — features the Tweaks panel can re-trigger
  // ============================================================
  const FEATURES = [
    {
      id: "counters",
      label: "Number count-up",
      desc: "Hero net worth + stat tiles tick from 0 with shimmer",
      replay() {
        const D = window.NEXUS_DATA;
        const heroEl = document.querySelector(".hero-value");
        if (heroEl && D) countUp(heroEl, Math.floor(D.netWorth), { prefix: "$", currency: true, duration: 1400 });
        const overviewTiles = document.querySelectorAll("#section-overview .stat-tile .v");
        overviewTiles.forEach(t => {
          const n = parseFloat(t.textContent.replace(/[^\d.-]/g, ""));
          if (!isNaN(n)) countUp(t, n, { duration: 1000 });
        });
        const ptiles = document.querySelectorAll("#section-portfolio .stat-tile .v");
        ptiles.forEach(t => {
          const n = parseFloat(t.textContent.replace(/[^\d.-]/g, ""));
          if (!isNaN(n)) countUp(t, n, { duration: 1000, prefix: t.textContent.trim().startsWith("$") ? "$" : "", currency: true });
        });
      },
    },
    {
      id: "charts",
      label: "Chart line draw-in",
      desc: "Area/line paths sketch in, fill fades after",
      replay() {
        if (window.AppleSections && window.AppleSections._redraw) window.AppleSections._redraw();
      },
    },
    {
      id: "donut",
      label: "Donut wedge sweep",
      desc: "Each allocation slice draws around the ring",
      replay() {
        if (window.AppleSections && window.AppleSections.hydrateOverview && window.Nexus.getActive() === "overview") {
          // Re-render donut
          document.querySelectorAll("#ow-donut .donut-seg").forEach((c) => {
            c.style.animation = "none";
            void c.getBoundingClientRect();
            c.style.animation = "";
          });
        }
      },
    },
    {
      id: "bars",
      label: "Bar fill stagger",
      desc: "Sector & concentration bars grow in sequence",
      replay() {
        const active = "section-" + (window.Nexus ? window.Nexus.getActive() : "overview");
        const scope = document.getElementById(active) || document;
        staggerBars(scope);
      },
    },
    {
      id: "sparks",
      label: "Sparkline draw",
      desc: "Mini trend lines sketch in across rows",
      replay() {
        const active = "section-" + (window.Nexus ? window.Nexus.getActive() : "overview");
        const scope = document.getElementById(active) || document;
        animateSparks(scope);
      },
    },
    {
      id: "section",
      label: "Section cross-fade",
      desc: "Cards fade + slide in when switching nav",
      replay() {
        playSectionEnter(document.querySelector(".section.active"));
      },
    },
    {
      id: "reveal",
      label: "Card scroll-reveal",
      desc: "Cards rise into view as you scroll",
      replay() { replayReveal(); },
    },
    {
      id: "nav",
      label: "Sliding nav highlight",
      desc: "Active pill glides between sidebar items",
      replay() {
        const ind = document.querySelector("#nav .nav-indicator");
        if (ind) {
          // jiggle for demo
          const items = [...document.querySelectorAll("#nav .nav-item")];
          let i = 0;
          const cur = document.querySelector("#nav .nav-item.active");
          const seq = [items[0], items[2], items[4], cur].filter(Boolean);
          const step = () => {
            if (i >= seq.length) return;
            document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
            seq[i].classList.add("active");
            moveNavIndicator();
            i++;
            setTimeout(step, 320);
          };
          step();
        }
      },
    },
    {
      id: "pills",
      label: "Range pill slide",
      desc: "Selected timeframe pill glides into place",
      replay() {
        const pills = document.querySelector(".section.active .range-pills");
        if (!pills) return;
        const btns = [...pills.querySelectorAll("button[data-r]")];
        if (!btns.length) return;
        const cur = pills.querySelector("button.active") || btns[btns.length - 1];
        let i = 0;
        const seq = [btns[0], btns[3], cur];
        const step = () => {
          if (i >= seq.length) return;
          pills.querySelectorAll("button").forEach(b => b.classList.remove("active"));
          seq[i].classList.add("active");
          seq[i].click();
          movePillIndicator(pills);
          i++;
          setTimeout(step, 420);
        };
        step();
      },
    },
    {
      id: "typing",
      label: "Streaming AI reply",
      desc: "Advisor responses stream in with cursor",
      replay() {
        if (window.Nexus) window.Nexus.navigateTo("advisor");
        setTimeout(() => {
          const input = document.getElementById("adv-input");
          if (input) {
            input.value = "Show me how a streaming reply looks.";
            input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
          }
        }, 400);
      },
    },
    {
      id: "pulse",
      label: "Live price flash",
      desc: "Prices flash green/red on tick; alerts pulse",
      replay() {
        if (window.Nexus) window.Nexus.navigateTo("watchlist");
        setTimeout(() => {
          pulseAlertDots();
          // Manually pulse a few visible prices for the demo
          const targets = [...document.querySelectorAll("#section-watchlist [style*='tabular-nums']")].slice(0, 5);
          targets.forEach((el, i) => setTimeout(() => {
            el.classList.remove("tick-up", "tick-down");
            void el.getBoundingClientRect();
            el.classList.add(i % 2 === 0 ? "tick-up" : "tick-down");
          }, i * 200));
        }, 400);
      },
    },
    {
      id: "theme",
      label: "Theme reveal (circular)",
      desc: "Light/dark swap with circular wipe from toggle",
      replay() {
        const next = document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
        const btn = document.querySelector(`[data-theme-set="${next}"]`);
        swapTheme(next, btn);
      },
    },
    {
      id: "hover",
      label: "Card hover lift",
      desc: "Cards rise 2px with deeper shadow on hover",
      replay() {
        const card = document.querySelector(".section.active .card");
        if (card) {
          card.style.transform = "translateY(-2px)";
          card.style.boxShadow = "var(--shadow-pop)";
          card.style.transition = "transform 280ms var(--anim-ease), box-shadow 280ms var(--anim-ease)";
          setTimeout(() => { card.style.transform = ""; card.style.boxShadow = ""; }, 900);
        }
      },
    },
  ];

  // ============================================================
  // Toasts — global, used by all save flows
  // ============================================================
  window.NexusToast = (msg, kind = "ok", ms = 2600) => {
    let wrap = document.getElementById("nexus-toasts");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "nexus-toasts";
      document.body.appendChild(wrap);
    }
    const t = document.createElement("div");
    t.className = "nexus-toast " + kind;
    const dot = document.createElement("span"); dot.className = "dot";
    const span = document.createElement("span"); span.textContent = msg;  // XSS-safe
    t.appendChild(dot); t.appendChild(span);
    wrap.appendChild(t);
    setTimeout(() => {
      t.classList.add("out");
      setTimeout(() => t.remove(), 240);
    }, ms);
  };

  // ============================================================
  // Public API
  // ============================================================
  window.AppleAnim = {
    state,
    features: FEATURES,
    save,
    applyState,
    setFeature(id, on) { state[id] = on; save(); applyState(); reflectFeature(id); },
    setSpeed(s) { state.speed = s; save(); applyState(); },
    setMaster(on) { state.master = on; save(); applyState(); reflectAllFeatures(); },
    replay(id) {
      const f = FEATURES.find(x => x.id === id);
      if (f) f.replay();
    },
    replayAll() {
      const active = window.Nexus ? window.Nexus.getActive() : "overview";
      const fn = window.AppleSections["hydrate" + active.charAt(0).toUpperCase() + active.slice(1)];
      if (fn) fn();
      playSectionEnter(document.querySelector(".section.active"));
      replayReveal();
      moveNavIndicator();
      document.querySelectorAll(".range-pills").forEach(p => movePillIndicator(p));
    },
  };

  // Toggle a feature off/on requires some side effects (e.g. start/stop ticker, redraw donut)
  function reflectFeature(id) {
    if (id === "pulse") {
      if (state.master && state.pulse) startPriceTicker();
      else stopPriceTicker();
      pulseAlertDots();
    }
    if (id === "donut" || id === "charts") {
      if (window.AppleSections && window.AppleSections._redraw) window.AppleSections._redraw();
      if (window.Nexus && window.Nexus.getActive() === "overview" && window.AppleSections.hydrateOverview) {
        // refresh donut
        try { window.AppleSections.hydrateOverview(); } catch (e) {}
      }
    }
    if (id === "reveal") replayReveal();
    if (id === "nav") moveNavIndicator();
    if (id === "pills") document.querySelectorAll(".range-pills").forEach(p => movePillIndicator(p));
  }
  function reflectAllFeatures() {
    FEATURES.forEach(f => reflectFeature(f.id));
  }

  // ============================================================
  // Init
  // ============================================================
  function init() {
    applyState();
    patchRenderers();
    // wait until other modules initialized
    const tryHook = () => {
      if (window.AppleSections && window.Nexus) {
        patchHydrate();
        patchNexusNav();
        patchThemeToggle();
        setupNavIndicator();
        setupPillIndicators();
        setupReveal();
        // Initial section enter (one-shot)
        playSectionEnter(document.querySelector(".section.active"));
        // run hydrate for current section so animations apply on initial load
        if (window.AppleSections.hydrateOverview) window.AppleSections.hydrateOverview();
        startPriceTicker();
        // Re-position nav indicator on resize
        window.addEventListener("resize", () => {
          moveNavIndicator();
          document.querySelectorAll(".range-pills").forEach(p => movePillIndicator(p));
        });
        return true;
      }
      return false;
    };
    if (!tryHook()) {
      const iv = setInterval(() => { if (tryHook()) clearInterval(iv); }, 30);
      setTimeout(() => clearInterval(iv), 3000);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
