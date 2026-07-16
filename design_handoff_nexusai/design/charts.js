// Lightweight SVG charts: area, line, donut, sparkline.
(() => {
  const px = (n) => +(+n).toFixed(2);

  // Smooth area chart with crosshair
  window.renderAreaChart = (container, series, opts = {}) => {
    const W = container.clientWidth || 720;
    const H = container.clientHeight || 220;
    const pad = { t: 14, r: 14, b: 22, l: 50 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;

    if (!series.length) { container.innerHTML = '<div class="chart-empty">Loading…</div>'; return; }

    const xs = series.map(d => d.x.getTime());
    const ys = series.map(d => d.y);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys) * 0.97;
    const yMax = Math.max(...ys) * 1.03;
    const sx = (x) => pad.l + ((x - xMin) / (xMax - xMin)) * innerW;
    const sy = (y) => pad.t + (1 - (y - yMin) / (yMax - yMin)) * innerH;

    // Build smooth path with monotonic cubic
    const pts = series.map(d => [sx(d.x.getTime()), sy(d.y)]);
    let path = `M ${pts[0][0]} ${pts[0][1]}`;
    for (let i = 1; i < pts.length; i++) {
      const [x0, y0] = pts[i - 1];
      const [x1, y1] = pts[i];
      const cx1 = x0 + (x1 - x0) * 0.5;
      path += ` C ${cx1} ${y0}, ${cx1} ${y1}, ${x1} ${y1}`;
    }
    const areaPath = path + ` L ${pts[pts.length - 1][0]} ${pad.t + innerH} L ${pts[0][0]} ${pad.t + innerH} Z`;

    // y ticks
    const yTicks = 4;
    let ticks = "";
    for (let i = 0; i <= yTicks; i++) {
      const t = yMin + (yMax - yMin) * (i / yTicks);
      const y = sy(t);
      ticks += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="var(--border)" stroke-dasharray="3,3"/>`;
      ticks += `<text x="${pad.l - 8}" y="${y + 4}" text-anchor="end" fill="var(--text-3)" font-size="10">${opts.fmtY ? opts.fmtY(t) : Math.round(t)}</text>`;
    }
    // x ticks (4 evenly spaced)
    let xTicks = "";
    const xCount = 4;
    for (let i = 0; i <= xCount; i++) {
      const t = xMin + (xMax - xMin) * (i / xCount);
      const x = sx(t);
      xTicks += `<text x="${x}" y="${H - 4}" text-anchor="middle" fill="var(--text-3)" font-size="10">${opts.fmtX ? opts.fmtX(new Date(t)) : new Date(t).toLocaleDateString()}</text>`;
    }

    const gradId = "grad-" + Math.random().toString(36).slice(2, 8);
    const color = opts.color || "var(--accent)";

    container.innerHTML = `
      <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
        <defs>
          <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${color}" stop-opacity="0.32"/>
            <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
          </linearGradient>
        </defs>
        ${ticks}${xTicks}
        <path d="${areaPath}" fill="url(#${gradId})"/>
        <path d="${path}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
        <line class="ch-vline" x1="0" x2="0" y1="${pad.t}" y2="${pad.t + innerH}" stroke="${color}" stroke-width="1" opacity="0"/>
        <circle class="ch-dot" r="5" fill="${color}" opacity="0"/>
        <circle class="ch-dot-ring" r="9" fill="${color}" opacity="0"/>
      </svg>
      <div class="crosshair-tip"><div class="v"></div><div class="date"></div></div>
    `;

    const svg = container.querySelector("svg");
    const vline = svg.querySelector(".ch-vline");
    const dot = svg.querySelector(".ch-dot");
    const ring = svg.querySelector(".ch-dot-ring");
    const tip = container.querySelector(".crosshair-tip");

    container.style.position = "relative";
    svg.addEventListener("mousemove", (e) => {
      const rect = svg.getBoundingClientRect();
      const mx = (e.clientX - rect.left) * (W / rect.width);
      if (mx < pad.l || mx > W - pad.r) return;
      // find nearest data point
      let nearest = 0;
      let minDist = Infinity;
      pts.forEach(([x], i) => {
        const d = Math.abs(x - mx);
        if (d < minDist) { minDist = d; nearest = i; }
      });
      const [x, y] = pts[nearest];
      vline.setAttribute("x1", x); vline.setAttribute("x2", x); vline.setAttribute("opacity", "0.35");
      dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("opacity", "1");
      ring.setAttribute("cx", x); ring.setAttribute("cy", y); ring.setAttribute("opacity", "0.18");
      const d = series[nearest];
      tip.classList.add("show");
      tip.style.left = (x * rect.width / W) + "px";
      tip.style.top = (y * rect.height / H) + "px";
      tip.querySelector(".v").textContent = opts.fmtTip ? opts.fmtTip(d.y) : d.y;
      tip.querySelector(".date").textContent = d.x.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    });
    svg.addEventListener("mouseleave", () => {
      vline.setAttribute("opacity", "0");
      dot.setAttribute("opacity", "0");
      ring.setAttribute("opacity", "0");
      tip.classList.remove("show");
    });
  };

  // Multi-line chart (Close + SMA50 + SMA200)
  window.renderMultiLineChart = (container, series, opts = {}) => {
    const W = container.clientWidth || 720;
    const H = container.clientHeight || 220;
    const pad = { t: 14, r: 14, b: 22, l: 50 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;

    if (!series[0]?.data?.length) { container.innerHTML = '<div class="chart-empty">Loading…</div>'; return; }

    const all = series.flatMap(s => s.data.map(d => d.y).filter(y => y != null));
    const yMin = Math.min(...all) * 0.97;
    const yMax = Math.max(...all) * 1.03;
    const xs = series[0].data.map(d => d.x.getTime());
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const sx = (x) => pad.l + ((x - xMin) / (xMax - xMin)) * innerW;
    const sy = (y) => pad.t + (1 - (y - yMin) / (yMax - yMin)) * innerH;

    let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const t = yMin + (yMax - yMin) * (i / yTicks);
      const y = sy(t);
      svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="var(--border)" stroke-dasharray="3,3"/>`;
      svg += `<text x="${pad.l - 8}" y="${y + 4}" text-anchor="end" fill="var(--text-3)" font-size="10">$${t.toFixed(0)}</text>`;
    }
    // Filled main area for close
    const closeSeries = series[0];
    const closePts = closeSeries.data.map(d => [sx(d.x.getTime()), sy(d.y)]);
    let mainPath = `M ${closePts[0][0]} ${closePts[0][1]}`;
    for (let i = 1; i < closePts.length; i++) {
      const [x0, y0] = closePts[i - 1];
      const [x1, y1] = closePts[i];
      const cx1 = x0 + (x1 - x0) * 0.5;
      mainPath += ` C ${cx1} ${y0}, ${cx1} ${y1}, ${x1} ${y1}`;
    }
    const gradId = "g-" + Math.random().toString(36).slice(2, 8);
    svg += `<defs><linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${closeSeries.color}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="${closeSeries.color}" stop-opacity="0"/></linearGradient></defs>`;
    svg += `<path d="${mainPath} L ${closePts[closePts.length-1][0]} ${pad.t + innerH} L ${closePts[0][0]} ${pad.t + innerH} Z" fill="url(#${gradId})"/>`;
    series.forEach((s, idx) => {
      const pts = s.data.filter(d => d.y != null).map(d => [sx(d.x.getTime()), sy(d.y)]);
      if (pts.length < 2) return;
      let p = `M ${pts[0][0]} ${pts[0][1]}`;
      for (let i = 1; i < pts.length; i++) p += ` L ${pts[i][0]} ${pts[i][1]}`;
      svg += `<path d="${p}" fill="none" stroke="${s.color}" stroke-width="${idx === 0 ? 2.2 : 1.4}" stroke-dasharray="${s.dash || ''}"/>`;
    });
    // legend
    svg += `</svg>`;
    container.innerHTML = svg;
  };

  // Sparkline
  window.renderSparkline = (data, opts = {}) => {
    const W = opts.w || 80, H = opts.h || 22;
    if (!data.length) return "";
    const min = Math.min(...data), max = Math.max(...data);
    const range = max - min || 1;
    const pts = data.map((y, i) => [(i / (data.length - 1)) * W, H - ((y - min) / range) * H]).map(p => p.join(",")).join(" ");
    const last = data[data.length - 1], first = data[0];
    const color = last >= first ? "var(--green)" : "var(--red)";
    return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
  };

  // Donut chart
  window.renderDonut = (container, segments, opts = {}) => {
    const size = opts.size || 220;
    const stroke = opts.stroke || 22;
    const r = (size - stroke) / 2 - 2;
    const cx = size / 2, cy = size / 2;
    const total = segments.reduce((s, x) => s + x.value, 0);
    const circ = 2 * Math.PI * r;
    let offset = 0;
    let segs = "";
    if (total <= 0) {
      // Empty / zero state — draw a neutral track ring so the donut never shows NaN
      segs = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="${stroke}"/>`;
    } else {
      segments.forEach((s) => {
        const len = (s.value / total) * circ;
        segs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="${stroke}" stroke-dasharray="${len} ${circ - len}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})" style="transition: stroke-dasharray 0.8s"/>`;
        offset += len;
      });
    }
    container.innerHTML = `<svg class="donut" viewBox="0 0 ${size} ${size}">${segs}
      <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="11" fill="var(--text-2)" font-weight="600" letter-spacing="0.06em">${opts.label || ""}</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="22" font-weight="700" fill="var(--text)" letter-spacing="-0.02em">${opts.center || ""}</text>
    </svg>`;
  };
})();
