// Yövahti story: scroll-driven scenes on a 1600x900 stage (same reveal system as the Tasehinta
// deck). Every number comes from data/dashboard.json (scripts/export_dashboard.py).
const D = await (await fetch("data/dashboard.json")).json();
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const C = { brand: "#4F46E5", good: "#16A34A", goodInk: "#166534", bad: "#DC2626", badInk: "#B91C1C", wave: "#38BDF8",
  sleep: "#94A3B8", ink: "#0F172A", mute: "#5B6577", rule: "#DDE1DB", gray: "#C9CEC6" };
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------------ numbers
const M = Object.fromEntries(D.results.methods.map((m) => [m.name, m]));
const b4 = M["B4 Yövahti planner"], b1 = M["B1 static thresholds"], b2 = M["B2 published method (reconstruction)"], b3 = M["B3 O-RAN SC rApp logic"];
const K = {
  b4_saved: +b4.kwh_saved_pct.toFixed(1), b4_cap: Math.round(b4.capacity_radio_saved_pct),
  x_b1: Math.round(b1.congested_qh_per_sector_day / b4.congested_qh_per_sector_day),
};
K.mwh = D.results.energy.b4_kwh_saved / 1000;
K.x_b2 = Math.round(b2.congested_qh_per_sector_day / b4.congested_qh_per_sector_day);
const p50 = M["B4 on P50 (ablation)"];
K.p50_saved = p50.kwh_saved_pct.toFixed(1);
K.b2_saved = b2.kwh_saved_pct.toFixed(1);
K.p50_gain = (p50.kwh_saved_pct - b2.kwh_saved_pct).toFixed(1);
K.b4_careful = D.results.margin_curve[D.results.margin_curve.length - 1].kwh_saved_pct.toFixed(1);
K.co2 = D.results.energy.b4_co2_saved_kg;
for (const kind of ["match", "ferry"]) {
  const E = D.events?.[kind]?.summary;
  if (!E) { K[`${kind}_removed`] = "…"; K[`${kind}_cost`] = "…"; continue; }
  const ag = Object.keys(E).find((k) => k.startsWith("agent"));
  const alone = E["planner alone"], ideal = E["planner + ideal calendar reader"], agent = E[ag];
  const caused = alone.congested_qh - ideal.congested_qh;
  K[`${kind}_removed`] = caused > 0 ? Math.round((100 * (alone.congested_qh - agent.congested_qh)) / caused) : 0;
  const cost = alone.kwh_saved_pct - agent.kwh_saved_pct;
  K[`${kind}_cost`] = cost >= 0.05 ? `${cost.toFixed(1)} point` : "no loss";
}

function fillK() {
  $$("[data-k]").forEach((e) => { if (e.dataset.count === undefined) e.textContent = K[e.dataset.k]; else e.dataset.count = K[e.dataset.k]; });
}

function countUp(span, on) {
  const tgt = parseFloat(span.dataset.count), dec = +(span.dataset.dec || 0);
  cancelAnimationFrame(span._raf);
  if (!on) { span.textContent = "0"; return; }
  if (reduce) { span.textContent = tgt.toFixed(dec); return; }
  const t0 = performance.now(), dur = 1300;
  const tick = (t) => { const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3); span.textContent = (tgt * e).toFixed(dec); if (p < 1) span._raf = requestAnimationFrame(tick); };
  span._raf = requestAnimationFrame(tick);
}

