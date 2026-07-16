# Handoff: NexusAI Dashboard — Animation System

## Overview

This handoff documents a system of **13 UX animations** layered onto the NexusAI investing dashboard. Each animation is independently toggleable and replayable by the end user via a Tweaks panel. The system is meant to feel like Apple/macOS — motion that signals causality, not motion as decoration.

## About the Design Files

The HTML/CSS/JS files in `reference/` are **design references**, not production code. They're a working prototype showing the intended motion vocabulary, timing curves, and interaction patterns. Your job is to **recreate these animations in the target application's existing environment** (React, Vue, Svelte, SwiftUI, native, etc.) using its established component primitives and animation libraries.

If the target app uses Framer Motion / Motion One / React Spring / a CSS-in-JS solution, prefer those over hand-rolled keyframes. The animation **specs** (durations, easings, properties, triggers) transfer 1:1; the **implementation** should match the host codebase's conventions.

## Fidelity

**High-fidelity.** All durations, easing curves, properties, and triggers are final and should be matched precisely. Adjusting them visibly changes the perceived quality of the product.

## The 13 Animations

Each animation below specifies: **trigger**, **target**, **properties**, **duration**, **easing**, **fallback behavior**.

---

### 1. Number count-up

- **Trigger**: Section first hydrated; manual replay button
- **Target**: Hero net worth number, portfolio stat tiles
- **What animates**: Numeric text content tweens from 0 → target value
- **Visual treat**: While counting, the digit color is masked by a horizontal gradient (`var(--text)` → `var(--accent)` → `var(--text)`) at 220% width that slides left. A subtle "ink wetting" shimmer.
- **Duration**: 1200–1400ms
- **Easing**: `easeOutCubic` (JS-driven via `requestAnimationFrame`)
- **Implementation**:
  ```js
  function countUp(el, to, { duration, prefix, currency }) {
    const t0 = performance.now();
    el.classList.add("counting");
    function frame(now) {
      const t = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = format(to * eased);
      if (t < 1) requestAnimationFrame(frame);
      else el.classList.remove("counting");
    }
    requestAnimationFrame(frame);
  }
  ```
- **Fallback**: If animations are disabled, set final value immediately.

### 2. Chart line draw-in + area fade

- **Trigger**: Chart rendered (net worth, Analyze price chart)
- **Target**: SVG `<path>` elements with `stroke` (lines) and `fill="url(#…)"` (area fill)
- **What animates**: Line paths use `stroke-dasharray` / `stroke-dashoffset` to "draw" the line from start to end. Area fill fades in (opacity 0→1) **after** the line has substantially drawn.
- **Duration**: line 1100ms, area 900ms with 500ms delay
- **Easing**: `cubic-bezier(0.2, 0.8, 0.2, 1)` (smooth ease-out)
- **Critical pattern**: Use `path.getTotalLength()` to set `--len`, then set `stroke-dashoffset: var(--len)` initially and animate to 0.
- **Implementation**:
  ```css
  .path-draw {
    stroke-dasharray: var(--len);
    stroke-dashoffset: var(--len);
    animation: pathDraw 1100ms cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
  }
  @keyframes pathDraw { to { stroke-dashoffset: 0; } }
  ```

### 3. Donut wedge sweep

- **Trigger**: Allocation donut rendered
- **Target**: Each `<circle>` segment of the donut
- **What animates**: `stroke-dasharray` from `0 circumference` → `segmentLength remainder`, sweeping the arc clockwise from 12 o'clock
- **Duration**: 900ms per segment
- **Stagger**: Each segment delayed 90ms after the previous (in segment order)
- **Easing**: `cubic-bezier(0.2, 0.8, 0.2, 1)`
- **Note**: The donut is composed of full circles rotated `-90deg` (so they start at top), with `stroke-dasharray` controlling the visible arc length and `stroke-dashoffset` controlling where each arc starts.

### 4. Bar fill stagger

- **Trigger**: Section hydrated (Sector breakdown, Concentration)
- **Target**: `.bar-fill` divs with `data-w` attribute (target width %)
- **What animates**: `width` from `0%` to `data-w%`
- **Duration**: 900ms per bar
- **Stagger**: 60ms between bars in the same card (DOM order)
- **Easing**: `cubic-bezier(0.34, 1.32, 0.4, 1)` (the "spring" curve — overshoots slightly)
- **Implementation**: Set `transition-delay: i * 60ms` per bar, then in the next animation frame flip width from 0% to target.

### 5. Sparkline draw-in

