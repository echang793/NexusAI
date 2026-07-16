// ============================================================
// NexusAI — Sleek layer
// Aurora field, spotlight, 3D tilt, sheen sweeps, chart comet,
// iridescent hero number. Registers each as a toggleable +
// replayable feature in the AppleAnim registry so the Tweaks
// panel picks them up automatically.
// ============================================================

(() => {
  const SPEED_MAP = { slow: 0.6, normal: 1, fast: 1.6 };

  const SLEEK_DEFAULTS = {
    aurora: true,
    glass: true,
    spotlight: true,
    tilt: true,
    sheen: true,
    tracer: true,
    herograd: true,
  };

  function init() {
    const A = window.AppleAnim;
    if (!A) return false;

    // ---- Merge defaults for keys older saved state won't have ----
    Object.entries(SLEEK_DEFAULTS).forEach(([k, v]) => {
      if (typeof A.state[k] === "undefined") A.state[k] = v;
    });

    // ============================================================
    // Body attributes (CSS reads these)
    // ============================================================
    function applySleekAttrs() {
      const b = document.body;
      Object.keys(SLEEK_DEFAULTS).forEach((k) => {
        b.setAttribute("data-anim-" + k, A.state[k] ? "on" : "off");
      });
    }

    // ============================================================
    // Aurora field
    // ============================================================
    function mountAurora() {
      if (document.querySelector(".aurora-layer")) return;
      const layer = document.createElement("div");
      layer.className = "aurora-layer";
      layer.setAttribute("aria-hidden", "true");
      layer.innerHTML = '<div class="aurora-blob b1"></div><div class="aurora-blob b2"></div><div class="aurora-blob b3"></div><div class="aurora-blob b4"></div>';
      document.body.prepend(layer);
    }
    function replayAurora() {
      const layer = document.querySelector(".aurora-layer");
      if (!layer) return;
      layer.querySelectorAll(".aurora-blob").forEach((b) => {
        b.style.animation = "none";
        void b.getBoundingClientRect();
        b.style.animation = "";
      });
    }

    // ============================================================
    // Cursor spotlight — one delegated listener
    // ============================================================
    function setupSpotlight() {
      const content = document.querySelector(".content");
      if (!content || content.dataset.spotlightWired) return;
      content.dataset.spotlightWired = "1";
      content.addEventListener("pointermove", (e) => {
        if (!A.state.master || !A.state.spotlight) return;
        const card = e.target.closest(".card");
        if (!card) return;
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left) + "px");
        card.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    }
    function replaySpotlight() {
      const card = document.querySelector(".section.active .card");
      if (!card) return;
      card.classList.add("spotlight-demo");
      const r = card.getBoundingClientRect();
      const t0 = performance.now();
      const dur = 1400 / (SPEED_MAP[A.state.speed] || 1);
      (function frame(now) {
        const t = Math.min(1, (now - t0) / dur);
        const ang = t * Math.PI * 2;
        card.style.setProperty("--mx", (r.width / 2 + Math.cos(ang) * r.width * 0.3) + "px");
        card.style.setProperty("--my", (r.height / 2 + Math.sin(ang) * r.height * 0.3) + "px");
        if (t < 1) requestAnimationFrame(frame);
        else card.classList.remove("spotlight-demo");
      })(performance.now());
    }

    // ============================================================
    // 3D hero tilt
    // ============================================================
    function setupTilt() {
      const content = document.querySelector(".content");
      if (!content || content.dataset.tiltWired) return;
      content.dataset.tiltWired = "1";
      let raf = null;
      content.addEventListener("pointermove", (e) => {
        if (!A.state.master || !A.state.tilt) return;
        const hero = e.target.closest(".card.hero");
        if (!hero) return;
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = null;
          const r = hero.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width - 0.5;
          const y = (e.clientY - r.top) / r.height - 0.5;
          hero.classList.add("tilting");
          hero.style.transform =
            "perspective(1100px) rotateX(" + (-y * 5).toFixed(2) + "deg) rotateY(" + (x * 7).toFixed(2) + "deg) translateZ(6px)";
        });
      });
      content.addEventListener("pointerout", (e) => {
        const hero = e.target.closest(".card.hero");
        if (!hero) return;
        if (e.relatedTarget && hero.contains(e.relatedTarget)) return;
        hero.classList.remove("tilting");
        hero.style.transform = "";
      });
    }
    function replayTilt() {
      if (window.Nexus && window.Nexus.getActive() !== "overview") window.Nexus.navigateTo("overview");
      setTimeout(() => {
        const hero = document.querySelector(".card.hero");
        if (!hero) return;
        const p = "perspective(1100px) ";
        hero.animate(
          [
            { transform: p + "rotateX(0deg) rotateY(0deg)" },
            { transform: p + "rotateX(4deg) rotateY(-6deg)" },
            { transform: p + "rotateX(-3deg) rotateY(5deg)" },
            { transform: p + "rotateX(0deg) rotateY(0deg)" },
          ],
          { duration: 1400 / (SPEED_MAP[A.state.speed] || 1), easing: "ease-in-out" }
        );
      }, 200);
    }

    // ============================================================
    // Sheen sweep across visible cards
    // ============================================================
    function runSheen() {
      if (!A.state.master || !A.state.sheen) return;
      const sec = document.querySelector(".section.active");
      if (!sec) return;
      sec.querySelectorAll(".card").forEach((card, i) => {
        if (card.querySelector(".sheen-streak")) return;
        if (getComputedStyle(card).position === "static") card.style.position = "relative";
        const s = document.createElement("i");
        s.className = "sheen-streak";
        s.style.setProperty("--sd", (i * 80) + "ms");
        card.appendChild(s);
        setTimeout(() => s.remove(), 2600);
      });
    }

    // ============================================================
    // Chart comet — glowing dot rides the line as it draws
    // ============================================================
    function addComet(container) {
      const svg = container && container.querySelector("svg");
      if (!svg) return;
      const path = [...svg.querySelectorAll("path")].find((p) => {
        const s = p.getAttribute("stroke");
        const f = p.getAttribute("fill");
        return s && s !== "none" && (!f || f === "none");
      });
      if (!path) return;
      svg.querySelectorAll(".chart-comet").forEach((c) => c.remove());
      const ns = "http://www.w3.org/2000/svg";
      const g = document.createElementNS(ns, "g");
      g.setAttribute("class", "chart-comet");
      const am = document.createElementNS(ns, "animateMotion");
      am.setAttribute("dur", (1.1 / (SPEED_MAP[A.state.speed] || 1)).toFixed(2) + "s");
      am.setAttribute("fill", "freeze");
      am.setAttribute("calcMode", "spline");
      am.setAttribute("keyTimes", "0;1");
      am.setAttribute("keySplines", "0.2 0.8 0.2 1");
      am.setAttribute("path", path.getAttribute("d"));
      const halo = document.createElementNS(ns, "circle");
      halo.setAttribute("class", "comet-halo");
      halo.setAttribute("r", "8");
      const core = document.createElementNS(ns, "circle");
      core.setAttribute("class", "comet-core");
      core.setAttribute("r", "3.5");
      g.appendChild(am);
      g.appendChild(halo);
      g.appendChild(core);
      svg.appendChild(g);
    }
    function patchChartRenderers() {
      if (window.__sleekChartsPatched) return;
      window.__sleekChartsPatched = true;
      const prevArea = window.renderAreaChart;
      const prevMulti = window.renderMultiLineChart;
      window.renderAreaChart = function (container, series, opts) {
        prevArea(container, series, opts);
        if (A.state.master && A.state.tracer) addComet(container);
      };
      window.renderMultiLineChart = function (container, series, opts) {
        prevMulti(container, series, opts);
        if (A.state.master && A.state.tracer) addComet(container);
      };
    }
    function redrawCharts() {
      if (window.AppleSections && window.AppleSections._redraw) {
        try { window.AppleSections._redraw(); } catch (e) {}
      } else if (window.Nexus && window.AppleSections) {
        const active = window.Nexus.getActive();
        const fn = window.AppleSections["hydrate" + active.charAt(0).toUpperCase() + active.slice(1)];
        if (fn) try { fn(); } catch (e) {}
      }
    }

    // ============================================================
    // Iridescent hero replay (one fast sweep)
    // ============================================================
    function replayHeroGrad() {
      const el = document.querySelector(".hero-value");
      if (!el) return;
      el.classList.remove("herograd-burst");
      void el.getBoundingClientRect();
      el.classList.add("herograd-burst");
      setTimeout(() => el.classList.remove("herograd-burst"), 2400);
    }

    // ============================================================
    // Register features in the AppleAnim registry
    // ============================================================
    A.features.push(
      { id: "aurora",    label: "Aurora background",    desc: "Drifting color field glows through the glass",   replay: replayAurora },
      { id: "glass",     label: "Frosted glass",        desc: "Translucent cards with gradient hairline",       replay: runSheen },
      { id: "spotlight", label: "Cursor spotlight",     desc: "Soft accent glow follows your pointer on cards", replay: replaySpotlight },
      { id: "tilt",      label: "3D hero tilt",         desc: "Net worth card tilts toward the cursor",         replay: replayTilt },
      { id: "sheen",     label: "Sheen sweep",          desc: "Light streak washes over cards on entry",        replay: runSheen },
      { id: "tracer",    label: "Chart comet",          desc: "Glowing dot rides the line as it draws",         replay: redrawCharts },
      { id: "herograd",  label: "Iridescent number",    desc: "Hero value shimmers with a slow gradient",       replay: replayHeroGrad }
    );

    // ============================================================
    // Wrap AppleAnim setters so sleek attrs + side effects apply
    // ============================================================
    const origSetFeature = A.setFeature.bind(A);
    A.setFeature = (id, on) => {
      origSetFeature(id, on);
      applySleekAttrs();
      if (id === "tilt" && !on) {
        const hero = document.querySelector(".card.hero");
        if (hero) { hero.style.transform = ""; hero.classList.remove("tilting"); }
      }
      if (id === "tracer") redrawCharts();
      if (id === "sheen" && on) runSheen();
    };
    const origSetMaster = A.setMaster.bind(A);
    A.setMaster = (on) => { origSetMaster(on); applySleekAttrs(); };
    const origSetSpeed = A.setSpeed.bind(A);
    A.setSpeed = (s) => { origSetSpeed(s); applySleekAttrs(); };
    const origReplayAll = A.replayAll.bind(A);
    A.replayAll = () => { origReplayAll(); runSheen(); };

    // Sheen on section change
    if (window.Nexus && !window.__sleekNavPatched) {
      window.__sleekNavPatched = true;
      const origNav = window.Nexus.navigateTo;
      window.Nexus.navigateTo = (sec) => {
        origNav(sec);
        setTimeout(runSheen, 140);
      };
    }

    // ============================================================
    // Boot
    // ============================================================
    A.save();
    applySleekAttrs();
    mountAurora();
    setupSpotlight();
    setupTilt();
    patchChartRenderers();
    redrawCharts(); // pick up the comet on the initially drawn chart
    setTimeout(runSheen, 350);

    // Belt & suspenders: make sure the Tweaks list includes sleek rows
    // even if it painted before we pushed features.
    setTimeout(() => {
      const list = document.getElementById("tw-anim-list");
      if (list && !list.querySelector('[data-fid="aurora"]') && list.children.length) {
        const PLAY_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20"></polygon></svg>';
        list.innerHTML = A.features.map((f) => `
          <div class="tweaks-anim-row" data-fid="${f.id}">
            <div class="tweaks-anim-swatch"></div>
            <div class="tweaks-anim-name-cell">
              <div class="tweaks-anim-name">${f.label}</div>
              <div class="tweaks-anim-desc">${f.desc}</div>
            </div>
            <button class="tweaks-anim-replay" data-replay="${f.id}" title="Replay this animation">${PLAY_ICON}</button>
            <button class="tweaks-toggle ${A.state[f.id] ? "on" : ""}" data-toggle="${f.id}" aria-label="Toggle ${f.label}"></button>
          </div>
        `).join("");
      }
    }, 700);

    return true;
  }

  function boot() {
    if (init()) return;
    const iv = setInterval(() => { if (init()) clearInterval(iv); }, 40);
    setTimeout(() => clearInterval(iv), 4000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