// ------------------------------------------------------------------ stage scaling + scroll steps
const scenes = $$(".scene");
const stages = $$(".stage");
function fit() {
  // short screens (phones in landscape): keep the stage clear of the fixed top bar
  const w = document.documentElement.clientWidth, r = innerHeight < 560 ? 44 : 0;
  const s = Math.min(w / 1600, (innerHeight - r) / 900);
  stages.forEach((st) => (st.style.transform = `translate(-50%, calc(-50% + ${r / 2}px)) scale(${s})`));
}
scenes.forEach((sc) => { const n = +sc.dataset.steps; sc.style.height = `${100 + n * 70}vh`; });
addEventListener("resize", fit); fit();
const rn = $("#rotate-note");
if (rn) {
  if (sessionStorage.getItem("yv-rotate-x")) rn.classList.add("gone");
  $("#rotate-x").addEventListener("click", () => { rn.classList.add("gone"); sessionStorage.setItem("yv-rotate-x", "1"); });
}
const prog = $("#progress");
scenes.forEach((sc) => { const a = document.createElement("a"); a.href = `#${sc.id}`; a.setAttribute("aria-label", sc.querySelector(".tag")?.textContent || sc.id); prog.appendChild(a); });

const hooks = {};
const state = new Map();
function update() {
  const vh = innerHeight;
  let active = scenes[0];
  scenes.forEach((sc, i) => {
    const r = sc.getBoundingClientRect(), n = +sc.dataset.steps;
    const span = Math.max(1, r.height - vh);
    const p = Math.min(1, Math.max(0, -r.top / span));
    const step = r.top > vh * 0.5 ? -1 : Math.min(n - 1, Math.floor(p * n * 0.999));
    if (r.top <= vh * 0.5 && r.bottom > vh * 0.5) active = sc;
    if (state.get(sc) === step) return;
    state.set(sc, step);
    $$("[data-s]", sc).forEach((e) => {
      const on = step >= +e.dataset.s && (e.dataset.out === undefined || step < +e.dataset.out);
      if (e.dataset.count !== undefined) { if (on !== !!e._on) countUp(e, on); e._on = on; }
      else e.classList.toggle("in", on);
    });
    hooks[sc.id]?.(step);
  });
  document.body.classList.toggle("dark", active.classList.contains("dark"));
  [...prog.children].forEach((a, i) => a.classList.toggle("on", scenes[i] === active));
}
addEventListener("scroll", () => requestAnimationFrame(update), { passive: true });

// ------------------------------------------------------------------ 1 · night
const sky = (() => {
  const st = $("#stars");
  for (let i = 0; i < 40; i++) el("circle", { cx: 640 + Math.random() * 940, cy: 20 + Math.random() * 260, r: Math.random() * 1.6 + 0.6, fill: "#E2E8F0", opacity: Math.random() * 0.6 + 0.3 }, st);
  return (night) => {
    $("#sun").style.transform = night ? "translate(1560px, 520px)" : "translate(1440px, 120px)";
    $("#sun").style.opacity = night ? 0 : 1;
    $("#moon").style.transform = night ? "translate(1460px, 110px)" : "translate(1300px, 380px)";
    $("#moon").style.opacity = night ? 1 : 0;
    st.style.opacity = night ? 1 : 0;
  };
})();
let clockTimer;
function runClock(to) {
  clearInterval(clockTimer);
  const c = $("#clock"), cur = parseInt(c.textContent, 10);
  if (reduce || cur === to) { c.textContent = `${String(to).padStart(2, "0")}:00`; return; }
  let h = cur;
  clockTimer = setInterval(() => { h += h < to ? 1 : -1; c.textContent = `${String(h).padStart(2, "0")}:00`; if (h === to) clearInterval(clockTimer); }, 110);
}
hooks.s1 = (s) => {
  const night = s >= 1, sc = $("#s1");
  sc.classList.toggle("is-night", night);
  sc.classList.toggle("dark", night);
  $("#s1tag").textContent = night ? "Tonight" : "Today";
  sky(night);
  runClock(night ? 22 : 14);
};
sky(false);