- **Trigger**: Sparklines rendered (Movers, Holdings table)
- **Target**: SVG `<polyline>` inside `.spark`
- **What animates**: Same `stroke-dashoffset` technique as the main chart
- **Duration**: 900ms
- **Stagger**: 40ms × (index % 8) — wraps at 8 to avoid huge cascade
- **Easing**: `cubic-bezier(0.2, 0.8, 0.2, 1)`

### 6. Section cross-fade

- **Trigger**: Sidebar nav item clicked (or initial mount of active section)
- **Target**: The newly-active `.section` element
- **What animates**: `transform: translateY(8px) → 0`, `scale(0.992) → 1`, `filter: blur(4px) → 0`
- **Duration**: 380ms
- **Easing**: `cubic-bezier(0.2, 0.8, 0.2, 1)`
- **⚠️ CRITICAL — Do not animate opacity here.** The previous-active section is hidden via `display:none`, so opacity is unnecessary. Animating opacity in the keyframes means that if the animation never advances (throttled tab, reduced-motion override, snapshot rendering), the section stays invisible. Keep the resting style fully visible; let the animation only "nudge" transform/blur.
- **Pattern**: Add a transient class `.section-enter` (not a permanent attribute of `.active`); remove it on `animationend` with a `setTimeout` fallback after 1200ms.

### 7. Card scroll-reveal

- **Trigger**: Card scrolls into the main scroll viewport
- **Target**: Each `.card` in `.content`
- **What animates**: `transform: translateY(14px) → 0`
- **Duration**: 560ms
- **Easing**: `cubic-bezier(0.34, 1.32, 0.4, 1)` (spring)
- **Stagger**: 40ms × DOM order — fires as cards intersect
- **Implementation**: IntersectionObserver with `threshold: 0.05`, `root: .main` (the scrolling element). Add `.card-enter` class on intersect; `unobserve` the card after.
- **⚠️ Same opacity caveat as #6.** Never gate visibility through the keyframe — resting `.card` is opaque; the animation just slides it up.

### 8. Sliding sidebar nav highlight

- **Trigger**: Active nav item changes
- **Target**: A single `.nav-indicator` element absolutely positioned inside `.nav`
- **What animates**: `top` and `height` glide to match the currently-active `.nav-item`'s bounding rect (computed relative to `.nav`)
- **Duration**: 360ms
- **Easing**: `cubic-bezier(0.34, 1.32, 0.4, 1)` (spring — slight overshoot)
- **Pattern**: Shared-element transition. One DOM node moves; individual `.nav-item.active` backgrounds are suppressed (`background: transparent`) when this animation is on.
- **Implementation**:
  ```js
  function moveNavIndicator() {
    const nav = document.getElementById("nav");
    const active = nav.querySelector(".nav-item.active");
    const navRect = nav.getBoundingClientRect();
    const r = active.getBoundingClientRect();
    indicator.style.top = (r.top - navRect.top) + "px";
    indicator.style.height = r.height + "px";
  }
  ```

### 9. Range-pill sliding indicator

- **Trigger**: Timeframe pill (1M / 3M / YTD / etc.) clicked
- **Target**: `.pill-indicator` inside `.range-pills`
- **What animates**: `left` and `width` glide to the active button's bounds
- **Duration**: 340ms
- **Easing**: spring
- **Pattern**: Same shared-element approach as #8. One indicator per `.range-pills` container.

### 10. Streaming AI reply (typewriter)

- **Trigger**: User submits a message in the Advisor chat
- **Target**: New assistant `.bubble`
- **What animates**:
  1. User bubble appears with a spring `bubbleIn` (opacity 0→1, scale 0.96→1, translateY 8→0, 340ms)
  2. Typing indicator bubble appears with 3 bouncing dots (`typingBounce` 1.1s infinite, 150ms phase offset between dots)
  3. After ~700ms, indicator content is replaced and text streams in character-by-character
  4. While streaming, a `▍` cursor blinks (`blink` 0.9s steps(2))
  5. When complete, the "Claude" source line fades into the bubble
- **Stream rate**: 2 chars per ~14ms tick (scaled by user speed setting)
- **Implementation**: Returns a promise; `setInterval` advances a slice of the full text into `el.textContent` until complete.

### 11. Live price flash + alert pulse

- **Trigger A (flash)**: Internal 1.6s timer randomly picks a visible price cell on Watchlist/Portfolio
- **Trigger B (pulse)**: Watchlist row where buy/sell target is "hit"
- **What animates**:
  - **Flash**: 620ms one-shot keyframe — background `transparent` → `var(--green-soft)` at 20% → `transparent`; text color same path
  - **Pulse**: Status dot has an `::after` pseudo with `box-shadow: 0 0 0 0 currentColor` → `0 0 0 10px currentColor`, opacity 0.5 → 0, 1.8s infinite
