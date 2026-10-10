/* Q2E single-page app - vanilla JS, no build step. */
"use strict";

const S = { meta: null, project: null, run: null, results: null, summary: null, poll: null, lit: null, watch: null, proposal: null,
            ask: { cycles: ["P"], source: "auto", provider: "", dataset: "" }, dict: null };
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nice = (s) => esc(s).replace(/&gt;=/g, "≥").replace(/&lt;=/g, "≤");
const pct = (x, d = 1) => (x == null ? "NA" : (100 * x).toFixed(d) + "%");
const fx = (x, d = 2) => (x == null || Number.isNaN(x) ? "NA" : Number(x).toFixed(d));
const pfmt = (p) => (p == null ? "NA" : p < 0.001 ? "<.001" : (p < 0.01 ? p.toFixed(3) : p.toFixed(2)).replace(/^0/, ""));
const store = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.headers = { "content-type": "application/json" }; o.body = JSON.stringify(o.body); }
  const r = await fetch(path, o);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || (data && data.detail && JSON.stringify(data.detail)) || r.statusText);
  return data;
}
function toast(msg, err = false) {
  const t = document.createElement("div"); t.className = "toast" + (err ? " err" : ""); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), err ? 7000 : 3200);
}

/* ------------------------------------------------------------------ routing */
const STEPS = [
  { id: "protocol", label: "Protocol" }, { id: "map", label: "Data map" }, { id: "plan", label: "Analysis plan" },
  { id: "run", label: "Run & validate" }, { id: "results", label: "Results" }, { id: "signoff", label: "Sign-off" },
];
function route() {
  const h = location.hash.replace(/^#\/?/, "").split("/");
  if (h[0] === "p" && h[1]) return { view: "project", pid: h[1], stage: h[2] || "protocol" };
  if (h[0] === "projects") return { view: "projects" };
  if (h[0] === "library") return { view: "library" };
  return { view: "ask" };
}
function go(stage) { location.hash = `#/p/${S.project.id}/${stage}`; }
window.addEventListener("hashchange", render);

function latestRun() { const r = S.project?.runs || []; return r.length ? r[r.length - 1] : null; }
function unlocked(stage) {
  const p = S.project; if (!p) return false;
  const lr = latestRun();
  if (["protocol", "map", "plan"].includes(stage)) return true;
  if (stage === "run") return p.approved_current || !!lr;
  if (stage === "results") return lr && lr.status === "completed";
  if (stage === "signoff") return lr && lr.status === "completed";
  return false;
}
function stageDone(stage) {
  const p = S.project; if (!p) return false; const lr = latestRun();
  const appr = p.approved_current || !!lr;
  return { protocol: appr, map: appr, plan: appr, run: lr && lr.status === "completed", results: !!p.signoff, signoff: !!p.signoff }[stage];
}

/* ------------------------------------------------------------------ chrome */
function renderBoundary() {
  const b = S.meta?.boundary; const l = S.meta?.llm; if (!b) return;
  const el = $("#boundary");
  const mode = l.enabled ? `${l.provider} · ${l.model}` : "offline agents";
  el.className = "chip " + (b.allowed ? "ok" : "bad");
  el.title = b.message + " Row-level data never sent to LLMs.";
  el.innerHTML = `● ${esc(mode)} · ${esc(b.policy)} data policy`;
}
function renderRail(r) {
  const rail = $("#rail"); const ms = $("#mobileSteps");
  if (r.view !== "project" || !S.project) {
    rail.innerHTML = `<h4>Workflow</h4><ol class="steps">${["Ask", ...STEPS.map((s) => s.label)].map((l, i) =>
      `<li class="${i === 0 && r.view === "ask" ? "active" : "locked"}"><span class="n">${i}</span>${l}</li>`).join("")}</ol>
      <h4>How it works</h4><p class="small muted">Agents draft · you edit & approve · the R engine executes · automated QC · you sign off. Every step is recorded in a hash-chained provenance ledger.</p>`;
    ms.innerHTML = ""; return;
  }
  const p = S.project;
  rail.innerHTML = `<h4>Study</h4><p class="small" style="margin:0 0 14px"><b>${esc(p.plan.title)}</b><br><span class="muted">${esc(p.id)} · plan v${p.plan.version}</span></p>
    <ol class="steps"><li data-act="home"><span class="n">0</span>Ask</li>${STEPS.map((s, i) => {
      const cls = r.stage === s.id ? "active" : stageDone(s.id) ? "done" : unlocked(s.id) ? "" : "locked";
      return `<li class="${cls}" data-act="${unlocked(s.id) ? "go" : ""}" data-stage="${s.id}"><span class="n">${stageDone(s.id) && r.stage !== s.id ? "✓" : i + 1}</span>${s.label}</li>`;
    }).join("")}</ol>
    <h4>Provenance <span class="chip ${p.chain.valid ? "ok" : "bad"}" style="font-size:10px">${p.chain.valid ? "chain valid" : "chain broken"}</span></h4>
    <ul class="timeline">${p.events.slice(-9).reverse().map((e) => `<li><b>${esc(e.action.replace(/_/g, " "))}</b> · ${esc(e.actor)}<small>${esc(e.at.slice(5, 16).replace("T", " "))} · ${esc(e.hash.slice(0, 8))}</small></li>`).join("")}</ul>`;
  ms.innerHTML = STEPS.map((s) => `<button class="btn sm ${r.stage === s.id ? "primary" : ""}" data-act="${unlocked(s.id) ? "go" : ""}" data-stage="${s.id}" ${unlocked(s.id) ? "" : "disabled"}>${s.label}</button>`).join("");
}

/* ------------------------------------------------------------------ main render */
async function render() {
  const r = route(); const main = $("#main");
  clearInterval(S.poll);
  try {
    if (r.view === "project") {
      if (!S.project || S.project.id !== r.pid) { S.project = await api(`/api/projects/${r.pid}`); S.results = null; S.lit = null; }
      const lr = latestRun();
      if (lr && (!S.run || S.run.id !== lr.id || S.run.status === "running")) S.run = await api(`/api/projects/${r.pid}/runs/${lr.id}`);
      if (lr && S.run?.status === "completed" && (!S.results || S.results._rid !== lr.id)) {
        S.results = await api(`/api/projects/${r.pid}/runs/${lr.id}/results`); S.results._rid = lr.id;
        S.summary = await api(`/api/projects/${r.pid}/runs/${lr.id}/summary`);
      }
    }
  } catch (e) { main.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; return; }
  renderRail(r);
  const views = { ask: viewAsk, projects: viewProjects, library: viewLibrary };
  if (r.view === "project") {
    const fn = { protocol: viewProtocol, map: viewMap, plan: viewPlan, run: viewRun, results: viewResults, signoff: viewSignoff }[r.stage] || viewProtocol;
    main.innerHTML = fn();
    if (r.stage === "run" && S.run?.status === "running") startPolling();
  } else main.innerHTML = await views[r.view]();
  window.scrollTo({ top: 0 });
}
function rerender() { const y = window.scrollY; render().then(() => window.scrollTo({ top: y })); }

/* ------------------------------------------------------------------ ASK */
async function viewAsk() {
  const k = S.meta.knowledge; const a = S.ask;
  const cyc = Object.entries(k.cycles).map(([id, c]) => `<button class="${a.cycles.includes(id) ? "on" : ""}" data-act="cycle" data-id="${id}" title="${esc(c.note || "")}">${esc(c.label.replace("NHANES ", ""))}</button>`).join("");
  const src = [["auto", "CDC download / local"], ["local", "Local XPT folder"], ["synthetic", "Synthetic demo"]].map(([v, l]) => `<button class="${a.source === v ? "on" : ""}" data-act="source" data-v="${v}">${l}</button>`).join("");
  const provs = ["", "offline", "anthropic", "azure_openai", "bedrock", "openai", "ollama"];
  const ds = S.meta.datasets || [];
  const recent = (await api("/api/projects")).slice(0, 6);
  const dataNote = S.meta.data.local_files ? `${S.meta.data.local_files} NHANES files found in ${esc(S.meta.data.local_dir)}` :
    S.meta.data.allow_download ? "Files download from CDC on first use and are cached." : "Downloads disabled: place NHANES .xpt files in the local folder or use synthetic data.";
  return `<h1 class="page">From clinical observation to reproducible evidence</h1>
  <p class="lede">Describe a research idea in plain language. Q2E's agents turn it into a protocol, map it to NHANES (or your own open dataset), and draft a statistical analysis plan for your approval. Nothing runs until you approve it, and nothing is final until you sign off.</p>
  <div class="card">
    <textarea id="q" class="ask" placeholder="e.g. Do a research study on the prevalence of functional iron deficiency in US adults.">${esc(store.get("q2e.q", ""))}</textarea>
    <div class="examples">${k.examples.map((e) => `<button data-act="example" data-q="${esc(e.question)}" title="${esc(e.title)}">${esc(e.title)}</button>`).join("")}</div>
    <div class="grid g3" style="margin-top:16px">
      <label class="field">Dataset<select id="dsSel"><option value="">NHANES (public)</option>${ds.map((d) => `<option value="${d.id}" ${a.dataset === d.id ? "selected" : ""}>${esc(d.name)} (uploaded)</option>`).join("")}</select></label>
      <label class="field">AI agents<select id="provSel">${provs.map((p) => `<option value="${p}" ${a.provider === p ? "selected" : ""}>${p === "" ? `Server default (${esc(S.meta.llm.provider)})` : p}</option>`).join("")}</select></label>
      <div class="field">Voice<div class="row"><button class="btn" data-act="mic" id="micBtn">🎙 Dictate</button><span class="tiny muted">${S.meta.voice ? "ElevenLabs Scribe" : "browser speech"}</span></div></div>
    </div>
    <div class="row" style="margin-top:14px;justify-content:space-between">
      <div class="row"><span class="small muted">Cycles</span><div class="seg">${cyc}</div></div>
      <div class="row"><span class="small muted">Data</span><div class="seg">${src}</div></div>
    </div>
    <p class="tiny muted" style="margin:8px 0 0">${dataNote}</p>
    <div class="row" style="margin-top:16px"><button class="btn" data-act="assess" id="assessBtn">Can NHANES answer this?</button><button class="btn primary" data-act="design" id="designBtn">Design my study →</button>
      <span class="small muted">Agents: Investigator · Data Steward · Epidemiologist · Statistician · Reviewer</span></div>
  </div>
  ${S.assess ? `<div style="margin-top:14px">${answerCard(S.assess)}</div>` : ""}
  <div class="grid g2" style="margin-top:18px">
    <div class="card"><h3 class="sub" style="margin-top:0">Recent projects</h3>${recent.length ? recent.map((p) => `<div class="crit"><div class="lbl"><a href="#/p/${p.id}/protocol">${esc(p.title)}</a><div class="tiny muted">${esc(p.created.slice(0, 16).replace("T", " "))} · ${p.runs} run(s)</div></div><span class="chip ${p.signed ? "ok" : "info"}">${p.signed ? "signed" : esc(p.status)}</span></div>`).join("") : `<p class="muted small">No projects yet.</p>`}</div>
    <div class="card"><h3 class="sub" style="margin-top:0">Bring your own open dataset</h3>
      <p class="small muted" style="margin-top:0">Upload a CSV and (optionally) its data dictionary. Q2E detects weight/strata/PSU columns and maps building blocks to your variables for review.</p>
      <div class="grid" style="gap:8px"><input type="text" id="dsName" placeholder="Dataset name (e.g. BRFSS 2024 extract)">
      <label class="field">Data (.csv)<input type="file" id="dsData" accept=".csv"></label>
      <label class="field">Data dictionary (.csv, optional)<input type="file" id="dsDict" accept=".csv"></label>
      <button class="btn" data-act="upload">Upload dataset</button></div></div>
  </div>`;
}

/* ------------------------------------------------------------------ PROJECTS / LIBRARY */
async function viewProjects() {
  const ps = await api("/api/projects");
  return `<h1 class="page">Projects</h1><div class="card"><table class="t"><thead><tr><th>Study</th><th>Created</th><th>Runs</th><th>Status</th></tr></thead><tbody>${ps.map((p) =>
    `<tr><td><a href="#/p/${p.id}/protocol">${esc(p.title)}</a><div class="tiny muted">${esc(p.question)}</div></td><td class="num">${esc(p.created.slice(0, 10))}</td><td class="num">${p.runs}</td><td><span class="chip ${p.signed ? "ok" : "info"}">${p.signed ? "signed" : esc(p.status)}</span></td></tr>`).join("") || `<tr><td colspan=4 class="muted">None yet</td></tr>`}</tbody></table></div>`;
}
async function viewLibrary() {
  const defs = await api("/api/guidelines");
  const by = {}; defs.forEach((d) => (by[d.concept] = by[d.concept] || []).push(d));
  const watch = S.watch ? `<div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Guideline watch (PubMed, newest first)</h3>${S.watch.map((w) => `<div class="crit"><div class="lbl"><b>${esc(w.label)}</b> <span class="tiny muted">library year ${w.library_year}</span>${w.error ? `<div class="tiny" style="color:var(--bad)">${esc(w.error)}</div>` : ""}<ul class="small">${w.candidates.map((c) => `<li><a href="${c.url}" target="_blank" rel="noopener">${esc(c.title)}</a> <span class="muted">${esc(c.journal)} ${esc(c.pubdate)}</span></li>`).join("") || "<li class='muted'>No newer records</li>"}</ul></div></div>`).join("")}</div>` : "";
  const prop = S.proposal ? `<div class="defcard" style="margin-top:10px"><span class="status proposed">proposed</span><h5>${esc(S.proposal.label)}</h5><p class="small">${nice(S.proposal.criteria_text)}</p><code>${esc(S.proposal.expr)}</code><ul class="small">${(S.proposal.operational_notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul><div class="row"><input type="text" id="propBy" placeholder="Your name" value="${esc(store.get("q2e.name", ""))}"><button class="btn primary sm" data-act="approveDef">Approve into library</button></div></div>` : "";
  return `<h1 class="page">Definitions library</h1><p class="lede">Versioned, citable case definitions made computable. Status shows how each threshold was verified; operational notes list every assumption needed to compute a clinical guideline in survey data.</p>
  <div class="row" style="margin-bottom:14px"><button class="btn" data-act="watch">Check PubMed for guideline updates</button></div>
  ${Object.entries(by).map(([c, ds]) => `<h2 class="sec">${esc(c.replace(/_/g, " "))}</h2><div class="grid g2">${ds.map(defCard).join("")}</div>`).join("")}
  ${watch}
  <div class="card" style="margin-top:20px"><h3 class="sub" style="margin-top:0">Import a new guideline (LLM-assisted, human-approved)</h3>
  <p class="small muted" style="margin-top:0">Paste the recommendation text (e.g. from a new KDIGO/ASH/Baveno statement). The curator agent drafts a computable definition; it cannot be used until you approve it.</p>
  <textarea id="gtext" rows="5" placeholder="Paste guideline text…"></textarea><div class="row" style="margin-top:8px"><button class="btn" data-act="importDef">Draft definition</button><span class="tiny muted">Requires an approved LLM provider.</span></div>${prop}</div>`;
}
function defCard(d) {
  const src = d.source || {};
  const link = src.url ? `<a href="${esc(src.url)}" target="_blank" rel="noopener">source</a>` : src.doi ? `<a href="https://doi.org/${esc(src.doi)}" target="_blank" rel="noopener">doi</a>` : "";
  return `<div class="defcard"><div class="row" style="justify-content:space-between"><span class="status ${esc(d.status)}">${esc(d.status)}</span><span class="tiny muted">${esc(src.year || "")} ${link}</span></div>
  <h5 style="margin-top:6px">${nice(d.label)}</h5><p class="small" style="margin:4px 0">${nice(d.criteria_text)}</p><code class="tiny">${esc(d.expr)}</code>
  ${(d.operational_notes || []).length ? `<details style="margin-top:6px"><summary>Operational notes (${d.operational_notes.length})</summary><ul class="small">${d.operational_notes.map((n) => `<li>${nice(n)}</li>`).join("")}</ul></details>` : ""}
  ${d.benchmark ? `<p class="tiny muted" style="margin:6px 0 0">Benchmark: ${pct(d.benchmark.estimate, 0)} (${pct(d.benchmark.lcl, 0)}-${pct(d.benchmark.ucl, 0)}) - ${esc(d.benchmark.label)}</p>` : ""}
  <p class="tiny muted" style="margin:6px 0 0">${esc(src.citation || "")}</p></div>`;
}

/* ------------------------------------------------------------------ ANSWERABILITY */
const ST_ICON = { ok: "✓", caution: "!", fail: "✕", unknown: "?" };
function answerCard(av, opts = {}) {
  if (!av) return "";
  const cls = { ok: "ok", caution: "warn", fail: "bad" }[av.status] || "info";
  const order = ["Design fit", "Coverage", "Co-measurement", "Subsample", "Data structure", "Eligibility", "Measurement", "Precision", "Power", "Reporting", "Design", "Missing data"];
  const checks = [...av.checks].sort((a, b) => order.indexOf(a.dimension) - order.indexOf(b.dimension));
  const pr = opts.probe;
  return `<div class="card answer">
    <div class="row" style="justify-content:space-between"><h3 class="sub" style="margin:0">Can NHANES answer this?</h3>
      <span class="chip ${cls}" style="font-size:13px;font-weight:600">${esc(av.verdict)}</span></div>
    <div class="achecks">${checks.map((c) => `<div class="acheck ${c.status}"><span class="ai">${ST_ICON[c.status] || "·"}</span><div><b>${nice(c.title)}</b> <span class="tiny muted">${esc(c.dimension)}</span>
      <div class="small muted">${nice(c.message)}</div>${c.suggestion ? `<div class="small">→ ${nice(c.suggestion)}</div>` : ""}</div></div>`).join("")}</div>
    ${opts.probeButton ? `<div class="row" style="margin-top:12px"><button class="btn ${av.probed ? "" : "primary"} sm" data-act="probe">${av.probed ? "Re-run" : "Run"} blinded feasibility probe</button>
      <span class="tiny muted">Counts only, using real data. No effect estimates; the outcome rate is shown only as a 5-point band, so the protocol can't be tuned to results.</span></div>` : ""}
    ${pr ? `<details style="margin-top:10px" ${pr.stale ? "" : "open"}><summary>Probe results ${pr.stale ? "(stale: plan changed since probe)" : ""} · ${esc(pr.at?.slice(0, 16).replace("T", " ") || "")}${pr.synthetic ? " · synthetic data" : ""}</summary>
      <table class="t" style="margin-top:8px"><thead><tr><th>Cycle</th><th>Records</th><th>Positive weight</th><th>Eligible</th><th>Outcome measured</th>${S.project?.plan?.exposure ? "<th>Exposure measured</th>" : ""}<th>Analytic</th><th>Complete case</th></tr></thead>
      <tbody>${pr.per_cycle.map((c) => `<tr><td>${esc(c.cycle)}</td><td class="num">${c.n_records.toLocaleString()}</td><td class="num">${c.n_weighted.toLocaleString()}</td><td class="num">${c.n_population.toLocaleString()}</td><td class="num">${c.n_outcome.toLocaleString()}</td>${S.project?.plan?.exposure ? `<td class="num">${c.n_exposure?.toLocaleString() ?? ""}</td>` : ""}<td class="num">${c.n_analytic.toLocaleString()}</td><td class="num">${c.n_complete_case.toLocaleString()}</td></tr>`).join("")}</tbody></table>
      <p class="tiny muted">Weight: ${esc(pr.weight_variable)} · outcome ${pr.outcome.rate_band ? `rate band ${Math.round(pr.outcome.rate_band[0] * 100)}-${Math.round(pr.outcome.rate_band[1] * 100)}%` : pr.outcome.sd ? `SD ${pr.outcome.sd}` : ""} · ~${pr.n_parameters} model parameters · design df ${pr.design.analytic_df} · design effect ${av.metrics?.deff_assumed ?? 1.8} assumed</p></details>` : ""}
  </div>`;
}

/* ------------------------------------------------------------------ PROTOCOL */
const AGENT_COLOR = { Investigator: "#1F5A85", "Data Steward": "#2E7D4F", Epidemiologist: "#7A4FB0", Statistician: "#B5651D", Reviewer: "#B3261E", "Privacy Guard": "#5C6B7A" };
function avatar(name) {
  const base = name.replace(/ \(LLM\)/, ""); const c = AGENT_COLOR[base] || "#5C6B7A";
  const ini = base.split(" ").map((w) => w[0]).join("").slice(0, 2);
  return `<div class="avatar" style="background:${c}${name.includes("LLM") ? ";outline:2px dashed " + c + ";outline-offset:2px" : ""}">${ini}</div>`;
}
function editable(field, text, cls = "") {
  return `<span class="editable ${cls}" data-act="edittext" data-field="${field}" title="Click to edit">${nice(text)}</span>`;
}
function viewProtocol() {
  const p = S.project.plan; const f = p.feasibility; const k = S.meta.knowledge;
  const defs = Object.fromEntries(k.definitions.map((d) => [d.id, d]));
  const varCard = (role) => {
    const v = p[role]; if (!v) return "";
    const opts = [v.variable, ...(v.alternatives || [])].filter((x, i, a) => a.indexOf(x) === i);
    const d = defs[v.variable];
    const issues = (p.review || []).filter((i) => i.id === `opnotes_${v.variable}` || i.id === `verify_${v.variable}`);
    return `<div class="card"><div class="row" style="justify-content:space-between"><h3 class="sub" style="margin:0">${role === "outcome" ? "Outcome" : "Exposure"}</h3>
      ${role === "exposure" ? `<button class="btn sm ghost" data-act="swap">⇄ Swap exposure/outcome</button>` : ""}</div>
      <p style="margin:6px 0 8px;font:600 16px var(--serif)">${nice(v.concept_label)}</p>
      <label class="field">Definition / variable<select data-act="setdef" data-role="${role}">${opts.map((o) => `<option value="${o}" ${o === v.variable ? "selected" : ""}>${nice(defs[o] ? `${defs[o].short} - ${defs[o].label}` : o)}${defs[o] ? ` [${defs[o].status}]` : ""}</option>`).join("")}</select></label>
      ${d ? `<p class="small" style="margin:10px 0 4px">${nice(d.criteria_text)}</p><p class="tiny muted" style="margin:0">${esc(d.source.citation || "")} <span class="status ${esc(d.status)}">${esc(d.status)}</span></p>
        ${(d.operational_notes || []).length ? `<ul class="small" style="margin:8px 0 0;padding-left:18px">${d.operational_notes.map((n) => `<li>${nice(n)}</li>`).join("")}</ul>` : ""}` : `<p class="small muted">Building block (${esc(v.type)}${v.units ? ", " + esc(v.units) : ""})</p>`}
      ${role === "exposure" && v.type === "continuous" ? `<div class="row" style="margin-top:10px"><span class="small">Effect reported per</span><input type="number" step="any" value="${v.scale || 1}" style="width:90px" data-act="scale"><span class="small muted">${esc(v.units || "")}</span></div>` : ""}
      ${issues.map((i) => `<div class="row" style="margin-top:10px"><span class="sev ${i.severity}">${i.severity}</span><span class="small" style="flex:1">${nice(i.title)}</span>${i.fix ? `<button class="btn sm" data-act="fix" data-id="${i.id}">Acknowledge</button>` : `<span class="chip ok">acknowledged</span>`}</div>`).join("")}
    </div>`;
  };
  const pop = p.population.map((c) => `<div class="crit"><label class="toggle"><input type="checkbox" data-act="crit" data-id="${c.id}" ${c.enabled ? "checked" : ""}><span></span></label>
    <div class="lbl"><span class="chip ${c.kind === "exclusion" ? "warn" : "accent"}" style="font-size:11px">${c.kind}</span> ${nice(c.label)}<div class="tiny muted">${esc(c.source || "")} · <code>${esc(c.expr)}</code></div></div></div>`).join("");
  return `${p.privacy?.findings?.length ? `<div class="banner warn">Privacy guard redacted ${p.privacy.findings.length} identifier(s) from your question before processing.</div>` : ""}
  <div class="row" style="justify-content:space-between;align-items:flex-start;gap:20px">
    <div style="flex:1;min-width:280px"><div class="tiny muted" style="text-transform:uppercase;letter-spacing:.08em">${esc(p.study_type)} · cross-sectional · plan v${p.version}</div>
      <h1 class="page">${editable("title", p.title, "title-edit")}</h1>
      <p class="muted small" style="margin:0">Original idea: “${esc(p.question)}”</p></div>
    <div class="card gauge"><div class="ring" style="--p:${f.score}"><div>${f.score}</div></div><div><b>${esc(f.label)} feasibility</b><div class="tiny muted">in ${p.dataset.type === "nhanes" ? "NHANES" : "uploaded data"}</div>
      <details><summary class="tiny">components</summary><ul class="tiny" style="padding-left:16px;margin:4px 0">${f.components.map((c) => `<li>${esc(c.name)}: ${c.score}/${c.max}${c.note ? " - " + esc(c.note) : ""}</li>`).join("")}</ul></details></div></div>
  </div>
  <div class="card" style="margin-top:16px"><h3 class="sub" style="margin-top:0">Refined research question</h3>
    <p style="font:400 16.5px/1.55 var(--serif);margin:0">${editable("refined_question", p.refined_question)}</p>
    ${p.refined_question_llm ? `<div class="row" style="margin-top:8px"><span class="chip accent">AI phrasing</span><span class="small" style="flex:1">${nice(p.refined_question_llm)}</span><button class="btn sm" data-act="usellm" data-field="refined_question">Use</button></div>` : ""}
    <h3 class="sub">Hypothesis</h3><p style="margin:0">${editable("hypothesis", p.hypothesis)}</p>
    <h3 class="sub">PICO</h3><dl class="kv">${Object.entries(p.pico).map(([k2, v]) => `<dt>${esc(k2[0].toUpperCase() + k2.slice(1))}</dt><dd>${nice(v)}</dd>`).join("")}</dl>
  </div>
  <div style="margin-top:14px">${answerCard(p.answerability, { probeButton: true, probe: p.probe })}</div>
  <div class="grid ${p.exposure ? "g2" : ""}" style="margin-top:14px">${p.exposure ? varCard("exposure") : ""}${varCard("outcome")}</div>
  <div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Study population</h3>${pop}
    <details style="margin-top:10px"><summary>Add a criterion</summary><div class="grid g4" style="margin-top:8px;align-items:end">
      <label class="field">Label<input type="text" id="critLabel" placeholder="e.g. Age 20-79 years"></label>
      <label class="field" style="grid-column:span 2">Expression<input type="text" id="critExpr" placeholder="age >= 20 & age < 80"></label>
      <label class="field">Type<select id="critKind"><option>inclusion</option><option>exclusion</option></select></label></div>
      <button class="btn sm" style="margin-top:8px" data-act="addcrit">Validate & add</button></details></div>
  <h2 class="sec">Agent roundtable</h2>
  <div class="card dialog">${(p.agent_dialogue || []).map((d) => `<div class="msg">${avatar(d.agent)}<div><div class="who">${esc(d.agent)}<small>${d.source === "llm" ? "LLM" : "rules"}</small></div><div class="txt">${nice(d.message)}</div></div></div>`).join("")}</div>
  <div class="row" style="margin-top:20px"><button class="btn primary" data-act="go" data-stage="map">Review data mapping →</button></div>`;
}

/* ------------------------------------------------------------------ MAP */
function viewMap() {
  const p = S.project.plan; const cycles = p.dataset.cycles || [];
  const kindChip = (r) => r.status === "ai-proposed" ? `<span class="status ai-proposed">AI-proposed</span>` :
    r.kind === "definition" ? `<span class="chip accent">guideline definition</span>` : r.direct ? `<span class="chip ok">direct ${p.dataset.type === "nhanes" ? "NHANES" : "column"}</span>` : `<span class="chip info">derived</span>`;
  const rows = (p.variable_map || []).map((r) => `<tr><td><b>${nice(r.label)}</b><div class="tiny muted"><code>${esc(r.variable)}</code></div></td><td>${esc(r.role)}</td><td>${kindChip(r)}</td>
    <td>${r.raw_variables.map((v) => `<code>${esc(v)}</code>`).join(" ")}</td>
    <td class="tiny">${cycles.map((c) => (r.files[c] || []).join(", ")).join("<br>")}</td>
    <td>${cycles.map((c) => `<span class="chip ${r.available[c] ? "ok" : "bad"}" style="font-size:10.5px">${c} ${r.available[c] ? "✓" : "✗"}</span>`).join(" ")}</td>
    <td><details><summary class="tiny">expr</summary><code class="tiny">${esc(r.expr)}</code></details></td></tr>`).join("");
  const generic = p.dataset.type === "generic" ? `<div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Map building blocks to “${esc(p.dataset.name)}”</h3>
    <p class="small muted" style="margin-top:0">Detected design: weight ${esc(p.dataset.weight || "none")}, strata ${esc(p.dataset.strata || "none")}, PSU ${esc(p.dataset.psu || "none")}. Confirm each mapping; binary blocks must evaluate to 1 = yes.</p>
    <table class="t"><thead><tr><th>Building block</th><th>Candidates (confidence)</th><th>Expression over your columns</th><th></th></tr></thead><tbody>${Object.entries(p.generic_status || {}).map(([b, st]) =>
      `<tr><td><b>${esc(st.label)}</b><div class="tiny muted">${esc(b)} · ${esc(st.type)}</div></td><td class="tiny">${st.candidates.map((c) => `${esc(c.variable)} (${c.confidence})`).join("<br>") || "none"}</td>
      <td><input type="text" id="gm_${b}" value="${esc((p.generic_mapping || {})[b] || "")}" style="width:100%"><div class="tiny muted">${esc(st.note || "")}</div></td>
      <td><button class="btn sm" data-act="gmap" data-block="${b}">Save</button></td></tr>`).join("")}</tbody></table></div>` : "";
  const custom = (p.custom_variables || []).filter((c) => c.source === "ai");
  return `<h1 class="page">Concept → variable map</h1><p class="lede">Every analysis variable traced to the raw ${p.dataset.type === "nhanes" ? "NHANES files and variable names" : "dataset columns"} it needs, with availability per survey cycle. Guideline definitions and derived variables show the exact expression that will run.</p>
  <div class="card"><div class="tablewrap"><table class="t"><thead><tr><th>Variable</th><th>Role</th><th>Source</th><th>Raw variables</th><th>Files</th><th>Availability</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>
  ${generic}
  ${custom.length ? `<div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">AI-proposed variables awaiting approval</h3>${custom.map((c) => `<div class="crit"><div class="lbl"><b>${esc(c.label)}</b> <code>${esc(c.name)} = ${esc(c.expr)}</code></div><button class="btn sm" data-act="fix" data-id="custom_${c.name}">Approve</button></div>`).join("")}</div>` : ""}
  <div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Data dictionary explorer</h3>
    <div class="row"><input type="text" id="dictQ" placeholder="Search the ${p.dataset.type === "nhanes" ? "NHANES" : "dataset"} dictionary (e.g. transferrin, liver stiffness, insulin)" style="flex:1"><button class="btn" data-act="dict">Search</button></div>
    ${S.dict ? `<table class="t" style="margin-top:10px"><thead><tr><th>Variable</th><th>Label</th><th>File</th><th>Cycles</th><th>Match</th></tr></thead><tbody>${S.dict.map((h) => `<tr><td><code>${esc(h.variable)}</code></td><td>${esc(h.label)}</td><td>${esc(h.table)}</td><td>${esc((h.cycles || []).join(", "))}</td><td><div style="width:80px;height:6px;background:var(--line-2);border-radius:3px"><div style="width:${h.confidence * 100}%;height:6px;background:var(--accent);border-radius:3px"></div></div><span class="tiny muted">${h.confidence}</span></td></tr>`).join("")}</tbody></table>` : ""}
  </div>
  <div class="row" style="margin-top:20px"><button class="btn" data-act="go" data-stage="protocol">← Protocol</button><button class="btn primary" data-act="go" data-stage="plan">Analysis plan →</button></div>`;
}

/* ------------------------------------------------------------------ PLAN */
function pills(field, items, options) {
  const k = S.meta.knowledge; const lab = (n) => (k.blocks.find((b) => b.name === n)?.label) || (k.definitions.find((d) => d.id === n)?.short) || n;
  return `<div class="pill-list">${items.map((n) => `<span class="pill">${nice(lab(n))}<button data-act="rmpill" data-field="${field}" data-v="${n}" title="Remove">×</button></span>`).join("")}
    <span class="pill add"><select data-act="addpill" data-field="${field}"><option value="">+ add</option>${options.filter((o) => !items.includes(o.name)).map((o) => `<option value="${o.name}">${nice(o.label)}</option>`).join("")}</select></span></div>`;
}
function viewPlan() {
  const p = S.project.plan; const k = S.meta.knowledge;
  const blockOpts = k.blocks.filter((b) => b.type !== "continuous" || true).map((b) => ({ name: b.name, label: b.label }));
  const catOpts = k.blocks.filter((b) => b.type !== "continuous").map((b) => ({ name: b.name, label: b.label }));
  const issues = p.review || [];
  const blockers = issues.filter((i) => i.severity === "blocker");
  const pendingAck = issues.filter((i) => i.severity === "major" && i.fix && i.fix.op === "acknowledge");
  const canApprove = !blockers.length && !pendingAck.length;
  const sens = p.sensitivity.map((s) => `<div class="crit"><label class="toggle"><input type="checkbox" data-act="sens" data-id="${s.id}" ${s.enabled ? "checked" : ""}><span></span></label><div class="lbl">${nice(s.label)}<div class="tiny muted">${esc(s.type)}${s.expr ? ` · <code>${esc(s.expr)}</code>` : ""}${s.outcome ? ` · outcome <code>${esc(s.outcome)}</code>` : ""}${s.family ? ` · ${esc(s.family)}` : ""}</div></div></div>`).join("");
  const cyc = Object.entries(k.cycles).map(([id, c]) => `<button class="${(p.dataset.cycles || []).includes(id) ? "on" : ""}" data-act="plancycle" data-id="${id}">${esc(id)}</button>`).join("");
  const src = [["auto", "CDC/local"], ["local", "Local"], ["synthetic", "Synthetic"]].map(([v, l]) => `<button class="${p.dataset.source === v ? "on" : ""}" data-act="plansource" data-v="${v}">${l}</button>`).join("");
  const approved = S.project.approved_current;
  return `<h1 class="page">Statistical analysis plan</h1><p class="lede">Drafted by the Statistician and Epidemiologist agents and critiqued by the Reviewer. Edit anything; every change is versioned. Approval locks this exact plan (by hash) for execution.</p>
  <div class="grid g2">
    <div class="card"><h3 class="sub" style="margin-top:0">Estimand & model</h3>
      <label class="field">Model family<select data-act="family">${[["quasipoisson", "Survey quasi-Poisson (prevalence ratio)"], ["quasibinomial", "Survey logistic (odds ratio)"], ["gaussian", "Survey linear (mean difference)"]].map(([v, l]) => `<option value="${v}" ${p.model.family === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <p class="small" style="margin:10px 0 0">${nice(p.rationale.statistician)}</p>
      ${p.rationale.statistician_llm ? `<p class="small" style="margin:8px 0 0"><span class="chip accent">LLM</span> ${nice(p.rationale.statistician_llm)}</p>` : ""}
      <h3 class="sub">Adjustment sets</h3><ol class="small" style="margin:0;padding-left:18px">${p.adjustment_sets.map((a) => `<li><b>${esc(a.label)}</b>: ${a.covariates.length ? esc(a.covariates.join(", ")) : "none"}</li>`).join("") || "<li>Descriptive only</li>"}</ol>
      <h3 class="sub">Missing data</h3><p class="small" style="margin:0">${esc(p.missing_data.rationale)}</p>
    </div>
    <div class="card"><h3 class="sub" style="margin-top:0">Variables</h3>
      <p class="small" style="margin:0 0 6px"><b>Covariates</b> <span class="muted">${esc(p.rationale.epidemiologist).slice(0, 220)}…</span></p>${pills("covariates", p.covariates, blockOpts)}
      ${Object.entries(p.covariate_notes || {}).map(([c, n]) => `<p class="tiny muted" style="margin:6px 0 0"><b>${esc(c)}</b>: ${nice(n)}</p>`).join("")}
      <p class="small" style="margin:14px 0 6px"><b>Subgroups</b></p>${pills("subgroups", p.subgroups, catOpts)}
      ${p.study_type === "association" ? `<p class="small" style="margin:14px 0 6px"><b>Effect modifiers (interaction tests)</b></p>${pills("interactions", p.interactions, catOpts)}` : ""}
      <h3 class="sub">Data</h3><div class="row"><span class="small muted">Cycles</span><div class="seg">${cyc}</div><span class="small muted">Source</span><div class="seg">${src}</div></div>
      ${p.benchmarks?.length ? `<h3 class="sub">Benchmark against published literature</h3>${p.benchmarks.map((b) => `<p class="small" style="margin:0 0 4px">${esc(b.label)}: <b>${pct(b.estimate, 0)}</b> (${pct(b.lcl, 0)}-${pct(b.ucl, 0)}), n=${(b.n || 0).toLocaleString()}</p>`).join("")}` : ""}
    </div>
  </div>
  <div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Prespecified sensitivity analyses</h3>${sens}
    <details style="margin-top:8px"><summary>Add an exclusion sensitivity analysis</summary><div class="grid g3" style="margin-top:8px;align-items:end"><label class="field">Label<input type="text" id="sLabel" placeholder="Exclude current smokers"></label><label class="field">Exclude if<input type="text" id="sExpr" placeholder='smoking == "Current"'></label><button class="btn sm" data-act="addsens">Validate & add</button></div></details></div>
  <h2 class="sec">Reviewer critique</h2>
  <div class="card">${issues.length ? issues.map((i) => `<div class="issue"><span class="sev ${i.severity}">${i.severity}</span><div><b class="small">${nice(i.title)}</b> <span class="tiny muted">${esc(i.agent)}</span><div class="small muted">${nice(i.detail)}</div></div>
    <div>${i.fix ? `<button class="btn sm" data-act="fix" data-id="${i.id}">${i.fix.op === "acknowledge" ? "Acknowledge" : "Apply fix"}</button>` : ""}</div></div>`).join("") : `<p class="muted small">No issues.</p>`}</div>
  <h2 class="sec">Investigator approval</h2>
  <div class="card">${approved ? `<div class="banner ok" style="margin:0 0 12px">Approved: plan v${p.version} (sha256 ${esc(S.project.plan_hash.slice(0, 12))}) by ${esc(p.approvals[p.approvals.length - 1].by)}.</div>
      <button class="btn primary" data-act="run">Run analysis in R →</button>` :
    `${blockers.length ? `<div class="banner bad">Resolve ${blockers.length} blocker(s) before approval.</div>` : ""}${pendingAck.length ? `<div class="banner warn">Acknowledge ${pendingAck.length} operational assumption(s) (see critique).</div>` : ""}
    <div class="row"><input type="text" id="approver" placeholder="Your name" value="${esc(store.get("q2e.name", ""))}"><label class="row small"><input type="checkbox" id="attest"> I reviewed the protocol, variable mappings, definitions and this analysis plan.</label>
    <button class="btn primary" data-act="approve" ${canApprove ? "" : "disabled"}>Approve protocol</button></div>`}</div>`;
}

/* ------------------------------------------------------------------ RUN */
function startPolling() {
  clearInterval(S.poll);
  S.poll = setInterval(async () => {
    const lr = latestRun(); if (!lr) return;
    S.run = await api(`/api/projects/${S.project.id}/runs/${lr.id}`);
    const con = $("#console"); if (con) { con.textContent = S.run.log.join("\n"); con.scrollTop = con.scrollHeight; }
    if (S.run.status !== "running") { clearInterval(S.poll); S.project = await api(`/api/projects/${S.project.id}`); S.results = null; render(); }
  }, 1200);
}
function viewRun() {
  const lr = latestRun(); const r = S.run;
  if (!lr) return `<h1 class="page">Run & validate</h1><div class="empty">Approve the plan, then run it.<br><br><button class="btn primary" data-act="run" ${S.project.approved_current ? "" : "disabled"}>Run analysis</button></div>`;
  const stale = lr.plan_hash !== S.project.plan_hash;
  let body = "";
  if (r.status === "running") body = `<div class="card"><p><span class="spinner"></span> Executing approved plan in the R engine (survey package)…</p><div class="console" id="console">${esc(r.log.join("\n"))}</div></div>`;
  else if (r.status === "failed") body = `<div class="banner bad"><b>Run failed:</b> ${esc(r.error)}</div>${/not found|download/i.test(r.error || "") ? `<div class="banner info">NHANES files were not available. Place the .xpt files in <code>${esc(S.meta.data.local_dir)}</code>, enable CDC downloads, or switch the data source to <b>Synthetic</b> in the analysis plan for an offline demo.</div>` : ""}<div class="console">${esc(r.log.join("\n"))}</div>`;
  else if (S.results) {
    const R = S.results; const c = R.checks; const cnt = (s) => c.filter((x) => x.status === s).length;
    body = `${R.meta.synthetic ? `<div class="banner warn">Synthetic NHANES-like data - pipeline demonstration only; estimates are not population estimates.</div>` : ""}
    <div class="row" style="margin-bottom:12px"><span class="chip ok">${cnt("pass")} pass</span><span class="chip warn">${cnt("warn")} warn</span><span class="chip bad">${cnt("fail")} fail</span><span class="chip info">${cnt("info")} info</span><span class="small muted">${R.meta.seconds}s · ${esc(R.meta.r_version)}</span></div>
    <div class="checks">${c.map((x) => `<div class="check ${x.status}"><span class="tiny muted">${esc(x.category)} · ${x.status.toUpperCase()}</span><b>${nice(x.title)}</b><p>${nice(x.message)}</p></div>`).join("")}</div>
    <div class="grid g2" style="margin-top:18px"><div class="card"><h3 class="sub" style="margin-top:0">Participant flow</h3><div class="flow">${R.flow.map((f, i) => `${i ? `<div class="arrow">${f.excluded ? `<span>− ${f.excluded.toLocaleString()} ${esc(f.kind === "exclusion" ? "excluded" : "not eligible")}</span>` : ""}</div>` : ""}<div class="box"><b>${f.n.toLocaleString()}</b> <span class="small">${nice(f.label)}</span></div>`).join("")}</div></div>
      <div class="card"><h3 class="sub" style="margin-top:0">Survey design</h3><dl class="kv"><dt>Weight</dt><dd><code>${esc(R.design.weight_variable)}</code> (${esc(R.design.weight_level)})</dd><dt>Cycles</dt><dd>${esc(R.design.cycles.join(", "))}</dd><dt>Strata / PSUs</dt><dd>${R.design.n_strata} / ${R.design.n_psu} (design df ${R.design.design_df})</dd><dt>Analytic df</dt><dd>${R.design.analytic_df}</dd><dt>Represents</dt><dd>${fx(R.design.sum_weights_millions, 1)} million people</dd><dt>Variance</dt><dd>Taylor linearization; lonely PSU: ${esc(R.design.lonely_psu)}</dd></dl>
      <h3 class="sub">Source files</h3><ul class="tiny" style="padding-left:16px;margin:0">${R.meta.files.map((f) => `<li>${esc(f.file)} · ${esc(f.origin)} · n=${f.nrow.toLocaleString()} · md5 <span class="hash">${esc(f.md5.slice(0, 12))}</span></li>`).join("")}</ul></div></div>
    <details class="card" style="margin-top:14px"><summary>Derivation audit (${R.derivation_audit.length} variables)</summary><table class="t" style="margin-top:8px"><thead><tr><th>Variable</th><th>Expression</th><th>Non-missing</th><th>Positive / distribution</th></tr></thead><tbody>${R.derivation_audit.map((a) => `<tr><td><code>${esc(a.name)}</code></td><td><code class="tiny">${esc(a.expr)}</code></td><td class="num">${a.n_nonmissing.toLocaleString()}</td><td class="tiny">${a.n_positive != null ? a.n_positive.toLocaleString() + " positive" : a.quantiles ? "min/Q1/med/Q3/max: " + a.quantiles.join(" / ") : a.levels ? Object.entries(a.levels).map(([k2, v]) => `${esc(k2)}: ${v}`).join("; ") : ""}</td></tr>`).join("")}</tbody></table></details>
    <details class="card" style="margin-top:10px"><summary>Engine log & executed calls</summary><div class="console" style="margin-top:8px">${esc(R.log.join("\n"))}\n\n${esc(R.trace.join("\n"))}</div></details>
    <div class="row" style="margin-top:18px"><button class="btn primary" data-act="go" data-stage="results">View results →</button></div>`;
  }
  return `<h1 class="page">Run & validate</h1><p class="lede">The approved plan is compiled into an executable specification and run by the R engine. ${"Every"} result is checked by automated QC before you see it.</p>
  ${stale ? `<div class="banner warn">The plan has changed since this run (run plan ${esc(lr.plan_hash.slice(0, 10))}). Re-approve and re-run to update results. ${S.project.approved_current ? `<button class="btn sm" data-act="run">Re-run now</button>` : ""}</div>` : ""}${body}`;
}

/* ------------------------------------------------------------------ RESULTS */
function headline() {
  const R = S.results; const pe = R.primary_estimate || {}; const p = S.project.plan;
  if (pe.effect === "prevalence") return `<div class="headline"><div class="big">${pct(pe.est)}</div><div><b>${nice(pe.label)}</b><div class="ci">95% CI ${pct(pe.lcl)}-${pct(pe.ucl)} · n = ${pe.n?.toLocaleString()}${pe.pop_millions ? ` · ≈${fx(pe.pop_millions, 1)} million people` : ""}</div></div></div>`;
  const nm = { PR: "Prevalence ratio", OR: "Odds ratio", Beta: "Mean difference" }[pe.effect] || pe.effect;
  return `<div class="headline"><div class="big">${fx(pe.est)}</div><div><b>${esc(nm)} · ${nice(pe.label)}</b> → ${nice(p.outcome.label)}<div class="ci">95% CI ${fx(pe.lcl)} to ${fx(pe.ucl)} · P ${pfmt(pe.p)} · n = ${pe.n?.toLocaleString()} · fully adjusted</div>${R.evalue ? `<div class="tiny muted">E-value ${fx(R.evalue.point)} (CI ${fx(R.evalue.ci)})</div>` : ""}</div></div>`;
}
function benchCards() {
  return (S.results.benchmarks || []).map((b) => {
    const mx = Math.max(b.published_ucl, b.replicated_ucl) * 1.25; const pos = (x) => (100 * x / mx).toFixed(1) + "%";
    return `<div class="card bench"><div class="row" style="justify-content:space-between"><b class="small">${nice(b.outcome_label)}</b><span class="chip ${b.overlap ? "ok" : "warn"}">${b.overlap ? "consistent with literature" : "differs from literature"}</span></div>
      <div class="small">Published <b>${pct(b.published)}</b> (${pct(b.published_lcl)}-${pct(b.published_ucl)}) · ${esc(b.label)}</div>
      <div class="bar"><i class="pub" style="left:${pos(b.published_lcl)};width:calc(${pos(b.published_ucl)} - ${pos(b.published_lcl)})"></i><em style="left:${pos(b.published)}"></em></div>
      <div class="small">Q2E <b>${pct(b.replicated)}</b> (${pct(b.replicated_lcl)}-${pct(b.replicated_ucl)}) · n=${b.replicated_n.toLocaleString()}</div>
      <div class="bar"><i class="rep" style="left:${pos(b.replicated_lcl)};width:calc(${pos(b.replicated_ucl)} - ${pos(b.replicated_lcl)})"></i><em style="left:${pos(b.replicated)}"></em></div></div>`;
  }).join("");
}
function table1() {
  const t = S.results.table1; if (!t) return "";
  return `<div class="tablewrap"><table class="t"><thead><tr><th>Characteristic</th>${t.columns.map((c) => `<th>${esc(c.label)}<div class="tiny muted">n=${c.n.toLocaleString()}</div></th>`).join("")}<th>P</th></tr></thead><tbody>${t.rows.map((r) =>
    r.header && r.type === "categorical" ? `<tr class="grp"><td>${nice(r.label)}</td>${t.columns.map(() => "<td></td>").join("")}<td class="num">${esc(r.p_text)}</td></tr>` :
      `<tr class="${r.header ? "" : "lvl"}"><td>${nice(r.label)}</td>${t.columns.map((c) => `<td class="num">${esc(r.values[c.key]?.text || "")}</td>`).join("")}<td class="num">${esc(r.p_text || "")}</td></tr>`).join("")}</tbody></table></div><p class="tiny muted">${esc(t.note)}</p>`;
}
function viewResults() {
  const R = S.results; const p = S.project.plan; const lr = latestRun(); const sm = S.summary || {};
  if (!R) return `<div class="empty">No results yet.</div>`;
  const base = `/api/projects/${S.project.id}/runs/${lr.id}`;
  const prevRows = R.prevalence.map((x) => `<tr><td>${nice(x.outcome_label)}${x.outcome_level ? " - " + esc(x.outcome_level) : ""}</td><td>${esc(x.group_var === "Overall" ? "" : x.group_label)}</td><td>${esc(x.group)}</td><td class="num">${x.n.toLocaleString()}</td><td class="num">${pct(x.est)} (${pct(x.lcl)}-${pct(x.ucl)})</td><td class="num">${x.pop_millions ?? ""}</td><td>${x.nchs === "meets standard" ? `<span class="chip ok" style="font-size:10.5px">ok</span>` : `<span class="chip warn" style="font-size:10.5px" title="${esc(x.nchs)}">flag</span>`}</td></tr>`).join("");
  const mrows = R.models.flatMap((m) => m.terms.filter((t) => t.term !== "(Intercept)" && (p.study_type !== "association" || t.variable === R.primary_estimate?.term)).map((t) => `<tr><td>${esc(m.label)}</td><td>${nice(t.label)}</td><td class="num">${m.n.toLocaleString()}</td><td class="num">${fx(t.est)} (${fx(t.lcl)} to ${fx(t.ucl)})</td><td class="num">${pfmt(t.p)}</td></tr>`)).join("");
  const srows = R.sensitivity.map((s) => `<tr><td>${nice(s.label)}</td><td class="num">${s.n?.toLocaleString() ?? ""}</td><td class="num">${s.error ? `<span style="color:var(--bad)">${esc(s.error)}</span>` : s.effect === "prevalence" ? `${pct(s.est)} (${pct(s.lcl)}-${pct(s.ucl)})` : `${esc(s.effect)} ${fx(s.est)} (${fx(s.lcl)} to ${fx(s.ucl)})`}</td><td class="tiny">${esc(s.note || "")}</td></tr>`).join("");
  return `${R.meta.synthetic ? `<div class="banner warn">Synthetic demonstration data - illustrative estimates only.</div>` : ""}
  <h1 class="page">Results</h1><p class="lede">${nice(p.refined_question)}</p>
  <div class="card">${headline()}</div>
  ${benchCards() ? `<h2 class="sec">Replication check against published literature</h2><div class="grid g2">${benchCards()}</div>` : ""}
  <div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Plain-language summary</h3><p style="margin:0 0 10px">${nice(sm.plain_language || "")}</p>
    <div class="row"><button class="btn sm" data-act="listen">🔊 Listen${S.meta.voice ? " (ElevenLabs)" : ""}</button><span class="tiny muted">Key point: ${nice(sm.key_points?.findings || "")}</span></div><audio id="audio" controls style="display:none;margin-top:8px;width:100%"></audio></div>
  <h2 class="sec">Figures</h2><div class="grid g2">${R.figures.map((f, i) => `<figure class="fig"><img src="${base}/files/${f.file}" alt="${esc(f.title)}" loading="lazy"><figcaption><b>Figure ${i + 1}.</b> ${nice(f.title)}</figcaption></figure>`).join("")}</div>
  <h2 class="sec">Table 1. Characteristics${R.table1?.by_label ? " by " + nice(R.table1.by_label) : ""}</h2>${table1()}
  ${prevRows ? `<h2 class="sec">Table 2. Weighted prevalence</h2><div class="tablewrap"><table class="t"><thead><tr><th>Outcome</th><th>Subgroup</th><th>Level</th><th>n</th><th>Weighted % (95% CI)</th><th>Millions</th><th>NCHS</th></tr></thead><tbody>${prevRows}</tbody></table></div>` : ""}
  ${mrows ? `<h2 class="sec">Table 3. Regression (${esc(R.models[0].effect_label)})</h2><div class="tablewrap"><table class="t"><thead><tr><th>Model</th><th>Term</th><th>n</th><th>Estimate (95% CI)</th><th>P</th></tr></thead><tbody>${mrows}</tbody></table></div>` : ""}
  ${R.interactions.length ? `<h2 class="sec">Effect modification</h2><div class="card">${R.interactions.map((it) => `<p class="small" style="margin:0 0 6px"><b>${esc(it.label)}</b> · P<sub>interaction</sub> ${pfmt(it.p_interaction)} · ${it.strata.map((s) => `${esc(s.level)}: ${fx(s.est)} (${fx(s.lcl)} to ${fx(s.ucl)})`).join(" · ")}</p>`).join("")}</div>` : ""}
  <h2 class="sec">Sensitivity analyses</h2><div class="tablewrap"><table class="t"><thead><tr><th>Analysis</th><th>n</th><th>Estimate</th><th>Note</th></tr></thead><tbody>${srows}</tbody></table></div>
  <h2 class="sec">Prior literature</h2><div class="card">${S.lit ? (S.lit.error ? `<p class="small" style="color:var(--bad)">${esc(S.lit.error)}</p>` : S.lit.results.map((r) => `<p class="small" style="margin:0 0 6px"><a href="${r.url}" target="_blank" rel="noopener">${esc(r.title)}</a> <span class="muted">${esc(r.first_author)} · ${esc(r.journal)} · ${esc(r.pubdate)}</span></p>`).join("") || `<p class="muted small">No matches.</p>`) + `<p class="tiny muted">Query: <code>${esc(S.lit.query)}</code></p>` : `<button class="btn sm" data-act="lit">Search PubMed for related NHANES studies</button>`}</div>
  <h2 class="sec">Outputs</h2><div class="card row">
    <a class="btn primary" href="${base}/report.html" target="_blank">Manuscript (JAMA Netw Open style)</a>
    ${S.meta.llm.enabled ? `<a class="btn" href="${base}/report.html?llm=true" target="_blank">Manuscript + AI narrative</a>` : ""}
    <a class="btn" href="${base}/report.md" target="_blank">Markdown</a>
    <a class="btn" href="${base}/bundle.zip">Reproducibility bundle (.zip)</a>
    <a class="btn ghost" href="/api/projects/${S.project.id}/compiled" target="_blank">Compiled plan JSON</a></div>
  <div class="row" style="margin-top:20px"><button class="btn primary" data-act="go" data-stage="signoff">Investigator sign-off →</button></div>`;
}

/* ------------------------------------------------------------------ SIGN-OFF */
const ATTEST = ["The research question, population and outcome reflect my scientific intent.",
  "I verified guideline definitions and accepted each operational assumption.",
  "I checked the concept-to-variable mapping against the dataset documentation.",
  "I reviewed all QC warnings and failures and documented overrides.",
  "Interpretation is associational and limitations are stated; results are suitable for the intended use."];
function viewSignoff() {
  const pj = S.project; const R = S.results; const lr = latestRun();
  if (pj.signoff) {
    const so = pj.signoff;
    return `<h1 class="page">Signed off</h1><div class="cert"><h3>${esc(pj.plan.title)}</h3><p class="small">Signed by <b>${esc(so.by)}</b> on ${esc(so.at.replace("T", " "))}${so.synthetic ? ` · <span class="chip warn">synthetic data</span>` : ""}</p>
      <dl class="kv"><dt>Plan hash</dt><dd class="hash">${esc(so.plan_hash)}</dd><dt>Results hash</dt><dd class="hash">${esc(so.results_sha256)}</dd><dt>Run</dt><dd>${esc(so.run_id)}</dd><dt>Provenance</dt><dd>${pj.chain.valid ? `✓ ${pj.chain.events} events, chain intact` : "✗ chain broken"} <span class="hash">${esc(pj.chain.head || "")}</span></dd>
      ${Object.keys(so.overrides || {}).length ? `<dt>Overrides</dt><dd>${Object.entries(so.overrides).map(([k2, v]) => `<b>${esc(k2)}</b>: ${esc(v)}`).join("<br>")}</dd>` : ""}</dl></div>
      ${provTable()}`;
  }
  const fails = (R?.checks || []).filter((c) => c.status === "fail");
  return `<h1 class="page">Investigator sign-off</h1><p class="lede">AI drafted and executed; you decide. Sign-off binds your name to this exact plan hash and results hash in the provenance ledger.</p>
  <div class="grid g2"><div class="card"><h3 class="sub" style="margin-top:0">Attestations</h3>${ATTEST.map((a, i) => `<label class="row small" style="align-items:flex-start;margin-bottom:8px"><input type="checkbox" class="att" data-i="${i}"> ${esc(a)}</label>`).join("")}
    ${fails.map((c) => `<label class="field" style="margin-top:8px">Override reason for failed check: ${esc(c.title)}<textarea class="ovr" data-id="${esc(c.id)}" rows="2"></textarea></label>`).join("")}
    <div class="row" style="margin-top:12px"><input type="text" id="signer" placeholder="Your name" value="${esc(store.get("q2e.name", ""))}"><button class="btn primary" data-act="sign">Sign off results</button></div></div>
  <div class="card"><h3 class="sub" style="margin-top:0">What stays under human supervision</h3><ul class="small" style="padding-left:18px;margin:0">
    <li><b>Question framing</b> - the AI proposes; the investigator decides what is clinically meaningful.</li>
    <li><b>Case definitions</b> - guideline thresholds and every operational assumption require explicit acknowledgement; AI-proposed definitions cannot run until approved.</li>
    <li><b>Confounder selection</b> - agents flag mediators and definitional overlap; causal structure is the investigator's call.</li>
    <li><b>Approval gate</b> - nothing executes without approval of the exact plan hash; any edit invalidates approval.</li>
    <li><b>QC failures</b> - cannot be silently ignored; each needs a documented override.</li>
    <li><b>Interpretation & publication</b> - narrative is drafted from aggregate results only, filtered for causal language, and signed by a human.</li>
    <li><b>Data governance</b> - restricted data use only approved/local models; row-level data never reach an LLM.</li></ul></div></div>
  ${provTable()}`;
}
function provTable() {
  const ev = S.project.events;
  return `<h2 class="sec">Provenance ledger</h2><div class="tablewrap"><table class="t"><thead><tr><th>#</th><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Plan</th><th>Hash</th></tr></thead><tbody>${ev.slice().reverse().map((e) => `<tr><td class="num">${e.seq}</td><td class="num">${esc(e.at.replace("T", " ").slice(0, 19))}</td><td>${esc(e.actor)}</td><td>${esc(e.action.replace(/_/g, " "))}<div class="tiny muted">${esc(JSON.stringify(e.detail).slice(0, 140))}</div></td><td class="hash">${esc(e.plan_hash.slice(0, 10))}</td><td class="hash">${esc(e.hash.slice(0, 10))}</td></tr>`).join("")}</tbody></table></div>`;
}

/* ------------------------------------------------------------------ actions */
async function edit(fix, note) {
  try { S.project = await api(`/api/projects/${S.project.id}/edit`, { method: "POST", body: { fix, actor: store.get("q2e.name", "") || "investigator", note } }); rerender(); }
  catch (e) { toast(e.message, true); }
}
const A = {
  home: () => (location.hash = "#/"),
  go: (el) => el.dataset.stage && go(el.dataset.stage),
  example: (el) => { $("#q").value = el.dataset.q; store.set("q2e.q", el.dataset.q); },
  cycle: (el) => { const c = S.ask.cycles; const id = el.dataset.id; S.ask.cycles = c.includes(id) ? c.filter((x) => x !== id) : [...c, id]; if (!S.ask.cycles.length) S.ask.cycles = [id]; rerender(); },
  source: (el) => { S.ask.source = el.dataset.v; rerender(); },
  assess: async (el) => {
    const q = $("#q").value.trim(); if (q.length < 4) return toast("Describe your research idea first", true);
    el.disabled = true; el.innerHTML = `<span class="spinner"></span> Checking…`;
    try { S.assess = await api("/api/assess", { method: "POST", body: { question: q, cycles: S.ask.cycles } }); } catch (e) { toast(e.message, true); }
    rerender();
  },
  probe: async (el) => {
    el.disabled = true; el.innerHTML = `<span class="spinner"></span> Probing data (counts only)…`;
    try { S.project = await api(`/api/projects/${S.project.id}/probe?actor=${encodeURIComponent(store.get("q2e.name", "investigator"))}`, { method: "POST" }); toast("Feasibility probe complete"); }
    catch (e) { toast(e.message, true); }
    rerender();
  },
  design: async (el) => {
    const q = $("#q").value.trim(); if (q.length < 8) return toast("Describe your research idea first", true);
    store.set("q2e.q", q); el.disabled = true; el.innerHTML = `<span class="spinner"></span> Agents designing your study…`;
    try {
      const pj = await api("/api/projects", { method: "POST", body: { question: q, cycles: S.ask.cycles, source: S.ask.source, provider: $("#provSel").value || null, dataset_id: $("#dsSel").value || null, actor: store.get("q2e.name", "") || "investigator" } });
      S.project = pj; location.hash = `#/p/${pj.id}/protocol`;
    } catch (e) {
      toast(e.message, true); el.disabled = false; el.textContent = "Design my study →";
      try { S.assess = await api("/api/assess", { method: "POST", body: { question: q, cycles: S.ask.cycles } }); rerender(); } catch {}
    }
  },
  upload: async () => {
    const f = $("#dsData").files[0]; if (!f) return toast("Choose a CSV data file", true);
    const fd = new FormData(); fd.append("name", $("#dsName").value || f.name); fd.append("data", f); if ($("#dsDict").files[0]) fd.append("dictionary", $("#dsDict").files[0]);
    try { const d = await api("/api/datasets", { method: "POST", body: fd }); S.meta.datasets.push({ id: d.id, name: d.name }); S.ask.dataset = d.id; toast(`Dataset registered: ${d.n_columns} columns; design ${JSON.stringify(d.design)}`); rerender(); } catch (e) { toast(e.message, true); }
  },
  mic: async (el) => {
    if (S.meta.voice && navigator.mediaDevices) {
      if (S.rec) { S.rec.stop(); return; }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); const chunks = []; const rec = new MediaRecorder(stream); S.rec = rec;
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => { S.rec = null; stream.getTracks().forEach((t) => t.stop()); el.textContent = "🎙 Dictate"; const fd = new FormData(); fd.append("audio", new Blob(chunks, { type: "audio/webm" }), "idea.webm");
        try { const r = await api("/api/voice/stt", { method: "POST", body: fd }); $("#q").value = r.text; } catch (e) { toast(e.message, true); } };
      rec.start(); el.textContent = "⏹ Stop"; return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return toast("Speech input not available in this browser", true);
    const r = new SR(); r.lang = "en-US"; r.onresult = (e) => ($("#q").value = e.results[0][0].transcript); r.start(); toast("Listening…");
  },
  edittext: (el) => {
    const field = el.dataset.field; const cur = S.project.plan[field];
    el.outerHTML = `<span><textarea id="et_${field}" rows="${field === "title" ? 2 : 3}">${esc(cur)}</textarea><span class="row" style="margin-top:6px"><button class="btn sm primary" data-act="savetext" data-field="${field}">Save</button><button class="btn sm" data-act="canceltext">Cancel</button></span></span>`;
  },
  savetext: (el) => edit({ op: "set_text", field: el.dataset.field, value: $(`#et_${el.dataset.field}`).value }),
  canceltext: () => rerender(),
  usellm: (el) => edit({ op: "set_text", field: el.dataset.field, value: S.project.plan[el.dataset.field + "_llm"] }),
  swap: () => edit({ op: "swap_roles" }, "swap exposure/outcome"),
  fix: (el) => { const i = (S.project.plan.review || []).find((x) => x.id === el.dataset.id); if (i?.fix) edit({ ...i.fix, by: store.get("q2e.name", "") || "investigator" }, `fix: ${i.title}`); },
  rmpill: (el) => { const f = el.dataset.field; edit({ op: `set_${f}`, value: S.project.plan[f].filter((x) => x !== el.dataset.v) }); },
  addcrit: async () => {
    const expr = $("#critExpr").value.trim(); const v = await api("/api/expressions/validate", { method: "POST", body: { expr } });
    if (!v.ok) return toast(v.error, true); edit({ op: "add_criterion", label: $("#critLabel").value || expr, expr, kind: $("#critKind").value });
  },
  addsens: async () => {
    const expr = $("#sExpr").value.trim(); const v = await api("/api/expressions/validate", { method: "POST", body: { expr } });
    if (!v.ok) return toast(v.error, true); edit({ op: "add_sensitivity", item: { type: "exclude", label: $("#sLabel").value || `Exclude ${expr}`, expr } });
  },
  plancycle: (el) => { const c = S.project.plan.dataset.cycles || []; const id = el.dataset.id; let n = c.includes(id) ? c.filter((x) => x !== id) : [...c, id]; if (!n.length) n = [id]; edit({ op: "set_cycles", value: n }); },
  plansource: (el) => edit({ op: "set_source", value: el.dataset.v }),
  gmap: (el) => edit({ op: "set_generic_mapping", block: el.dataset.block, expr: $(`#gm_${el.dataset.block}`).value.trim() }),
  dict: async () => { const q = $("#dictQ").value.trim(); if (!q) return; S.dict = await api("/api/dictionary/match", { method: "POST", body: { query: q, dataset_id: S.project.plan.dataset.dataset_id || null } }); rerender(); },
  approve: async () => {
    const by = $("#approver").value.trim(); if (!by) return toast("Enter your name", true); if (!$("#attest").checked) return toast("Confirm you reviewed the plan", true);
    store.set("q2e.name", by);
    try { S.project = await api(`/api/projects/${S.project.id}/approve`, { method: "POST", body: { by } }); toast("Protocol approved and locked by hash"); rerender(); } catch (e) { toast(e.message, true); }
  },
  run: async () => {
    try { await api(`/api/projects/${S.project.id}/run?actor=${encodeURIComponent(store.get("q2e.name", "investigator"))}`, { method: "POST" }); S.project = await api(`/api/projects/${S.project.id}`); S.run = null; S.results = null; go("run"); }
    catch (e) { toast(e.message, true); }
  },
  listen: async () => {
    const txt = (S.summary?.plain_language || "") + " " + (S.summary?.key_points?.meaning || "");
    if (S.meta.voice) {
      try { const r = await fetch("/api/voice/tts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: txt }) }); if (!r.ok) throw new Error((await r.json()).error);
        const a = $("#audio"); a.src = URL.createObjectURL(await r.blob()); a.style.display = "block"; a.play(); } catch (e) { toast(e.message, true); }
    } else if (window.speechSynthesis) { speechSynthesis.speak(new SpeechSynthesisUtterance(txt)); } else toast("No speech output available", true);
  },
  lit: async () => { S.lit = await api(`/api/projects/${S.project.id}/literature`); rerender(); },
  sign: async () => {
    const by = $("#signer").value.trim(); if (!by) return toast("Enter your name", true);
    const att = [...document.querySelectorAll(".att")]; if (att.some((a) => !a.checked)) return toast("All attestations are required", true);
    const overrides = {}; document.querySelectorAll(".ovr").forEach((t) => (overrides[t.dataset.id] = t.value));
    try { S.project = await api(`/api/projects/${S.project.id}/signoff`, { method: "POST", body: { by, run_id: latestRun().id, overrides, attestations: ATTEST } }); store.set("q2e.name", by); toast("Signed off"); rerender(); } catch (e) { toast(e.message, true); }
  },
  watch: async (el) => { el.disabled = true; el.innerHTML = `<span class="spinner"></span> Checking PubMed…`; S.watch = await api("/api/guidelines/watch"); rerender(); },
  importDef: async () => { try { S.proposal = await api("/api/guidelines/import", { method: "POST", body: { text: $("#gtext").value } }); rerender(); } catch (e) { toast(e.message, true); } },
  approveDef: async () => { try { await api("/api/guidelines/approve", { method: "POST", body: { id: S.proposal.id, by: $("#propBy").value || "investigator" } }); S.proposal = null; S.meta = await api("/api/meta"); toast("Definition added to library"); rerender(); } catch (e) { toast(e.message, true); } },
};
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]"); if (!el) return;
  const fn = A[el.dataset.act]; if (fn && !(el.tagName === "INPUT" || el.tagName === "SELECT")) { e.preventDefault(); fn(el, e); }
});
document.addEventListener("change", (e) => {
  const el = e.target; const act = el.dataset?.act; if (!act) return;
  if (act === "setdef") edit({ op: "set_definition", role: el.dataset.role, value: el.value });
  else if (act === "scale") edit({ op: "set", path: "exposure.scale", value: parseFloat(el.value) || 1 });
  else if (act === "crit") edit({ op: "enable_criterion", id: el.dataset.id, value: el.checked });
  else if (act === "sens") edit({ op: "enable_sensitivity", id: el.dataset.id, value: el.checked });
  else if (act === "family") edit({ op: "set", path: "model.family", value: el.value });
  else if (act === "addpill" && el.value) { const f = el.dataset.field; edit({ op: `set_${f}`, value: [...S.project.plan[f], el.value] }); }
});
document.addEventListener("input", (e) => { if (e.target.id === "q") store.set("q2e.q", e.target.value); if (e.target.id === "dsSel") S.ask.dataset = e.target.value; if (e.target.id === "provSel") S.ask.provider = e.target.value; });
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark"; store.set("q2e.theme", document.documentElement.dataset.theme);
});
(async function init() {
  const t = store.get("q2e.theme", ""); if (t) document.documentElement.dataset.theme = t;
  try { S.meta = await api("/api/meta"); } catch (e) { $("#main").innerHTML = `<div class="banner bad">Cannot reach the Q2E server: ${esc(e.message)}</div>`; return; }
  renderBoundary(); render();
})();