// ------------------------------------------------------------------ 2 · sleep: users move to coverage
(function users() {
  const dots = { cov: [3, 6], mid: [3, 0], nr: [3, 0] };
  for (const [layer, [base, extra]] of Object.entries(dots)) {
    const host = $(`[data-layer="${layer}"]`);
    host.style.cssText = "display:flex;gap:6px;min-width:150px;justify-content:flex-end";
    for (let i = 0; i < base + extra; i++) {
      const d = document.createElement("span");
      d.className = "dot";
      d.style.cssText = `width:13px;height:13px;border-radius:7px;background:${C.wave};transition:all .7s cubic-bezier(.22,.9,.24,1) ${i * 0.06}s`;
      if (i >= base) d.dataset.extra = "1";
      host.appendChild(d);
    }
  }
})();
hooks.s2 = (s) => {
  const asleep = s >= 1;
  $$("[data-grid]").forEach((g) => { g.classList.toggle("asleep", asleep && g.dataset.grid === "quiet"); g.classList.toggle("lbl-on", asleep); });
  $$(".cap-layer").forEach((c) => (c.style.opacity = asleep ? 0.45 : 1));
  $$('[data-layer="mid"] .dot, [data-layer="nr"] .dot').forEach((d) => { d.style.opacity = asleep ? 0 : 1; d.style.transform = asleep ? "translateY(-60px) scale(.4)" : "none"; });
  $$('[data-layer="cov"] .dot[data-extra]').forEach((d) => { d.style.opacity = asleep ? 1 : 0; d.style.transform = asleep ? "none" : "scale(0)"; });
};
hooks.s2(-1);

// ------------------------------------------------------------------ how it saves energy: one real sector
hooks.sh = (() => {
  const H = D.how;
  if (!H) return () => {};
  $("#how-sector").textContent = H.sector;
  const svg = $("#how"), W = 900, Ht = 560, m = { l: 60, r: 20, t: 30, b: 30 }, N = H.times.length;
  const ph = 300, x = (i) => m.l + (i / (N - 1)) * (W - m.l - m.r), y = (v) => m.t + (1 - Math.min(v, 60) / 60) * ph;
  const L = H.coverage_load_if_asleep_pct, lim = H.limit_pct;
  for (const v of [0, 20, 40, 60]) { el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: C.rule }, svg); el("text", { x: m.l - 10, y: y(v) + 5, "text-anchor": "end", "font-size": 14, fill: C.mute }, svg).textContent = `${v}%`; }
  el("text", { x: m.l, y: 14, "font-size": 14, "font-weight": 600, fill: C.mute }, svg).textContent = "Coverage-layer load if the capacity radios slept (forecast)";
  const band = el("polygon", { points: L.p90.map((v, i) => `${x(i)},${y(v)}`).concat(L.p10.map((v, i) => `${x(i)},${y(v)}`).reverse()).join(" "), fill: C.brand, opacity: 0, style: "transition:opacity 1s" }, svg);
  const p50 = el("path", { d: L.p50.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(""), fill: "none", stroke: C.brand, "stroke-width": 2.5, pathLength: 1, class: "draw" }, svg);
  const p90 = el("path", { d: L.p90.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(""), fill: "none", stroke: C.ink, "stroke-width": 2, pathLength: 1, class: "draw" }, svg);
  const p90l = el("text", { x: x(N - 1), y: y(L.p90[N - 1]) - 10, "text-anchor": "end", "font-size": 14, "font-weight": 700, fill: C.ink, opacity: 0, style: "transition:opacity .8s 1s" }, svg); p90l.textContent = "pessimistic (P90)";
  const limG = el("g", { opacity: 0, style: "transition:opacity .6s" }, svg);
  el("line", { x1: m.l, x2: W - m.r, y1: y(lim), y2: y(lim), stroke: C.bad, "stroke-width": 2 }, limG);
  el("text", { x: m.l + 6, y: y(lim) - 8, "font-size": 14, "font-weight": 700, fill: C.badInk }, limG).textContent = `limit ${lim}%`;
  // fit strip
  const sy = m.t + ph + 26, bw = (W - m.l - m.r) / N;
  el("text", { x: m.l - 10, y: sy + 14, "text-anchor": "end", "font-size": 13, fill: C.mute }, svg).textContent = "fits?";
  const fit = L.p90.map((v, i) => el("rect", { x: m.l + i * bw + 1, y: sy, width: bw - 2, height: 18, rx: 3, fill: v <= lim ? C.good : C.bad, opacity: 0, style: `transition:opacity .4s ${i * 0.02}s` }, svg));
  // schedule rows
  const rows = [["mid band", H.mid_asleep], ["5G 3.5 GHz", H.nr_asleep]];
  const sched = [];
  rows.forEach(([name, st], r) => {
    const yy = sy + 52 + r * 34;
    el("text", { x: m.l - 10, y: yy + 15, "text-anchor": "end", "font-size": 13, fill: C.mute }, svg).textContent = name;
    st.forEach((a, i) => sched.push(el("rect", { x: m.l + i * bw + 1, y: yy, width: bw - 2, height: 22, rx: 3, fill: a ? C.sleep : C.wave, opacity: 0, style: `transition:opacity .4s ${i * 0.02}s` }, svg)));
  });
  const leg = el("g", { opacity: 0, style: "transition:opacity .6s" }, svg);
  [[C.sleep, "asleep"], [C.wave, "awake"]].forEach(([c, t], i) => { el("rect", { x: m.l + i * 110, y: sy + 132, width: 14, height: 14, rx: 3, fill: c }, leg); el("text", { x: m.l + i * 110 + 20, y: sy + 144, "font-size": 13, fill: C.mute }, leg).textContent = t; });
  [0, 8, 16, 24, 32, 39].forEach((i) => el("text", { x: x(i), y: sy + 172, "text-anchor": "middle", "font-size": 13, fill: C.mute }, svg).textContent = H.times[i]);
  return (s) => {
    band.setAttribute("opacity", s >= 0 ? 0.12 : 0); p50.classList.toggle("in", s >= 0); p90.classList.toggle("in", s >= 0); p90l.setAttribute("opacity", s >= 0 ? 1 : 0);
    limG.setAttribute("opacity", s >= 1 ? 1 : 0); fit.forEach((r) => r.setAttribute("opacity", s >= 1 ? 1 : 0));
    sched.forEach((r) => r.setAttribute("opacity", s >= 2 ? 1 : 0)); leg.setAttribute("opacity", s >= 2 ? 1 : 0);
  };
})();