- **Easing**: ease-out
- **Note**: The flash is a *one-shot demo* of how real price ticks would feel. In production, fire it on actual websocket price-tick events.

### 12. Theme reveal (circular wipe)

- **Trigger**: Theme toggle clicked (sidebar or Tweaks panel)
- **Target**: The whole document
- **What animates**: `clip-path: circle(0% at <tx> <ty>)` → `circle(150% at <tx> <ty>)` on the new view
- **Duration**: 700ms
- **Easing**: `cubic-bezier(0.2, 0.8, 0.2, 1)`
- **API used**: [`document.startViewTransition()`](https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API) (Chrome, Safari 18+)
- **Pattern**: Set CSS custom properties `--tx` and `--ty` on `:root` to the click point before calling `startViewTransition()`. Style `::view-transition-new(root)` with the circular reveal keyframe.
- **Fallback**: If `document.startViewTransition` is undefined, apply the theme change synchronously (no animation).

### 13. Card hover lift

- **Trigger**: Mouse over a `.card`
- **Target**: The card
- **What animates**: `transform: translateY(0) → translateY(-2px)`, `box-shadow: var(--shadow-card) → var(--shadow-pop)`
- **Duration**: 280ms
- **Easing**: `cubic-bezier(0.2, 0.8, 0.2, 1)`
- **Note**: Off by default in most density modes; opt-in via the Tweaks panel.

---

## Animation Tokens

Define these once at the root of your design system:

```css
:root {
  /* Easing */
  --ease-spring: cubic-bezier(0.34, 1.32, 0.4, 1);   /* Slight overshoot */
  --ease-out:    cubic-bezier(0.2, 0.8, 0.2, 1);     /* Smooth ease-out */
  --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);       /* Material standard */

  /* Durations */
  --d-instant: 120ms;
  --d-fast:    200ms;
  --d-base:    280ms;
  --d-medium:  380ms;
  --d-slow:    560ms;
  --d-very-slow: 900ms;

  /* Global speed multiplier (user-controllable) */
  --anim-speed: 1;
}
```

When applying a duration, divide by speed: `calc(380ms / var(--anim-speed))`. The user's Tweaks panel sets `--anim-speed` to `0.6` / `1` / `1.6` for Slow / Normal / Fast.

## Architectural Patterns to Preserve

### 1. **Never gate visibility through opacity in keyframes**

This is the single most important rule. If `from { opacity: 0 }` is in your enter keyframe with `animation-fill-mode: both`, and the animation fails to advance (throttled tab, paused tab, reduced motion, server snapshot), your content is permanently invisible. **Always make the resting/no-class state fully visible.** Animations should only nudge transform / filter / color.

### 2. **One-shot enter classes, not permanent attributes**

Pattern:
- Add `.section-enter` when entering the section
- Remove on `animationend` AND with a `setTimeout` fallback at duration × 3
- Never leave the class on permanently

The CSS rule binds the animation **to the transient class**, not to `.active`. Switching back to a section that's already active won't re-trigger the animation unless JS explicitly re-applies the class.

### 3. **Master toggle as `data-` attribute on `<body>`**

Each animation feature has a `body[data-anim-<feature>="off"]` rule that sets `animation: none` on the relevant selectors. The master kill-switch `body[data-anim-master="off"] *` sets all `animation-duration: 1ms` and `transition-duration: 1ms` — animations effectively snap to their end state. This is also what should hook into `prefers-reduced-motion`.

### 4. **`prefers-reduced-motion` support**

Wrap the master kill-switch as:

```css
@media (prefers-reduced-motion: reduce) {
  body:not([data-anim-override="on"]) *,
  body:not([data-anim-override="on"]) *::before,
  body:not([data-anim-override="on"]) *::after {
    animation-duration: 1ms !important;
    animation-delay: 0ms !important;
    transition-duration: 1ms !important;
    transition-delay: 0ms !important;
  }
}
```

In the reference HTML this is `data-anim-master`; rename for production as appropriate. Allow users with reduced-motion preference to opt back in via the Tweaks panel.

### 5. **Restart-an-animation pattern**

To replay a CSS animation, you must:
```js
el.classList.remove("anim-class");
void el.getBoundingClientRect();  // force reflow
el.classList.add("anim-class");
```

Skipping the reflow does nothing — the browser doesn't see the class as having changed.

### 6. **SVG path draw-in helper**

