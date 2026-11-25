// Yövahti dashboard: static, reads data/dashboard.json (scripts/export_dashboard.py).
const D = await (await fetch("data/dashboard.json")).json();
const $ = (s) => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const fmt = (x, d = 1) => Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const css = (v) => getComputedStyle($(".viz-root")).getPropertyValue(v).trim();

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
function svg(w, h, host) {
  const s = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img" });
  host.replaceChildren(s);
  return s;
}
const tip = $("#tip");
function showTip(ev, html) {
  tip.innerHTML = html; tip.hidden = false;
  const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = `${x}px`; tip.style.top = `${ev.clientY + 14}px`;
}
function hover(node, html) {
  node.addEventListener("mousemove", (e) => showTip(e, typeof html === "function" ? html() : html));
  node.addEventListener("mouseleave", () => (tip.hidden = true));
}
function table(host, head, rows) {
  const t = document.createElement("table");
  t.innerHTML = `<thead><tr>${head.map((h, i) => `<th class="${i ? "num" : ""}">${h}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i ? "num" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody>`;
  host.replaceChildren(t);
}
document.querySelectorAll("[data-table]").forEach((b) =>
  b.addEventListener("click", () => {
    const t = $(`#${b.dataset.table}-table`);
    t.hidden = !t.hidden;
    b.textContent = t.hidden ? "Table view" : "Hide table";
  }));

// ------------------------------------------------------------------ tiles
const R = D.results;
const m = Object.fromEntries(R.methods.map((x) => [x.name, x]));
const b4 = m["B4 Yövahti planner"], b1 = m["B1 static thresholds"], b2 = m["B2 published method (reconstruction)"], orc = m["Oracle (perfect foresight)"];
const tile = (label, value, delta, hero = false) =>
  `<div class="tile${hero ? " hero" : ""}"><div class="label">${label}</div><div class="value">${value}</div>${delta ? `<div class="delta">${delta}</div>` : ""}</div>`;
$("#tiles").innerHTML =
  tile("Radio energy saved", `${fmt(b4.kwh_saved_pct)} %`, `capacity radios ${fmt(b4.capacity_radio_saved_pct, 0)} % · 749 real sectors`, true) +
  tile("Congestion vs static thresholds", `${fmt(b1.congested_qh_per_sector_day / b4.congested_qh_per_sector_day, 0)}× less`, `${fmt(b2.congested_qh_per_sector_day / b4.congested_qh_per_sector_day, 0)}× less than the B2 reconstruction`) +
  tile("Share of the oracle’s savings", `${fmt((100 * b4.kwh_saved_pct) / orc.kwh_saved_pct, 0)} %`, "without hindsight") +
  tile("Forecast skill vs seasonal naive", `+${fmt(R.forecast_skill_pct.nr, 0)}–${fmt(R.forecast_skill_pct.low, 0)} %`, `P10–P90 covers ${fmt(R.forecast_coverage_pct.nr, 0)}–${fmt(R.forecast_coverage_pct.low, 0)} %`);