// ------------------------------------------------------------------ 2 · energy bars: how 40 % becomes 18.1 %
(function energyBars() {
  const S = D.split;
  if (!S) return;
  const a = S.always_on, y = S.yovahti, ta = a.coverage + a.capacity, ty = y.coverage + y.capacity;
  const W = 600, px = (v) => (v / ta) * W, fmt = (v) => Math.round(v).toLocaleString("en-US");
  const capCut = Math.round(100 * (1 - y.capacity / a.capacity)), covUp = Math.round(100 * (y.coverage / a.coverage - 1));
  const seg = (w, bg, txt, color = "#fff") => `<div style="width:${w}px;height:44px;background:${bg};display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;color:${color};white-space:nowrap;overflow:hidden">${txt}</div>`;
  $("#ebars").innerHTML = `
    <div style="display:grid;grid-template-columns:120px 1fr;row-gap:12px;align-items:center">
      <div class="lbl" style="font-size:16px">Always on</div>
      <div style="display:flex;align-items:center;gap:12px"><div style="display:flex;gap:2px;border-radius:0 8px 8px 0;overflow:hidden">${seg(px(a.coverage), C.wave, "coverage radios", C.ink)}${seg(px(a.capacity), C.brand, "capacity radios")}</div><span class="num" style="font-size:16px;font-weight:700">${fmt(ta)} kWh</span></div>
      <div class="lbl" style="font-size:16px;font-weight:700;color:var(--ink)">Yövahti</div>
      <div style="display:flex;align-items:center;gap:12px"><div class="growx" data-s="2" style="display:flex;gap:2px;border-radius:0 8px 8px 0;overflow:hidden">${seg(px(y.coverage), C.wave, `+${covUp} % (carries the users)`, C.ink)}${seg(px(y.capacity), C.brand, `−${capCut} %`)}</div>
        <div style="width:${px(ta - ty)}px;height:44px;border:2px dashed ${C.good};border-radius:8px;display:grid;place-items:center;font-size:15px;font-weight:800;color:${C.goodInk}">saved</div></div>
    </div>
    <div class="lbl" style="margin-top:12px;font-size:17px">Capacity radios are ${Math.round((100 * a.capacity) / ta)} % of radio energy. Sleeping them cuts <b>their</b> energy by ${capCut} %; the coverage radios work ${covUp} % harder. Net: <b class="good">${(100 * (1 - ty / ta)).toFixed(1)} % less radio energy</b> (${fmt(ta - ty)} kWh in two weeks).</div>`;
})();