```js
function animatePath(pathEl) {
  const len = pathEl.getTotalLength();
  pathEl.style.setProperty("--len", len);
  pathEl.classList.add("path-draw");
}
```

The CSS keyframe references `var(--len)` for both `stroke-dasharray` and the start `stroke-dashoffset`.

### 7. **Shared-element indicators**

For sliding nav + range pills, use one moveable indicator per group, not per-item background swaps. The user-toggle CSS suppresses per-item active backgrounds when the indicator is on, so toggling between the two visual modes is clean.

### 8. **Streaming text as a promise**

```js
function streamText(el, text, opts) {
  return new Promise(resolve => {
    let i = 0;
    const it = setInterval(() => {
      i += opts.charsPerTick;
      el.textContent = text.slice(0, i);
      if (i >= text.length) { clearInterval(it); resolve(); }
    }, opts.tick);
  });
}
```

Lets you `await` the stream before showing follow-up UI (e.g., a source citation).

## State Management

The animation system maintains:

```ts
type AnimState = {
  master: boolean;           // Global on/off
  speed: "slow" | "normal" | "fast";
  // Per-feature toggles
  section: boolean;
  reveal: boolean;
  counters: boolean;
  charts: boolean;
  donut: boolean;
  bars: boolean;
  sparks: boolean;
  nav: boolean;
  pills: boolean;
  hover: boolean;
  typing: boolean;
  pulse: boolean;
  theme: boolean;
};
```

Persist to `localStorage` (key: `nexus_anim_v1`). On change, write `data-anim-*` attributes back to `<body>` so CSS reflects state.

## Tweaks Panel UX (for the animation showcase)

The reference prototype includes a Tweaks panel where users can:

- Toggle each animation on/off individually with a small pill switch
- Replay any single animation via a ▶ button per row
- "Replay current view" button that re-hydrates the active section
- Choose master Slow / Normal / Fast speed

This is meant as a **demo/QA tool**, not a permanent end-user feature. In production you'd typically just expose a global "reduce motion" toggle that overrides `prefers-reduced-motion`.

## Files in `reference/`

| File | What it contains |
|---|---|
| `index.html` | App shell, init script, nav handling, theme toggle |
| `styles.css` | Base styles (layout, cards, charts, tables, command palette) |
| `animations.css` | All animation keyframes + toggle rules (this is the new layer) |
| `animations.js` | Animation utilities, hooks into render/hydrate, replay registry (this is the new layer) |
| `charts.js` | SVG chart renderers (area, multi-line, donut, sparkline) — modified to support draw-in |
| `sections-1.js` | Overview + Analyze section HTML + hydration |
| `sections-2.js` | Portfolio + Watchlist + Advisor section HTML + hydration |
| `tweaks.js` | Tweaks panel (existing controls + the new Animations section) |
| `command.js` | ⌘K command palette |
| `icons.js` | Lucide-style inline SVG icons |
| `data.js` (in parent) | All sample data — net worth history, accounts, positions, watchlist, etc. |

The animation system is concentrated in `animations.css` + `animations.js`. The other files are minimally modified (small hooks into `tweaks.js`, `index.html`, `charts.js`). If you're porting to a new framework, those two files contain ~90% of what you need to translate.

## Implementation Order Suggestion

1. **Set up animation tokens** (CSS custom properties, easing curves)
2. **Implement `prefers-reduced-motion` respect** at the global level
3. **Section cross-fade + card scroll-reveal** — the foundational page-level motion (#6, #7)
4. **Sliding nav indicator + range pills** — the shared-element pattern (#8, #9)
5. **Count-up + chart draw-in + donut sweep** — the content-arrival animations (#1, #2, #3)
6. **Bars + sparklines** — the smaller charts (#4, #5)
7. **Streaming chat + pulse + live flash** — the live-data motion (#10, #11)
8. **Theme reveal** — uses View Transitions API; nice-to-have, gated on browser support (#12)
9. **Card hover lift** — trivial, last (#13)

## Acceptance Criteria

- [ ] All resting (non-animating) UI is fully visible at all times, even with JS disabled
- [ ] `prefers-reduced-motion: reduce` disables all non-essential motion by default
- [ ] No animation depends on a specific timing for its visible state — i.e., pausing the page at any animation's currentTime=0 should still show the content
- [ ] Theme reveal degrades to instant swap on browsers without View Transitions API
- [ ] Streaming text is interruptible (subsequent message replaces stream cleanly)
- [ ] Number counters round consistently — no flicker between e.g. `253622` and `253622.99`
- [ ] Chart draws complete even if the user resizes mid-animation
- [ ] Toggling any feature off in the Tweaks panel takes immediate effect, no reload required