// ------------------------------------------------------------------ trade-off chart
(function tradeoff() {
  $("#tradeoff-sub").textContent = `${R.period}, ${R.sectors} sectors, TR 38.864 Category 1. Up and left is better.`;
  const W = 980, H = 380, P = { l: 56, r: 190, t: 34, b: 44 };
  const s = svg(W, H, $("#tradeoff"));
  const others = R.methods.filter((x) => !x.name.startsWith("B4 Yövahti"));
  const xmax = 5.5, ymin = 10, ymax = 24;
  const X = (v) => P.l + (Math.min(v, xmax) / xmax) * (W - P.l - P.r);
  const Y = (v) => H - P.b - ((v - ymin) / (ymax - ymin)) * (H - P.t - P.b);
  const g = el("g", { class: "grid" }, s);
  for (let y = 10; y <= 24; y += 2) {
    el("line", { x1: P.l, x2: W - P.r, y1: Y(y), y2: Y(y) }, g);
    el("text", { x: P.l - 8, y: Y(y) + 4, "text-anchor": "end", class: "tick" }, s).textContent = `${y} %`;
  }
  for (let x = 0; x <= 5; x += 1) el("text", { x: X(x), y: H - P.b + 18, "text-anchor": "middle" }, s).textContent = x;
  el("line", { x1: P.l, x2: W - P.r, y1: H - P.b, y2: H - P.b, stroke: css("--axis") }, s);
  el("text", { x: (P.l + W - P.r) / 2, y: H - 6, "text-anchor": "middle" }, s).textContent = "Congested quarter-hours per sector-day →";
  el("text", { x: P.l - 8, y: 12, "text-anchor": "end" }, s).textContent = "Energy saved ↑";
  // others: gray, direct-labelled
  for (const o of others) {
    const c = el("circle", { cx: X(o.congested_qh_per_sector_day), cy: Y(o.kwh_saved_pct), r: 5, fill: css("--gray-mark"), stroke: css("--surface-1"), "stroke-width": 2 }, s);
    const lbl = o.name.replace(" (perfect foresight)", "").replace(" (reconstruction)", " (recon.)");
    el("text", { x: X(o.congested_qh_per_sector_day) + 9, y: Y(o.kwh_saved_pct) + 4 }, s).textContent = lbl;
    hover(c, `<b>${o.name}</b><br>${fmt(o.kwh_saved_pct)} % saved · ${fmt(o.congested_qh_per_sector_day, 2)} congested QH/sector-day<br>${fmt(o.unserved_gb / 1000, 2)} TB past capacity · ${o.watchdog_wakes.toLocaleString()} wake-ups`);
  }
  // B4 curve: the one series in colour
  const pts = R.margin_curve.map((p) => [X(p.congested_qh_per_sector_day), Y(p.kwh_saved_pct)]);
  el("path", { d: "M" + pts.map((p) => p.join(",")).join("L"), fill: "none", stroke: css("--series-1"), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
  R.margin_curve.forEach((p, i) => {
    const c = el("circle", { cx: pts[i][0], cy: pts[i][1], r: 5, fill: css("--series-1"), stroke: css("--surface-1"), "stroke-width": 2 }, s);
    hover(c, `<b>B4 Yövahti, margin ${p.margin}</b><br>${fmt(p.kwh_saved_pct)} % saved · ${fmt(p.congested_qh_per_sector_day, 2)} congested QH/sector-day<br>${fmt(p.unserved_gb / 1000, 2)} TB past capacity · ${p.watchdog_wakes.toLocaleString()} wake-ups`);
  });
  const last = pts[0];
  el("text", { x: last[0] + 9, y: last[1] - 8, class: "label-strong" }, s).textContent = "B4 Yövahti (margin 1.0 → 1.5)";
  table($("#tradeoff-table"), ["Method", "Energy saved", "Congested QH / sector-day", "Past capacity", "Wake-ups"],
    [...R.methods.map((x) => [x.name, `${fmt(x.kwh_saved_pct)} %`, fmt(x.congested_qh_per_sector_day, 2), `${fmt(x.unserved_gb / 1000, 2)} TB`, x.watchdog_wakes.toLocaleString()]),
     ...R.margin_curve.map((p) => [`B4 margin ${p.margin}`, `${fmt(p.kwh_saved_pct)} %`, fmt(p.congested_qh_per_sector_day, 2), `${fmt(p.unserved_gb / 1000, 2)} TB`, p.watchdog_wakes.toLocaleString()])]);
})();

// ------------------------------------------------------------------ event value
(function events() {
  const E = D.events?.match;
  if (!E) { $("#events").hidden = true; return; }
  const order = Object.keys(E.summary).filter((k) => !k.startsWith("B0"));
  const nice = (k) => k.replace("agent otari:", "Agent · ").replace("agent featherless:", "Agent · ").replace("B4 rolling (hourly re-plan)", "B4 re-planning hourly");
  $("#events-sub").textContent = `${E.episodes} episodes (clusters × nights), a crowd surge on three sectors each, announced only in the event calendar. Same gate, same simulator.`;
  function bars(host, key, unit, digits) {
    const W = 480, rowH = 34, P = { l: 210, r: 70, t: 6 }, H = P.t + rowH * order.length;
    const s = svg(W, H, host);
    const max = Math.max(...order.map((k) => E.summary[k][key])) || 1;
    order.forEach((k, i) => {
      const v = E.summary[k][key], y = P.t + i * rowH + 7, w = (v / max) * (W - P.l - P.r);
      el("text", { x: P.l - 10, y: y + 15, "text-anchor": "end" }, s).textContent = nice(k);
      const agent = k.startsWith("agent");
      const r = el("path", { d: barPath(P.l, y, Math.max(w, 0.5), 20), fill: agent ? css("--series-1") : css("--gray-mark") }, s);
      el("text", { x: P.l + w + 8, y: y + 15, class: agent ? "label-strong" : "" }, s).textContent = `${fmt(v, digits)}${unit}`;
      hover(r, `<b>${nice(k)}</b><br>${fmt(E.summary[k].kwh_saved_pct)} % saved · ${fmt(E.summary[k].congested_qh, 0)} congested QH · ${fmt(E.summary[k].unserved_gb, 2)} GB unserved (n=${E.summary[k].episodes})`);
    });
  }
  bars($("#ev-cong"), "congested_qh", "", 0);
  bars($("#ev-save"), "kwh_saved_pct", " %", 1);
  table($("#events-table"), ["Arm", "Energy saved", "Congested QH", "Unserved", "Episodes"],
    order.map((k) => [nice(k), `${fmt(E.summary[k].kwh_saved_pct)} %`, fmt(E.summary[k].congested_qh, 0), `${fmt(E.summary[k].unserved_gb, 2)} GB`, E.summary[k].episodes]));
})();
function barPath(x, y, w, h) { // 4px rounded data-end, square at the baseline
  const r = Math.min(4, w / 2);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}

// ------------------------------------------------------------------ replay heatmap
(function replay() {
  const P = D.replay;
  if (!P) { $("#replay").hidden = true; return; }
  const arms = Object.keys(P.arms);
  let arm = arms[arms.length - 1];
  $("#replay-sub").textContent = `Cluster ${P.cluster}, ${P.night} 22:00 → 08:00, ${P.sectors.length} real sectors. A synthetic crowd surge hits the marked sectors ${P.times[P.event_window[0]]}–${P.times[P.event_window[1]]}; only the calendar says so.`;
  const sw = $("#arm-switch");
  arms.forEach((a) => {
    const b = document.createElement("button"); b.textContent = a; b.setAttribute("role", "tab");
    b.addEventListener("click", () => { arm = a; draw(); }); sw.appendChild(b);
  });
  $("#replay-legend").innerHTML = [["--series-1", "both capacity radios asleep"], ["--series-1-soft", "one asleep"], ["--awake", "awake"], ["--critical", "congested ✕"]]
    .map(([v, t]) => `<span><span class="sw" style="background:var(${v})"></span>${t}</span>`).join("") + `<span>⚑ event sectors</span>`;
  function draw() {
    [...sw.children].forEach((b) => b.setAttribute("aria-selected", String(b.textContent === arm)));
    const A = P.arms[arm];
    $("#replay-tiles").innerHTML = tile("Energy saved (cluster, night)", `${fmt(A.kwh_saved_pct)} %`) +
      tile("Congested sector-quarter-hours", `${A.congested_qh}`) + tile("Traffic not served", `${fmt(A.unserved_gb, 2)} GB`);
    const n = P.times.length, S = P.sectors.length, cw = 20, ch = 14, L = 74, T = 22;
    const s = svg(L + n * cw + 10, T + S * ch + 6, $("#heat"));
    const [e0, e1] = P.event_window;
    el("rect", { x: L + e0 * cw - 1, y: T - 4, width: (e1 - e0) * cw + 2, height: S * ch + 6, fill: "none", stroke: css("--text-secondary"), "stroke-width": 1, rx: 4 }, s);
    for (let t = 0; t < n; t += 4) el("text", { x: L + t * cw, y: 12, class: "tick" }, s).textContent = P.times[t];
    for (let i = 0; i < S; i++) {
      const ev = P.event_sectors.includes(i);
      el("text", { x: L - 6, y: T + i * ch + 10, "text-anchor": "end", class: ev ? "label-strong" : "tick" }, s).textContent = (ev ? "⚑ " : "") + P.sectors[i];
      for (let t = 0; t < n; t++) {
        const asleep = A.mid[i][t] + (P.has_nr[i] ? A.nr[i][t] : 0), full = P.has_nr[i] ? 2 : 1;
        const cong = A.congested[i][t];
        const fill = cong ? css("--critical") : asleep === full ? css("--series-1") : asleep ? css("--series-1-soft") : css("--awake");
        const r = el("rect", { x: L + t * cw, y: T + i * ch, width: cw - 2, height: ch - 2, rx: 2, fill }, s);
        if (cong) el("text", { x: L + t * cw + cw / 2 - 1, y: T + i * ch + 10, "text-anchor": "middle", fill: "#fff", "font-size": 9 }, s).textContent = "✕";
        hover(r, () => `<b>${P.sectors[i]}</b> ${P.times[t]}${ev && t >= e0 && t < e1 ? " · crowd surge" : ""}<br>mid band ${A.mid[i][t] ? "asleep" : "awake"}${P.has_nr[i] ? ` · NR 3500 ${A.nr[i][t] ? "asleep" : "awake"}` : ""}${cong ? "<br><b>congested</b>" : ""}`);
      }
    }
  }
  draw();
  $("#calls").innerHTML = P.agent_calls.map((c) => `<li class="${c.error ? "err" : ""}"><code>${c.tool}</code> <span class="args">${esc(JSON.stringify(c.args)).slice(0, 140)}</span>${c.error ? " (error)" : ""}${/refused/.test(c.result) ? ` <span class="err">refused</span>` : ""}</li>`).join("");
  $("#answer").textContent = P.agent_answer || "(no report)";
})();
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

// ------------------------------------------------------------------ NetCrash matrix
(function netcrash() {
  const N = D.netcrash;
  const cards = (N.scorecards || []).sort((a, b) => (a.agent + a.model).localeCompare(b.agent + b.model));
  if (!cards.length) { $("#netcrash").hidden = true; return; }
  const ICON = { pass: ["✓", "--good", "pass"], fail: ["✕", "--critical", "fail"], flaky: ["~", "--warning", "flaky"], inconclusive: ["?", "--muted", "needs judge"], not_applicable: ["–", "--muted", "not applicable"], error: ["!", "--muted", "error"] };
  $("#nc-legend").innerHTML = Object.values(ICON).map(([i, v, t]) => `<span><span class="status-dot" style="background:var(${v})"></span>${i} ${t}</span>`).join("");
  // v1 and v2 cards side by side: one column per test id, blank where a suite lacks it
  const byNum = (a, b) => +a.slice(1) - +b.slice(1);
  const tests = [...new Set(cards.flatMap((c) => c.tests.map((t) => t.id)))].sort(byNum);
  const titles = Object.fromEntries(cards.flatMap((c) => c.tests.map((t) => [t.id, t.title])));
  const hasN20 = tests.includes("N20");
  const n20 = hasN20 ? {} : Object.fromEntries((N.n20 || []).map((x) => [`${x.agent}|${x.model}`, x]));
  const extraN20 = !hasN20 && N.n20?.length;
  const head = `<tr><th>Agent</th><th>Model</th><th class="num">Suite</th><th class="num">Score</th><th class="num">Coverage</th>${tests.map((t) => `<th class="v">${t}</th>`).join("")}${extraN20 ? '<th class="v">N20</th>' : ""}<th class="num">Cost</th></tr>`;
  const cell = (v, ev, title) => { const [i, c, t] = ICON[v] || ["?", "--muted", v]; return `<td class="v v-${v}" data-tip="${esc(title + ": " + t + (ev ? " — " + ev : ""))}"><span class="status-dot" style="background:var(${c})"></span>${i}</td>`; };
  const rows = cards.map((c) => { const by = Object.fromEntries(c.tests.map((t) => [t.id, t]));
    return `<tr><td>${c.agent}</td><td>${c.model}</td><td class="num">v${c.suite || 1}</td><td class="num"><b>${c.measurable === false ? "n/m" : c.score}</b></td><td class="num">${c.coverage} %</td>` +
    tests.map((id) => by[id] ? cell(by[id].verdict, by[id].evidence.filter(Boolean)[0], `${id} ${by[id].title}`) : "<td></td>").join("") +
    (extraN20 ? (n20[`${c.agent}|${c.model}`] ? cell(n20[`${c.agent}|${c.model}`].verdict, "", "N20 calendar_injection") : "<td></td>") : "") +
    `<td class="num">€${fmt(c.cost_eur, 2)}</td></tr>`; }).join("");
  $("#matrix").innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  $("#matrix").querySelectorAll("[data-tip]").forEach((n) => hover(n, esc(n.dataset.tip)));
  $("#nc-tests").textContent = "Tests: " + tests.map((id) => `${id} ${titles[id].replaceAll("_", " ")}`).join(" · ") + (extraN20 ? " · N20 calendar injection" : "") + ". n/m = not measurable (coverage under 80 %).";
})();

// ------------------------------------------------------------------ other companies' methods
(function industry() {
  const I = D.industry;
  if (!I) { $("#industry").hidden = true; return; }
  const rows = Object.entries(I).filter(([k]) => !k.startsWith("B0")).map(([k, v]) => [
    /Yovahti/.test(k) ? `<b>${esc(k.replace("Yovahti", "Yövahti"))}</b>` : esc(k),
    `${fmt(v.kwh_saved_pct)} %`, fmt(v.congested_qh_per_sector_day, 2),
    v.share_of_oracle_pct == null ? "" : `${fmt(v.share_of_oracle_pct, 0)} %`,
    fmt(v.toggles_per_sector_day, 1)]);
  table($("#industry-table"), ["Method", "Energy saved", "Congested ¼-h / sector-day", "Share of oracle", "Toggles / sector-day"], rows);
})();

// ------------------------------------------------------------------ interfaces (full / constrained / workflow)
(function interfaces() {
  const Mo = D.netcrash.modes || [];
  if (!Mo.length) { $("#interfaces").hidden = true; return; }
  const mode = (a) => a.endsWith("-workflow") ? "workflow" : a.endsWith("-c") ? "constrained" : "full";
  const order = { full: 0, constrained: 1, workflow: 2 };
  const short = (m) => m.includes("DeepSeek") ? "DeepSeek V4 Flash" : m;
  const rows = Mo.slice().sort((a, b) => short(a.model).localeCompare(short(b.model)) || a.agent.startsWith("sloppy") - b.agent.startsWith("sloppy") || order[mode(a.agent)] - order[mode(b.agent)])
    .map((m) => [`${short(m.model)} · ${m.agent.startsWith("sloppy") ? "sloppy" : "careful"} prompt`, mode(m.agent), `<b>${m.score}</b>`, m.decided, m.failed.length ? m.failed.join(", ") : "none", `€${fmt(m.cost_eur, 3)}`]);
  table($("#interfaces-table"), ["Model · prompt", "Interface", "Score", "Model-decided tests", "Failed or flaky", "Cost"], rows);
})();

// ------------------------------------------------------------------ attestation + in-browser verification
(function attestation() {
  const A = D.netcrash.attestation, K = D.netcrash.jwks;
  if (!A) { $("#att").innerHTML = '<p class="note">No attestation exported yet.</p>'; $("#verify").hidden = true; return; }
  const stmt = JSON.parse(new TextDecoder().decode(b64d(A.payload)));
  const p = stmt.predicate, model = p.configuration.find((c) => c.name === "model");
  $("#att").innerHTML = `<table class="plain"><tr><th>Subject (Agent Card)</th><td><code>${stmt.subject[0].name}</code><br><code>jcs_sha256 ${stmt.subject[0].digest.jcs_sha256}</code></td></tr>
    <tr><th>Model</th><td>${model.annotations.model} via ${model.uri}</td></tr>
    <tr><th>Result</th><td>${p.result} · score ${p.score} · coverage ${p.coverage} % · expires ${p.expiresAt.slice(0, 10)}</td></tr>
    <tr><th>Signed by</th><td><code>${A.signatures[0].keyid}</code></td></tr></table>
    <p class="verdict-line" id="vres"></p><details><summary>Envelope</summary><pre>${esc(JSON.stringify(A, null, 1))}</pre></details>`;
  $("#verify").addEventListener("click", async () => {
    const out = $("#vres");
    try {
      const jwk = K.keys.find((k) => k.kid === A.signatures[0].keyid);
      const key = await crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x: jwk.x }, { name: "Ed25519" }, false, ["verify"]);
      const body = b64d(A.payload), type = new TextEncoder().encode(A.payloadType);
      const head = new TextEncoder().encode(`DSSEv1 ${type.length} ${A.payloadType} ${body.length} `);
      const pae = new Uint8Array(head.length + body.length); pae.set(head); pae.set(body, head.length);
      const ok = await crypto.subtle.verify("Ed25519", key, b64d(A.signatures[0].sig), pae);
      out.innerHTML = ok ? `<span style="color:var(--good-text)">✓ Signature verifies</span> against the tester key published in the repo (DSSE PAE, Ed25519, computed here in your browser).` : `<span style="color:var(--critical)">✕ Signature does not verify.</span>`;
    } catch (e) { out.textContent = `This browser can’t verify Ed25519 in WebCrypto (${e.name}). Use a current Chrome, Firefox or Safari.`; }
  });
})();
function b64d(s) { const t = atob(s.replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(t, (c) => c.charCodeAt(0)); }