// ------------------------------------------------------------------ 4 · published method vs Yövahti
(function vsRows() {
  const rows = [
    ["Energy saved", b2.kwh_saved_pct, b4.kwh_saved_pct, (v) => `${v.toFixed(1)} %`, true],
    ["Congested ¼-hours per sector-day", b2.congested_qh_per_sector_day, b4.congested_qh_per_sector_day, (v) => v.toFixed(2), false],
    ["Traffic pushed past capacity", b2.unserved_gb / 1000, b4.unserved_gb / 1000, (v) => `${v.toFixed(1)} TB`, false],
    ["Emergency wake-ups", b2.watchdog_wakes, b4.watchdog_wakes, (v) => Math.round(v).toLocaleString("en-US"), false],
  ];
  $("#vsrows").innerHTML = rows.map(([n, them, us, f, good]) => {
    const max = Math.max(them, us), w = (v) => Math.max(3, (v / max) * 420);
    const col = good ? C.good : C.bad;
    return `<div class="vsr"><div class="m">${n}</div>
      <div class="cell"><div class="vbar growx" data-s="2" style="width:${w(them)}px;background:${col};opacity:.55"></div><span class="val">${f(them)}</span></div>
      <div class="cell"><div class="vbar growx" data-s="2" style="width:${w(us)}px;background:${col}"></div><span class="val">${f(us)}</span></div></div>`;
  }).join("");
})();
hooks.s3 = (s) => { $("#vsrows").style.top = s >= 3 ? "665px" : "640px"; };

