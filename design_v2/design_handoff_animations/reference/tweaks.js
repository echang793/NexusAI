// Vanilla Tweaks panel — host protocol + live theme/accent/density controls.
// Persists to localStorage so refreshes keep your choices.
(() => {
  const LS_KEY = "nexus_tweaks_v1";
  const DEFAULTS = { accent: "blue", density: "regular", theme: "light" };

  const ACCENTS = {
    blue:   { light: "#0066ff", dark: "#0a84ff", name: "Blue" },
    purple: { light: "#8b5cf6", dark: "#a78bfa", name: "Purple" },
    green:  { light: "#00a96e", dark: "#30d158", name: "Green" },
    orange: { light: "#f5810a", dark: "#ff9f0a", name: "Amber" },
    pink:   { light: "#f5396b", dark: "#ff476f", name: "Pink" },
  };

  let state = loadState();

  function loadState() {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(LS_KEY) || "{}") }; }
    catch (e) { return { ...DEFAULTS }; }
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch (e) {}
    // host protocol: persist edits to disk EDITMODE block if running in host
    window.parent.postMessage({ type: "__edit_mode_set_keys", edits: state }, "*");
  }

  function hexToRgb(hex) {
    const h = hex.replace("#", "");
    return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
  }

  // ---- Appliers ----
  function applyAccent() {
    const a = ACCENTS[state.accent] || ACCENTS.blue;
    const mode = document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
    const col = a[mode];
    const [r,g,b] = hexToRgb(col);
    document.body.style.setProperty("--accent", col);
    document.body.style.setProperty("--accent-soft", `rgba(${r}, ${g}, ${b}, ${mode === "dark" ? 0.18 : 0.12})`);
    redrawCharts();
  }
  function applyDensity() {
    document.body.setAttribute("data-density", state.density);
  }
  function applyTheme() {
    document.body.setAttribute("data-theme", state.theme);
    // sync the sidebar toggle
    document.querySelectorAll("[data-theme-set]").forEach(b => b.classList.toggle("active", b.dataset.themeSet === state.theme));
    applyAccent(); // accent shade depends on theme
  }
  function applyAll() { applyTheme(); applyDensity(); }

  function redrawCharts() {
    if (window.AppleSections && AppleSections._redraw) {
      // slight delay so CSS var is committed before SVG reads it
      requestAnimationFrame(() => { try { AppleSections._redraw(); } catch(e){} });
    }
  }

  // ---- Panel UI ----
  // Small inline icons used by the Animations list
  const REPLAY_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>`;
  const PLAY_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20"/></svg>`;

  function buildPanel() {
    const panel = document.createElement("div");
    panel.className = "tweaks-panel wide";
    panel.id = "tweaks-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="tweaks-head">
        <div class="tweaks-title">${Icon("sliders", 15)} Tweaks</div>
        <button class="tweaks-close" id="tweaks-close">${Icon("x", 16)}</button>
      </div>
      <div class="tweaks-body" style="max-height:78vh; overflow-y:auto;">
        <div class="tweaks-section" style="margin-top:0;">${Icon("activity", 11)} Animations</div>
        <div class="tweaks-master-row">
          <div class="label">Animations enabled</div>
          <button class="tweaks-toggle on" id="tw-anim-master" aria-label="Toggle all animations"></button>
        </div>
        <div class="tweaks-speed" id="tw-anim-speed">
          <button data-speed="slow">Slow</button>
          <button data-speed="normal" class="active">Normal</button>
          <button data-speed="fast">Fast</button>
        </div>
        <div style="margin-top:10px;"><button class="tweaks-replay-all" id="tw-replay-all">${REPLAY_ICON} Replay current view</button></div>
        <div class="tweaks-anim-list" id="tw-anim-list"></div>

        <div class="tweaks-section">Accent</div>
        <div class="tweaks-swatches" id="tw-accent">
          ${Object.entries(ACCENTS).map(([k,v]) => `
            <button class="tw-swatch ${state.accent===k?'active':''}" data-accent="${k}" title="${v.name}">
              <span style="background:${v.light}"></span>
            </button>`).join("")}
        </div>

        <div class="tweaks-section">Density</div>
        <div class="tweaks-seg" id="tw-density">
          ${["compact","regular","comfy"].map(d => `<button class="${state.density===d?'active':''}" data-density="${d}">${d[0].toUpperCase()+d.slice(1)}</button>`).join("")}
        </div>

        <div class="tweaks-section">Theme</div>
        <div class="tweaks-seg" id="tw-theme">
          ${["light","dark"].map(t => `<button class="${state.theme===t?'active':''}" data-theme-opt="${t}">${Icon(t==='light'?'sun':'moon', 13)} ${t[0].toUpperCase()+t.slice(1)}</button>`).join("")}
        </div>
      </div>
    `;
    document.body.appendChild(panel);
    buildAnimationsSection(panel);

    panel.querySelector("#tweaks-close").addEventListener("click", dismiss);

    panel.querySelector("#tw-accent").addEventListener("click", e => {
      const b = e.target.closest("[data-accent]"); if (!b) return;
      state.accent = b.dataset.accent;
      panel.querySelectorAll("#tw-accent .tw-swatch").forEach(s => s.classList.toggle("active", s.dataset.accent === state.accent));
      applyAccent(); save();
    });
    panel.querySelector("#tw-density").addEventListener("click", e => {
      const b = e.target.closest("[data-density]"); if (!b) return;
      state.density = b.dataset.density;
      panel.querySelectorAll("#tw-density button").forEach(s => s.classList.toggle("active", s.dataset.density === state.density));
      applyDensity(); save();
    });
    panel.querySelector("#tw-theme").addEventListener("click", e => {
      const b = e.target.closest("[data-theme-opt]"); if (!b) return;
      state.theme = b.dataset.themeOpt;
      panel.querySelectorAll("#tw-theme button").forEach(s => s.classList.toggle("active", s.dataset.themeOpt === state.theme));
      applyTheme(); save();
    });

    return panel;
  }

  // Render the Animations feature list (toggle + replay per feature).
  // Runs once AppleAnim is available; if not yet, polls briefly.
  function buildAnimationsSection(panel) {
    const list = panel.querySelector("#tw-anim-list");
    const master = panel.querySelector("#tw-anim-master");
    const speed = panel.querySelector("#tw-anim-speed");
    const replayAll = panel.querySelector("#tw-replay-all");
    if (!list) return;

    function paint() {
      const A = window.AppleAnim;
      if (!A) return false;
      // Master toggle visual
      master.classList.toggle("on", !!A.state.master);
      // Speed visual
      speed.querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.speed === A.state.speed));
      // Feature rows
      list.innerHTML = A.features.map(f => `
        <div class="tweaks-anim-row" data-fid="${f.id}">
          <div class="tweaks-anim-swatch"></div>
          <div class="tweaks-anim-name-cell">
            <div class="tweaks-anim-name">${f.label}</div>
            <div class="tweaks-anim-desc">${f.desc}</div>
          </div>
          <button class="tweaks-anim-replay" data-replay="${f.id}" title="Replay this animation">${PLAY_ICON}</button>
          <button class="tweaks-toggle ${A.state[f.id] ? 'on' : ''}" data-toggle="${f.id}" aria-label="Toggle ${f.label}"></button>
        </div>
      `).join("");
      return true;
    }

    if (!paint()) {
      const iv = setInterval(() => { if (paint()) clearInterval(iv); }, 60);
      setTimeout(() => clearInterval(iv), 4000);
    }

    master.addEventListener("click", () => {
      const A = window.AppleAnim; if (!A) return;
      A.setMaster(!A.state.master);
      master.classList.toggle("on", !!A.state.master);
    });
    speed.addEventListener("click", (e) => {
      const A = window.AppleAnim; if (!A) return;
      const b = e.target.closest("[data-speed]"); if (!b) return;
      A.setSpeed(b.dataset.speed);
      speed.querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
    });
    replayAll.addEventListener("click", () => { window.AppleAnim && window.AppleAnim.replayAll(); });
    list.addEventListener("click", (e) => {
      const A = window.AppleAnim; if (!A) return;
      const replayBtn = e.target.closest("[data-replay]");
      if (replayBtn) {
        replayBtn.classList.remove("spinning");
        void replayBtn.getBoundingClientRect();
        replayBtn.classList.add("spinning");
        A.replay(replayBtn.dataset.replay);
        return;
      }
      const toggleBtn = e.target.closest("[data-toggle]");
      if (toggleBtn) {
        const id = toggleBtn.dataset.toggle;
        const next = !A.state[id];
        A.setFeature(id, next);
        toggleBtn.classList.toggle("on", next);
      }
    });
  }

  let panelEl;
  function show() { if (panelEl) { panelEl.hidden = false; requestAnimationFrame(() => panelEl.classList.add("show")); } }
  function hide() { if (panelEl) { panelEl.classList.remove("show"); setTimeout(() => panelEl.hidden = true, 200); } }
  function dismiss() { hide(); window.parent.postMessage({ type: "__edit_mode_dismissed" }, "*"); }

  // Keep the sidebar theme toggle in sync with tweaks state
  function bindSidebarSync() {
    const tt = document.getElementById("theme-toggle");
    if (!tt) return;
    tt.addEventListener("click", e => {
      const b = e.target.closest("[data-theme-set]");
      if (!b) return;
      state.theme = b.dataset.themeSet;
      // re-sync tweaks panel buttons + accent shade
      document.querySelectorAll("#tw-theme button").forEach(s => s.classList.toggle("active", s.dataset.themeOpt === state.theme));
      applyAccent(); save();
    });
  }

  window.NexusTweaks = {
    init() {
      panelEl = buildPanel();
      applyAll();
      bindSidebarSync();
      // host protocol
      window.addEventListener("message", e => {
        const t = e?.data?.type;
        if (t === "__activate_edit_mode") show();
        else if (t === "__deactivate_edit_mode") hide();
      });
      window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    },
    // Called by animations.js after a View Transition theme swap, so the tweaks
    // panel + accent shade stay in sync without re-triggering the swap.
    syncTheme(t) {
      state.theme = t;
      document.querySelectorAll("#tw-theme button").forEach(s => s.classList.toggle("active", s.dataset.themeOpt === t));
      applyAccent(); save();
    },
  };
})();