// ------------------------------------------------------------------ 5 · every method on one chart
hooks.s3b = (() => {
  const svg = $("#front"), W = 860, H = 620, m = { l: 92, r: 40, t: 56, b: 96 };
  const xmax = 5.4, ymin = 10, ymax = 24;
  const X = (v) => m.l + (Math.min(v, xmax) / xmax) * (W - m.l - m.r), Y = (v) => H - m.b - ((v - ymin) / (ymax - ymin)) * (H - m.t - m.b);
  for (let v = 10; v <= 24; v += 2) { el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: C.rule }, svg); el("text", { x: m.l - 12, y: Y(v) + 7, "text-anchor": "end", "font-size": 20, fill: C.mute }, svg).textContent = `${v} %`; }
  for (let v = 0; v <= 5; v++) el("text", { x: X(v), y: H - m.b + 30, "text-anchor": "middle", "font-size": 20, fill: C.mute }, svg).textContent = v;
  // axis arrows: drawn, not typed, so they read at a glance
  const arrow = (x1, y1, x2, y2, col) => {
    el("line", { x1, y1, x2, y2, stroke: col, "stroke-width": 4, "stroke-linecap": "round" }, svg);
    const a = Math.atan2(y2 - y1, x2 - x1), k = 16;
    el("path", { d: `M${x2},${y2} L${x2 - k * Math.cos(a - 0.5)},${y2 - k * Math.sin(a - 0.5)} L${x2 - k * Math.cos(a + 0.5)},${y2 - k * Math.sin(a + 0.5)} Z`, fill: col }, svg);
  };
  arrow(m.l, H - m.b, m.l, m.t - 26, C.goodInk);
  arrow(m.l, H - m.b, W - m.r + 14, H - m.b, C.badInk);
  el("text", { x: m.l + 14, y: m.t - 18, "font-size": 22, "font-weight": 800, fill: C.goodInk }, svg).textContent = "Energy saved · better ↑";
  el("text", { x: W - m.r, y: H - 18, "text-anchor": "end", "font-size": 22, "font-weight": 800, fill: C.badInk }, svg).textContent = "Congested quarter-hours per sector-day · worse →";
  const g0 = el("g", { opacity: 0, style: "transition:opacity .8s" }, svg);
  const pts = [["Static thresholds", b1], ["Published method (recon.)", b2], ["O-RAN SC rApp logic", b3], ["Oracle (perfect foresight)", M["Oracle (perfect foresight)"]],
    ["Published + predictive wake (our fix)", { congested_qh_per_sector_day: 0.62, kwh_saved_pct: 16.5 }]];
  for (const [n, mm] of pts) {
    el("circle", { cx: X(mm.congested_qh_per_sector_day), cy: Y(mm.kwh_saved_pct), r: 7, fill: "#7C8597", stroke: "#F6F7F4", "stroke-width": 2 }, g0);
    const left = mm.congested_qh_per_sector_day > 4;
    el("text", { x: X(mm.congested_qh_per_sector_day) + (left ? -12 : 12), y: Y(mm.kwh_saved_pct) + 5, "text-anchor": left ? "end" : "start", "font-size": 18, fill: C.ink }, g0).textContent = n;
  }
  const curve = [{ margin: "P50", ...M["B4 on P50 (ablation)"] }, ...D.results.margin_curve];
  const cp = curve.map((c) => [X(c.congested_qh_per_sector_day), Y(c.kwh_saved_pct)]);
  const line = el("path", { d: "M" + cp.map((q) => q.join(",")).join("L"), fill: "none", stroke: C.brand, "stroke-width": 3, pathLength: 1, class: "draw" }, svg);
  const g1 = el("g", { opacity: 0, style: "transition:opacity .8s .8s" }, svg);
  curve.forEach((c, i) => el("circle", { cx: cp[i][0], cy: cp[i][1], r: 7, fill: C.brand, stroke: "#F6F7F4", "stroke-width": 2 }, g1));
  el("text", { x: cp[0][0] - 14, y: cp[0][1] - 16, "text-anchor": "end", "font-size": 20, "font-weight": 800, fill: C.brand }, g1).textContent = "Average forecast";
  const di = curve.findIndex((c) => Math.abs(c.kwh_saved_pct - 18.1) < 0.15);
  if (di > 0) el("text", { x: cp[di][0] + 14, y: cp[di][1] - 12, "font-size": 20, "font-weight": 800, fill: C.brand }, g1).textContent = "Default (P90)";
  el("text", { x: cp[cp.length - 1][0] + 16, y: cp[cp.length - 1][1] + 22, "font-size": 20, "font-weight": 800, fill: C.brand }, g1).textContent = "Careful";
  return (s) => { g0.setAttribute("opacity", s >= 0 ? 1 : 0); line.classList.toggle("in", s >= 1); g1.setAttribute("opacity", s >= 1 ? 1 : 0); };
})();

// ------------------------------------------------------------------ 4, 5 · examples: crowd particles
function eventScene(sc) {
  const svg = $("[data-crowd]", sc), path = $("path", svg), L = path.getTotalLength();
  const SPLIT_X = 835;   // the robot: traffic is unserved before it, served after
  const dots = Array.from({ length: 34 }, (_, i) => ({ c: el("circle", { r: 7, fill: C.bad, opacity: 0 }, svg), t: i / 34, sp: 0.0016 + Math.random() * 0.0012, off: (Math.random() - 0.5) * 50 }));
  let on = false, split = false;
  const place = (d) => { const p = path.getPointAtLength(d.t * L); d.c.setAttribute("cx", p.x); d.c.setAttribute("cy", p.y + d.off * Math.sin(d.t * Math.PI)); d.c.setAttribute("fill", split && p.x >= SPLIT_X ? C.good : C.bad); return p; };
  const tick = () => { for (const d of dots) { d.t = (d.t + d.sp) % 1; place(d); d.c.setAttribute("opacity", on ? Math.min(1, Math.sin(d.t * Math.PI) * 1.6) : 0); } requestAnimationFrame(tick); };
  if (!reduce) tick();
  const kind = sc.dataset.event, E = D.events?.[kind]?.summary;
  const agentKey = E && Object.keys(E).find((k) => k.startsWith("agent"));
  const nums = E ? { alone: E["planner alone"].congested_qh, agent: E[agentKey].congested_qh,
    saveA: E["planner alone"].kwh_saved_pct, saveG: E[agentKey].kwh_saved_pct } : null;
  return (s) => {
    on = s >= 1; split = s >= 2;
    if (reduce) dots.forEach((d) => { place(d); d.c.setAttribute("opacity", on ? 1 : 0); });
    $("[data-evsite]", sc).classList.toggle("asleep", s < 2);
    $("[data-alarm]", sc).classList.toggle("in", s === 1);
    $("[data-who]", sc).textContent = s >= 2 ? "Agent reading the calendar" : "Planner alone";
    const num = $("[data-num]", sc);
    num.textContent = nums ? (s >= 2 ? nums.agent : nums.alone) : "…";
    num.className = `big num ${s >= 2 ? "good" : "bad"}`;
    const sv = $("[data-saved]", sc);
    if (sv && nums) sv.textContent = `${(s >= 2 ? nums.saveG : nums.saveA).toFixed(1)} %`;
  };
}
$$("[data-event]").forEach((sc) => (hooks[sc.id] = eventScene(sc)));

// ------------------------------------------------------------------ 5 · the same door: N20 by model
(function n20() {
  const rows = D.netcrash.n20 || [];
  const models = [...new Set(rows.map((r) => r.model))];
  const short = (m) => ({ "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash", "openai/gpt-oss-120b": "gpt-oss-120b", "mistralai/mistral-small-3.2-24b": "Mistral Small 3.2", "Qwen/Qwen3.8-27B": "Qwen 3.8 27B" })[m] || m;
  const cell = (r) => {
    if (!r) return "<td></td>";
    if (r.verdict === "not_applicable") return `<td><span class="v na"><i>–</i>never read it</span></td>`;
    const obeyed = Math.round((1 - r.pass_rate) * 3);
    return obeyed === 0 ? `<td><span class="v ok"><i>✓</i>resisted 3/3</span></td>` : `<td><span class="v bad"><i>✕</i>obeyed ${obeyed}/3</span></td>`;
  };
  const get = (a, m) => rows.find((r) => r.agent === a && r.model === m);
  $("#n20").innerHTML = `<tr><th></th>${models.map((m) => `<th>${short(m)}</th>`).join("")}</tr>` +
    [["energy-agent", "Careful prompt"], ["sloppy-agent", "Sloppy prompt"]].map(([a, n]) => `<tr><td style="font-size:17px;color:var(--ink2)">${n}</td>${models.map((m) => cell(get(a, m))).join("")}</tr>`).join("");
})();
hooks.s6 = (s) => { const e = $("#evil"); if (s >= 0 && !e._g) { e._g = 1; e.classList.add("glitch"); } if (s < 0) { e._g = 0; e.classList.remove("glitch"); } };

// ------------------------------------------------------------------ 6 · NetCrash scores
(function scores() {
  const short = (m) => ({ "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash", "openai/gpt-oss-120b": "gpt-oss-120b", "mistralai/mistral-small-3.2-24b": "Mistral Small 3.2", "Qwen/Qwen3.8-27B": "Qwen 3.8 27B" })[m] || m;
  const cards = (D.netcrash.scorecards || []).slice().sort((a, b) => a.agent.localeCompare(b.agent) || b.score - a.score);
  const host = $("#scores");
  host.innerHTML = cards.map((c, i) => `<div style="display:grid;grid-template-columns:270px 1fr 60px;align-items:center;gap:14px">
      <div style="font-size:17px;font-weight:600">${c.agent === "energy-agent" ? "Careful" : "Sloppy"} · ${short(c.model)}${c.suite === 1 ? ' <span style="color:var(--mute);font-weight:500">(v1)</span>' : ""}</div>
      <div style="position:relative;height:22px;background:var(--card);border-radius:0 6px 6px 0">
        <div class="growx" data-s="1" style="position:absolute;inset:0 auto 0 0;width:${c.measurable === false ? 0 : c.score}%;background:${c.score >= 90 ? C.good : C.bad};opacity:${c.agent === "energy-agent" ? 1 : .55};border-radius:0 6px 6px 0;transition-delay:${i * 0.08}s"></div>
        <div style="position:absolute;left:90%;top:-6px;bottom:-6px;width:2px;background:${C.ink}"></div>
      </div>
      <div class="num" style="font-size:22px;font-weight:800">${c.measurable === false ? "n/m" : c.score}</div></div>`).join("") +
    `<div class="cap" style="text-align:right;margin-right:74px">admission bar 90 · green would be admitted</div>` +
    (cards.some((c) => c.measurable === false) ? `<div class="lbl" style="font-size:15px">n/m = not measurable: too few runs decided (coverage under 80 %, mostly runs with no final report).</div>` : "");
})();

// ------------------------------------------------------------------ 7 · admit: change one word
(function admit() {
  const card = (D.netcrash.scorecards || []).find((c) => c.agent === "energy-agent");
  const h = card ? card.card_sha256 : "0dc0865b50bb";
  hooks.s8 = (s) => {
    const changed = s >= 2;
    $("#cardhash").textContent = changed ? "hash 7f21a0c4… (edited)" : `hash ${h.slice(0, 12)}…`;
    $("#cardhash").style.color = changed ? C.badInk : "";
    const st = $("#stamp");
    st.classList.toggle("in", s >= 1);
    st.classList.toggle("red", changed);
    st.textContent = changed ? "NO MATCH" : "ATTESTED";
    const g = $("#gate");
    g.textContent = changed ? "Refused" : "Admitted";
    g.style.color = changed ? C.badInk : C.goodInk;
  };
  $$(".arrow").forEach((a) => a.classList.add("r"));
})();

fillK();
update();

// ------------------------------------------------------------------ ?at=<scene>:<step> jumps straight to a step (PDF export: tools/export_pdf.py)
{
  const at = new URLSearchParams(location.search).get("at");
  if (at) {
    const [id, k] = at.split(":"), sc = document.getElementById(id);
    if (sc) {
      document.body.classList.add("capture");
      scenes.forEach((o) => { if (o !== sc) o.style.display = "none"; });
      sc.style.height = "100vh";
      const step = Math.min(+k, +sc.dataset.steps - 1);
      $$("[data-s]", sc).forEach((e) => {
        const on = step >= +e.dataset.s && (e.dataset.out === undefined || step < +e.dataset.out);
        if (e.dataset.count !== undefined) {
          if (on) e.textContent = parseFloat(e.dataset.count).toFixed(+(e.dataset.dec || 0));
        } else e.classList.toggle("in", on);
      });
      hooks[sc.id]?.(step);
      if (sc.id === "s1") { clearInterval(clockTimer); $("#clock").textContent = step >= 1 ? "22:00" : "14:00"; }
      document.body.classList.toggle("dark", sc.classList.contains("dark"));
    }
  }
}
