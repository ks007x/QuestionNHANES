/* Q2E single-page app - vanilla JS, no build step. */
"use strict";

const S = { meta: null, project: null, run: null, results: null, summary: null, poll: null, lit: null, watch: null, proposal: null,
            ask: { cycles: [], source: "auto", provider: "", dataset: "" }, dict: null };
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
/* Why the next section is still locked (shown under the last step's Next button). */
const LOCK_REASON = { run: "Approve the analysis plan first (bottom of the Analysis plan page).",
                      results: "Run the analysis first and wait for it to finish.", signoff: "Run the analysis first and wait for it to finish." };
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
      const reach = S.reach[stepKey(s.id)] || 0;
      const subs = r.stage === s.id && (S.parts || []).length > 1 ? `<ol class="substeps">${S.parts.map((x, j) =>
        `<li class="${j === S.partIndex ? "on" : j <= reach ? "done" : "locked"}" data-act="${j <= reach ? "sub" : ""}" data-i="${j}">${j <= reach && j !== S.partIndex ? "✓ " : ""}${esc(x.title)}</li>`).join("")}</ol>` : "";
      return `<li class="${cls}" data-act="${unlocked(s.id) ? "go" : ""}" data-stage="${s.id}"><span class="n">${stageDone(s.id) && r.stage !== s.id ? "✓" : i + 1}</span>${s.label}${subs}</li>`;
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
      if (!S.project || S.project.id !== r.pid) { S.project = await api(`/api/projects/${r.pid}`); S.results = null; S.lit = null; S.where = null; }
      const lr = latestRun();
      if (lr && (!S.run || S.run.id !== lr.id || S.run.status === "running")) S.run = await api(`/api/projects/${r.pid}/runs/${lr.id}`);
      if (lr && S.run?.status === "completed" && (!S.results || S.results._rid !== lr.id)) {
        S.results = await api(`/api/projects/${r.pid}/runs/${lr.id}/results`); S.results._rid = lr.id;
        S.summary = await api(`/api/projects/${r.pid}/runs/${lr.id}/summary`);
      }
    }
  } catch (e) { main.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; return; }
  const views = { ask: viewAsk, projects: viewProjects, library: viewLibrary };
  if (r.view === "project") {
    const fn = { protocol: viewProtocol, map: viewMap, plan: viewPlan, run: viewRun, results: viewResults, signoff: viewSignoff }[r.stage] || viewProtocol;
    main.innerHTML = stepper(r.stage, fn());
    renderRail(r);
    if (r.stage === "run" && S.run?.status === "running") startPolling();
  } else { renderRail(r); main.innerHTML = await views[r.view](); }
  window.scrollTo({ top: 0 });
}
function rerender() { const y = window.scrollY; return render().then(() => window.scrollTo({ top: y })); }

/* ------------------------------------------------------------------ ASK */
async function viewAsk() {
  const k = S.meta.knowledge; const a = S.ask;
  const cyc = `<button class="${a.cycles.length ? "" : "on"}" data-act="cycleauto" title="Use the most recent cycle that measured your variables">Auto</button>` +
    Object.entries(k.cycles).map(([id, c]) => `<button class="${a.cycles.includes(id) ? "on" : ""}" data-act="cycle" data-id="${id}" title="${esc(c.note || "")}">${esc(c.label.replace("NHANES ", ""))}</button>`).join("");
  const src = [["auto", "CDC download / local"], ["local", "Local XPT folder"], ["synthetic", "Synthetic demo"]].map(([v, l]) => `<button class="${a.source === v ? "on" : ""}" data-act="source" data-v="${v}">${l}</button>`).join("");
  const provs = ["", "offline", "anthropic", "azure_openai", "bedrock", "openai", "ollama"];
  const ds = S.meta.datasets || [];
  const recent = (await api("/api/projects")).slice(0, 6);
  const dataNote = S.meta.data.local_files ? `${S.meta.data.local_files} NHANES files found in ${esc(S.meta.data.local_dir)}` :
    S.meta.data.allow_download ? "Files download from CDC on first use and are cached." : "Downloads disabled: place NHANES .xpt files in the local folder or use synthetic data.";
  return `<h1 class="page">From clinical observation to reproducible evidence</h1>
  <p class="lede">Describe a research idea in plain language. Q2E's agents turn it into a protocol, map it to NHANES (or your own open dataset), and draft a statistical analysis plan for your approval. Nothing runs until you approve it, and nothing is final until you sign off.</p>
  <div class="card">
    <textarea id="q" class="ask${S.rewrite ? " needs-fix" : ""}" placeholder="e.g. Do a research study on the prevalence of functional iron deficiency in US adults.">${esc(store.get("q2e.q", ""))}</textarea>
    ${S.rewrite ? rewriteCard(S.rewrite) : ""}
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
  ${S.clarify ? clarifyCard(S.clarify) : ""}
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

/* Interviewer: follow-up questions adapted to the expertise detected from the user's wording */
const LEVEL_NAMES = { novice: "Beginner", intermediate: "Intermediate", expert: "Expert" };
/* One question per screen: Back / Next arrows; Next stays locked until the current question is answered. */
function clarifyCard(c) {
  const ex = c.expertise; const n = c.questions.length; const step = c.step || 0;
  const q = c.questions[step]; const a = c.answers[q.id] || {};
  const dots = c.questions.map((_, i) => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;background:${i <= step ? "var(--accent, #4f8cc9)" : "var(--line, #555)"}"></span>`).join("");
  const opts = q.options.map((o) =>
    `<label class="small" style="display:flex;gap:8px;align-items:flex-start;cursor:pointer">
       <input type="radio" name="cq_${q.id}" value="${esc(o.id)}" data-act="cqopt" ${a.option === o.id ? "checked" : ""} style="margin-top:3px">
       <span><b>${esc(o.label)}</b>${o.hint ? `<br><span class="tiny muted">${esc(o.hint)}</span>` : ""}</span></label>`).join("");
  const last = step === n - 1;
  return `<div class="cq-overlay"><div class="card" id="clarifyCard">
    <div class="row" style="justify-content:space-between">
      <h3 class="sub" style="margin:0">Question ${step + 1} of ${n}</h3>
      <div class="row" style="gap:10px">
        <label class="small muted">Explanations for
          <select id="levelSel" data-act="level">${["novice", "intermediate", "expert"].map((l) =>
            `<option value="${l}" ${c.level_used === l ? "selected" : ""}>${LEVEL_NAMES[l]}${l === ex.level ? " (detected)" : ""}</option>`).join("")}</select></label>
        <button class="btn sm" data-act="cqClose" title="Close and go back to change your research idea">✕ Edit my idea</button>
      </div>
    </div>
    <p class="tiny muted" style="margin:6px 0 0">Your idea: “${esc(c.question)}”</p>
    ${c.fromProject ? `<div class="banner info" style="margin:10px 0 0;display:flex;justify-content:space-between;align-items:center;gap:10px">
      <span>These are your earlier answers. Changing them creates a new version of the study; the current one stays in Projects.</span>
      <button class="btn sm" data-act="backToStudy">Return to my study →</button></div>` : ""}
    <div style="margin-top:6px">${dots}</div>
    ${step === 0 && c.notice ? `<div class="banner info" style="margin:10px 0 0">${esc(c.notice)}</div>` : ""}
    ${step === 0 && (c.understood || []).length ? `<div class="tiny" style="margin-top:10px;padding:8px 10px;border:1px solid var(--line, #444);border-radius:8px">
      <b>What we understood from your idea</b> <span class="muted">(so we won't ask about these again; if something is wrong, use "Edit my idea")</span>
      <ul style="margin:4px 0 0 16px">${c.understood.map((u) => `<li><b>${esc(u.label)}:</b> ${esc(u.value)}${u.hint ? ` <span class="muted">- ${esc(u.hint)}</span>` : ""}</li>`).join("")}</ul></div>` : ""}
    <div style="margin-top:14px"><b>${esc(q.text)}</b>${q.why ? `<div class="tiny muted" style="margin-top:2px">Why we ask: ${esc(q.why)}</div>` : ""}</div>
    <div style="display:grid;gap:8px;margin-top:10px">${opts}</div>
    ${q.free_text ? `<input type="text" id="cqt_${q.id}" value="${esc(a.text || "")}" placeholder="${esc(q.free_text.placeholder)}" style="margin-top:10px;width:100%">` : ""}
    <div class="row" style="margin-top:16px;justify-content:space-between">
      <button class="btn" data-act="cqBack" ${step === 0 ? "disabled" : ""}>← Back</button>
      <button class="btn primary" id="cqNext" data-act="${last ? "clarifyGo" : "cqNext"}" ${answered(q, a) ? "" : "disabled"}>${last ? "Design my study →" : "Next →"}</button>
    </div>
    ${step === 0 ? `<details class="tiny muted" style="margin-top:10px"><summary style="cursor:pointer">Why these questions?</summary>
      <p style="margin:4px 0">We wrote them to match how your idea is worded. If they feel too simple or too technical, change "Explanations for" above.</p>
      <ul style="margin:4px 0 0 16px">${ex.signals.map((s) => `<li>${s.effect === "+" ? "More technical:" : "Less technical:"} ${esc(s.text)}</li>`).join("") || "<li>No strong signals either way.</li>"}</ul></details>` : ""}
  </div></div>`;
}
/* A question counts as answered when a choice is picked (plus any text that choice needs), or when text was typed. */
/* Shown under the idea box when nothing in the idea is something NHANES measured: what happened, what to do, one-click fixes. */
function rewriteCard(r) {
  let happened = esc(r.what_happened);
  for (const m of r.missing) happened = happened.split(esc(`"${m}"`)).join(`<mark class="rw-miss">${esc(m)}</mark>`);
  const chip = (t) => `<button data-act="rwSwap" data-use="${esc(t.use)}" title="${esc(t.hint)}">${esc(t.label)}</button>`;
  const swapTitle = r.missing.length ? `Or swap <mark class="rw-miss">${esc(r.missing[0])}</mark> for the closest thing NHANES measured`
    : "Or start from one of these topics";
  const total = r.all_topics.reduce((n, g) => n + g.topics.length, 0);
  return `<div class="rewrite" id="rewriteCard">
    <div class="row" style="justify-content:space-between;align-items:flex-start">
      <b>⚠ Your idea needs a small change before we can design a study</b>
      <button class="btn sm" data-act="rwClose" title="Hide this help">✕</button>
    </div>
    <ol class="small" style="margin:8px 0 0 18px;padding:0;display:grid;gap:4px">
      <li><b>What happened:</b> ${happened}</li>
      <li><b>What to do:</b> ${esc(r.what_to_do)} Then press <b>Design my study →</b> again.</li>
    </ol>
    ${r.examples.length ? `<div class="small" style="margin-top:12px"><b>Try one of these</b> <span class="muted tiny">(click to put it in the box)</span></div>
      <div class="examples" style="margin-top:6px">${r.examples.map((e) => `<button data-act="rwUse" data-q="${esc(e)}">${esc(e)}</button>`).join("")}</div>` : ""}
    <div class="small" style="margin-top:12px"><b>${swapTitle}</b> <span class="muted tiny">(hover a topic to see what it means)</span></div>
    <div class="examples" style="margin-top:6px">${r.related.map(chip).join("")}</div>
    <details style="margin-top:10px"><summary class="small" style="cursor:pointer">See all ${total} health topics NHANES measures</summary>
      ${r.all_topics.map((g) => `<div class="tiny muted" style="margin-top:8px">${esc(g.group)}</div><div class="examples" style="margin-top:4px">${g.topics.map(chip).join("")}</div>`).join("")}
    </details>
  </div>`;
}

function answered(q, a) {
  const text = (a.text || "").trim(); const ft = q.free_text;
  if (a.option && a.option === q.blocking_option) return false;   // e.g. "None of these": the idea needs rewording first
  if (a.option) return !(ft && ft.requires_option === a.option && !text);
  return !!(ft && !ft.requires_option && text);
}
function refreshNext() {
  const c = S.clarify; const q = c.questions[c.step]; const btn = $("#cqNext");
  if (btn) btn.disabled = !answered(q, c.answers[q.id] || {});
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
const AGENT_COLOR = { Investigator: "#1F5A85", "Data Steward": "#2E7D4F", Epidemiologist: "#7A4FB0", Statistician: "#B5651D", Reviewer: "#B3261E", "Privacy Guard": "#5C6B7A", Interviewer: "#0E7C86" };
function avatar(name) {
  const base = name.replace(/ \(LLM\)/, ""); const c = AGENT_COLOR[base] || "#5C6B7A";
  const ini = base.split(" ").map((w) => w[0]).join("").slice(0, 2);
  return `<div class="avatar" style="background:${c}${name.includes("LLM") ? ";outline:2px dashed " + c + ";outline-offset:2px" : ""}">${ini}</div>`;
}
function editable(field, text, cls = "") {
  return `<span class="editable ${cls}" data-act="edittext" data-field="${field}" title="Click to edit">${nice(text)}</span>`;
}
/* Protocol agent chat + change history (so the lead investigator can follow every change) */
const SOURCE_NAME = { chat: "asked the AI", edit: "edited by hand", undo: "undo", comment: "comment" };
function when(at) {
  const d = new Date(at); if (isNaN(d)) return esc(at || "");
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
function ageGroup(at) {
  const d = new Date(at); const now = new Date();
  if (d.toDateString() === now.toDateString()) return "Today";
  return now - d < 7 * 864e5 ? "This week" : "Earlier";
}
/* ---- Step-by-step walkthrough: every section shows ONE step at a time, with room for the analyst's input ---- */
S.sub = (() => { try { return JSON.parse(store.get("q2e.sub", "{}")) || {}; } catch { return {}; } })();
S.reach = (() => { try { return JSON.parse(store.get("q2e.reach", "{}")) || {}; } catch { return {}; } })();
const CAN_CHANGE = ["protocol", "map", "plan"];
function stepKey(stage) { return `${S.project.id}:${stage}`; }
function saveSteps() { store.set("q2e.sub", JSON.stringify(S.sub)); store.set("q2e.reach", JSON.stringify(S.reach)); }
/* Input lives on the specific items that need the analyst (they differ for every study), not in one general box. */
function canChangeHere() { return CAN_CHANGE.includes(route().stage) && !S.project.signoff; }
function msgHtml(m) {
  const ai = m.who === "Protocol agent";
  return `<div class="pc-msg ${ai ? "" : "me"} ${m.kind === "comment" ? "note" : ""}"><div class="who">${esc(ai ? "AI" : m.who || "analyst")}${m.kind === "comment" ? " · comment" : ""} <small>${when(m.at)}</small></div>
    <div class="txt">${nice(m.text || "")}</div>
    ${(m.summary || []).length ? `<ul class="small">${m.summary.map((s) => `<li>${nice(s)}</li>`).join("")}</ul>` : ""}
    ${(m.options || []).length ? `<div class="examples">${m.options.map((o) => `<button data-act="pcSend" data-msg="${esc(o.send)}" data-pt="${esc(m.step || "")}" title="${esc(o.hint || "")}">${esc(o.label)}</button>`).join("")}</div>` : ""}</div>`;
}
/* Plain-language name for a Reviewer fix; null when there is no one-click fix worth suggesting. */
function fixLabel(fix) {
  if (!fix) return null;
  const k = S.meta.knowledge; const p = S.project.plan;
  const lab = (n) => (k.blocks.find((b) => b.name === n) || {}).label || n;
  if (fix.op === "set_cycles") return "Use " + fix.value.map((c) => ((k.cycles[c] || {}).label || c).replace("NHANES ", "")).join(" + ");
  if (fix.op === "remove_covariate") return "Stop adjusting for " + lab(fix.name);
  if (fix.op === "set" && fix.path === "model.family" && fix.value === "quasipoisson") return "Report prevalence ratios instead";
  if (fix.op === "set" && fix.path === "exposure.scale") return "Report the effect per 1 unit";
  if (fix.op === "add_sensitivity" && fix.item) return "Add extra check: " + fix.item.label;
  if (fix.op === "enable_criterion") { const c = p.population.find((x) => x.id === fix.id); return c ? "Turn on rule: " + c.label : null; }
  if (fix.op === "soften_text") return "Rephrase without cause-and-effect wording";
  return null;
}
/* The conversation + input for ONE item. key ties messages to the item; title is what the history shows. */
function ptTalk(key, title) {
  const can = canChangeHere();
  const msgs = (S.project.protocol_chat || []).filter((m) => m.step === key).slice(-6);
  const thread = msgs.length ? `<div class="pc-list">${msgs.map(msgHtml).join("")}</div>` : "";
  const data = `data-pt="${esc(key)}" data-ptitle="${esc(title)}"`;
  if (S.openPt !== key) return `${thread}<button class="btn sm ghost pt-open" data-act="ptOpen" ${data}>${can ? "✎ Change or comment" : "💬 Comment"}</button>`;
  return `${thread}<div class="pt-input">
    <textarea id="pcInput" rows="2" maxlength="1000" ${data} placeholder="${can ? "Say what you want changed, or write a note for the lead investigator" : "Write a note for the lead investigator"}"></textarea>
    <div class="row" style="margin-top:6px">${can ? `<button class="btn primary sm" data-act="pcSend" id="pcBtn" ${data}>Ask the AI to change it</button>` : ""}
      <button class="btn sm" data-act="comment" ${data}>Save as a comment</button><button class="btn sm ghost" data-act="ptClose">Cancel</button></div></div>`;
}
/* One Reviewer finding, shown where it matters, with its fix (if any) and the analyst's input. */
function issuePoint(i) {
  const key = `issue:${i.id}`; const lbl = canChangeHere() ? fixLabel(i.fix) : null;
  const ack = i.fix && i.fix.op === "acknowledge" && canChangeHere();
  return `<div class="pt sev-${esc(i.severity)}"><div class="pt-row"><span class="sev ${esc(i.severity)}">${esc(i.severity)}</span>
      <div style="flex:1"><b class="small">${nice(i.title)}</b><div class="small muted">${nice(i.detail)}</div></div></div>
    ${lbl ? `<div class="examples" style="margin:6px 0 0"><span class="tiny muted">Suggested fix:</span> <button data-act="ptFix" data-id="${esc(i.id)}" data-pt="${esc(key)}" data-ptitle="${esc(i.title)}">${esc(lbl)}</button></div>` : ""}
    ${ack ? `<div style="margin-top:6px"><button class="btn sm" data-act="ptFix" data-id="${esc(i.id)}" data-pt="${esc(key)}" data-ptitle="${esc(i.title)}">✓ I accept this</button></div>` : ""}
    ${ptTalk(key, i.title)}</div>`;
}
/* Any item that is not a Reviewer finding (e.g. an uncertain variable match or a failed QC check). */
function notePoint(key, title, detail, sev = "minor") {
  return `<div class="pt sev-${sev}"><div class="pt-row"><span class="sev ${sev}">check</span>
      <div style="flex:1"><b class="small">${nice(title)}</b>${detail ? `<div class="small muted">${nice(detail)}</div>` : ""}</div></div>${ptTalk(key, title)}</div>`;
}
/* Which step each Reviewer finding belongs to. */
function issueStep(id) {
  if (/^(avail_|cycle_overlap)/.test(id)) return "map:table";
  if (/^unmapped_/.test(id)) return "map:columns";
  if (/^custom_/.test(id)) return "map:proposed";
  if (/^(verify_|opnotes_)/.test(id)) return "protocol:variables-inline";
  if (/^overlap_/.test(id)) return "protocol:variables";
  if (/^(pregnancy|small_pop)$/.test(id)) return "protocol:population";
  if (/^causal_/.test(id)) return "protocol:question";
  if (id === "answerability") return "protocol:feasible";
  if (/^(or_common|scale)$/.test(id)) return "plan:model";
  if (/^(mediator_|collinearity|multiplicity)/.test(id)) return "plan:adjust";
  if (/^(iron_inflammation|a1c_anemia|mi)$/.test(id)) return "plan:sensitivity";
  if (/^audit_/.test(id)) return "plan:audit";
  return "plan:review";
}
function attention(stage, partId, extra = "") {
  const its = (S.project.plan.review || []).filter((i) => issueStep(i.id) === `${stage}:${partId}` && (i.fix || i.severity !== "info"));
  if (!its.length && !extra) return "";
  return `<div class="attn"><h4>Needs your attention here</h4>${its.map(issuePoint).join("")}${extra}</div>`;
}
/* Small, collapsed way to raise anything else on a step (the analyst can always change things). */
function otherTalk(stage, part) {
  const key = `${stage}:${part.id}`;
  const has = (S.project.protocol_chat || []).some((m) => m.step === key);
  if (S.openPt !== key && !has) return `<div class="other-talk"><button class="btn sm ghost" data-act="ptOpen" data-pt="${esc(key)}" data-ptitle="${esc(part.title)}">${canChangeHere() ? "Something else to change or note on this step?" : "Add a note on this step"}</button></div>`;
  return `<div class="card other-talk"><h3 class="sub" style="margin-top:0">Other notes on this step</h3>${ptTalk(key, part.title)}</div>`;
}
function historyBar() {
  const ams = S.project.amendments || [];
  const last = ams[ams.length - 1];
  return `<div class="card hbar"><div class="row" style="justify-content:space-between;gap:8px">
      <span class="small"><b>Change history</b> <span class="chip accent">${ams.length}</span> <span class="muted">${last ? `last: ${when(last.at)} by ${esc(last.by || "analyst")}` : "no changes yet - this is the AI's first draft"}</span></span>
      <button class="btn sm ghost" data-act="histToggle">${S.histOpen ? "Hide ▴" : "Show ▾"}</button></div>
    ${S.histOpen ? `<div style="margin-top:10px">${changeHistoryCard()}</div>` : ""}</div>`;
}
function stepper(stage, v) {
  const parts = v.parts.filter(Boolean); const key = stepKey(stage);
  const i = Math.max(0, Math.min(S.sub[key] || 0, parts.length - 1));
  S.sub[key] = i; S.reach[key] = Math.max(S.reach[key] || 0, i); saveSteps();
  S.parts = parts; S.partIndex = i;
  const part = parts[i]; S.curStep = { stage, id: part.id, title: part.title };
  const reach = S.reach[key];
  const dots = parts.length > 1 ? `<div class="sp-dots">${parts.map((x, j) => {
    const ok = j <= reach; const cls = j === i ? "on" : ok ? "done" : "";
    return `<button class="sp-dot ${cls}" data-act="${ok ? "sub" : ""}" data-i="${j}" ${ok ? "" : "disabled"} title="${ok ? "" : "Finish the steps before this one first"}"><span class="n">${ok && j !== i ? "✓" : j + 1}</span>${esc(x.title)}</button>`;
  }).join("")}</div>` : "";
  const si = STEPS.findIndex((s) => s.id === stage); const prevS = STEPS[si - 1]; const nextS = STEPS[si + 1];
  const nextOk = nextS && unlocked(nextS.id);
  const back = i > 0 ? `<button class="btn" data-act="sub" data-i="${i - 1}">← Back</button>`
    : prevS ? `<button class="btn" data-act="go" data-stage="${prevS.id}">← Back to ${esc(prevS.label)}</button>`
    : `<button class="btn" data-act="backToAsk">← Back to your idea</button>`;
  const fwd = i < parts.length - 1 ? `<button class="btn primary" data-act="sub" data-i="${i + 1}">Looks good - next: ${esc(parts[i + 1].title)} →</button>`
    : nextS ? `<button class="btn primary" data-act="${nextOk ? "go" : ""}" data-stage="${nextS.id}" ${nextOk ? "" : "disabled"}>Done - go to ${esc(nextS.label)} →</button>` : "";
  return `${historyBar()}
  <div class="sp-head"><div class="tiny muted" style="text-transform:uppercase;letter-spacing:.08em">Section ${si + 1} of ${STEPS.length} · ${esc(STEPS[si].label)}${v.tag ? " · " + v.tag : ""}</div>
    <h1 class="page" style="margin-bottom:4px">${v.title}</h1>${v.lede ? `<p class="lede" style="margin-top:0">${v.lede}</p>` : ""}</div>
  ${dots}
  <div class="sp-step"><div class="sp-title"><span class="sp-n">Step ${i + 1} of ${parts.length}</span><h2>${esc(part.title)}</h2>${part.help ? `<p class="small muted" style="margin:2px 0 0">${part.help}</p>` : ""}</div>
    ${part.noTalk || part.noAttn ? "" : attention(stage, part.id, part.attn || "")}
    ${part.html}</div>
  ${part.noTalk ? "" : otherTalk(stage, part)}
  <div class="card sp-nav"><div class="row" style="justify-content:space-between">${back}${fwd}</div>
    ${i === parts.length - 1 && nextS && !nextOk ? `<p class="tiny muted" style="margin:8px 0 0;text-align:right">${esc(LOCK_REASON[nextS.id] || "Finish this section first.")}</p>` : ""}</div>`;
}
function changeHistoryCard() {
  const ams = (S.project.amendments || []).slice().reverse();
  const live = ams.filter((a) => !a.undone && a.source !== "undo" && a.source !== "comment");
  const latest = live.length ? live[0].id : null;
  const n = (g) => ams.filter((a) => ageGroup(a.at) === g).length;
  let lastGroup = "";
  const rows = ams.map((a) => {
    const g = ageGroup(a.at); const head = g !== lastGroup ? `<div class="ch-group">${g}</div>` : ""; lastGroup = g;
    return `${head}<div class="ch-item ${a.undone ? "undone" : ""}">
      <div class="row" style="justify-content:space-between;gap:8px"><span><b>${when(a.at)}</b> · ${esc(a.by || "analyst")} <span class="chip">${SOURCE_NAME[a.source] || esc(a.source)}</span>${a.undone ? ` <span class="chip warn">undone</span>` : ""}</span>
        <span class="tiny muted">${a.source === "comment" ? `on v${a.version_after ?? "?"}` : `v${a.version_before ?? "?"} → v${a.version_after ?? "?"}`}</span></div>
      ${a.step_title ? `<div class="tiny muted">Step: ${esc(a.step_title)}</div>` : ""}
      ${a.source === "chat" ? `<div class="small muted">Asked: “${esc(a.request)}”</div>` : ""}
      ${a.source === "comment" ? `<p class="small" style="margin:4px 0">“${esc(a.request)}”</p>` : `<ul class="small">${(a.summary || []).map((s) => `<li>${nice(s)}</li>`).join("")}</ul>`}
      <div class="row" style="gap:6px">${a.reason ? `<span class="small"><b>Why:</b> ${esc(a.reason)}</span>` : (!["undo", "comment"].includes(a.source) ? `<button class="btn sm ghost" data-act="amReason" data-id="${a.id}">+ Why? (optional)</button>` : "")}
        ${a.id === latest ? `<button class="btn sm" data-act="amUndo" data-id="${a.id}">↶ Undo this change</button>` : ""}</div></div>`;
  }).join("");
  return `<div class="card ch"><div class="row" style="justify-content:space-between"><h3 class="sub" style="margin:0">Change history <span class="chip accent">${ams.length}</span></h3>
      ${ams.length ? `<button class="btn sm ghost" data-act="amCopy" title="Copy a weekly summary to paste into an email or report">Copy weekly summary</button>` : ""}</div>
    <p class="tiny muted" style="margin:4px 0 8px">Every change and comment on this protocol, with date, time and who made it, so the lead investigator can follow along. Today: ${n("Today")} · This week: ${n("Today") + n("This week")} · Total: ${ams.length}</p>
    <div class="ch-list">${rows || `<p class="small muted" style="margin:0">No changes yet. This is the AI's first draft (v1).</p>`}</div></div>`;
}
function weeklySummary() {
  const p = S.project.plan; const ams = (S.project.amendments || []).filter((a) => new Date() - new Date(a.at) < 7 * 864e5);
  const lines = [`Protocol change summary (last 7 days): ${p.title}`, `Current version: v${p.version}. Changes: ${ams.length}.`, ""];
  for (const a of ams) {
    lines.push(`${new Date(a.at).toLocaleString()} - ${a.by || "analyst"} (${SOURCE_NAME[a.source] || a.source}${a.undone ? ", later undone" : ""})`);
    if (a.step_title) lines.push(`  Step: ${a.step_title}`);
    if (a.source === "chat") lines.push(`  Asked: "${a.request}"`);
    if (a.source === "comment") lines.push(`  Comment: "${a.request}"`);
    else for (const s of a.summary || []) lines.push(`  - ${s}`);
    if (a.reason) lines.push(`  Why: ${a.reason}`);
  }
  return lines.join("\n");
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
      ${String(v.concept || "").startsWith("dict:") ? `<div style="margin-top:10px">${notePoint(`protocol:variables:${role}`, `Is this the right NHANES survey item for your ${role}?`,
        `The AI matched your words to the official NHANES item <b>${esc(v.concept.slice(5))}</b>: “${esc(v.concept_label || "")}”. If you meant something else, say so.`)}</div>` : ""}
      ${issues.map((i) => `<div style="margin-top:10px">${i.fix ? issuePoint(i) : `<div class="row"><span class="sev ${i.severity}">${i.severity}</span><span class="small" style="flex:1">${nice(i.title)}</span><span class="chip ok">accepted</span></div>`}</div>`).join("")}
    </div>`;
  };
  const pop = p.population.map((c) => `<div class="crit"><label class="toggle"><input type="checkbox" data-act="crit" data-id="${c.id}" ${c.enabled ? "checked" : ""}><span></span></label>
    <div class="lbl"><span class="chip ${c.kind === "exclusion" ? "warn" : "accent"}" style="font-size:11px">${c.kind}</span> ${nice(c.label)}<div class="tiny muted">${esc(c.source || "")} · <code>${esc(c.expr)}</code></div></div></div>`).join("");
  return { title: "Your research protocol", tag: `plan v${p.version}`,
    lede: "The AI drafted your study. Check it one step at a time. Items that need your attention are marked, and you can change or comment on them right there.",
    parts: [
      { id: "question", title: "Your study question", help: "Check that this says what you want to study. Click any underlined text to edit it yourself.",
        html: `${p.privacy?.findings?.length ? `<div class="banner warn">Privacy guard redacted ${p.privacy.findings.length} identifier(s) from your question before processing.</div>` : ""}
        <div class="card"><div class="tiny muted" style="text-transform:uppercase;letter-spacing:.08em">${esc(p.study_type)} · cross-sectional</div>
          <h3 class="sub" style="margin-top:6px">Title</h3><p style="font:600 18px var(--serif);margin:0">${editable("title", p.title, "title-edit")}</p>
          <p class="muted small" style="margin:6px 0 0">Your original idea: “${esc(p.question)}”</p>
          <h3 class="sub">Research question</h3>
          <p style="font:400 16.5px/1.55 var(--serif);margin:0">${editable("refined_question", p.refined_question)}</p>
          ${p.refined_question_llm ? `<div class="row" style="margin-top:8px"><span class="chip accent">AI phrasing</span><span class="small" style="flex:1">${nice(p.refined_question_llm)}</span><button class="btn sm" data-act="usellm" data-field="refined_question">Use</button></div>` : ""}
          <h3 class="sub">What we expect to find (hypothesis)</h3><p style="margin:0">${editable("hypothesis", p.hypothesis)}</p>
          <details style="margin-top:12px"><summary class="small">Study summary in research terms (PICO)</summary><dl class="kv" style="margin-top:8px">${Object.entries(p.pico).map(([k2, v]) => `<dt>${esc(k2[0].toUpperCase() + k2.slice(1))}</dt><dd>${nice(v)}</dd>`).join("")}</dl></details>
        </div>` },
      { id: "feasible", title: "Can NHANES answer it?", help: "How well the NHANES data fits your question, and how often it has been studied before.",
        attn: f.score < 50 ? notePoint("protocol:feasible:score", `Feasibility is only ${f.score}/100`,
          f.components.filter((c) => c.score < c.max).map((c) => `${esc(c.name)}: ${c.score}/${c.max}${c.note ? " - " + esc(c.note) : ""}`).join("<br>"), "major") : "",
        html: `<div class="row" style="gap:14px;align-items:stretch;flex-wrap:wrap">
          <div class="card gauge"><div class="ring" style="--p:${f.score}"><div>${f.score}</div></div><div><b>${esc(f.label)} feasibility</b><div class="tiny muted">in ${p.dataset.type === "nhanes" ? "NHANES" : "uploaded data"}</div>
            <details><summary class="tiny">why this score</summary><ul class="tiny" style="padding-left:16px;margin:4px 0">${f.components.map((c) => `<li>${esc(c.name)}: ${c.score}/${c.max}${c.note ? " - " + esc(c.note) : ""}</li>`).join("")}</ul></details></div></div>
          ${noveltyGauge()}</div>
          <div style="margin-top:14px">${answerCard(p.answerability, { probeButton: true, probe: p.probe })}</div>` },
      { id: "variables", title: p.exposure ? "What you are comparing" : "What you are measuring",
        help: p.exposure ? "The <b>exposure</b> is the thing you think has an effect; the <b>outcome</b> is the health result you measure." : "The <b>outcome</b> is the health result you measure.",
        html: `<div class="grid ${p.exposure ? "g2" : ""}">${p.exposure ? varCard("exposure") : ""}${varCard("outcome")}</div>` },
      { id: "population", title: "Who is in the study", help: "These rules decide which people are counted. Switch a rule on or off, or add your own.",
        html: `<div class="card">${pop}
          <details style="margin-top:10px"><summary>Add your own rule</summary><div class="grid g4" style="margin-top:8px;align-items:end">
            <label class="field">Label<input type="text" id="critLabel" placeholder="e.g. Age 20-79 years"></label>
            <label class="field" style="grid-column:span 2">Expression<input type="text" id="critExpr" placeholder="age >= 20 & age < 80"></label>
            <label class="field">Type<select id="critKind"><option>inclusion</option><option>exclusion</option></select></label></div>
            <button class="btn sm" style="margin-top:8px" data-act="addcrit">Validate & add</button></details></div>` },
      { id: "agents", title: "What the AI team noticed", help: "Notes from the AI agents that designed the study. Read them, then leave a comment if you disagree.",
        html: `<div class="card dialog">${(p.agent_dialogue || []).map((d) => `<div class="msg">${avatar(d.agent)}<div><div class="who">${esc(d.agent)}<small>${d.source === "llm" ? "LLM" : "rules"}</small></div><div class="txt">${nice(d.message)}</div></div></div>`).join("") || `<p class="small muted">No notes.</p>`}</div>` },
    ] };
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
  return { title: "Where the data comes from",
    lede: `Each part of your study is linked to the exact ${p.dataset.type === "nhanes" ? "NHANES files and survey questions" : "columns in your dataset"} it uses. Check it one step at a time.`,
    parts: [
      { id: "table", title: "Your variables and their sources",
        help: "Each row is one thing your study uses. <b>Availability</b> shows which survey years have it (✓ yes, ✗ no). Click <b>expr</b> to see the exact formula.",
        html: `<div class="card"><div class="tablewrap"><table class="t"><thead><tr><th>Variable</th><th>Role</th><th>Source</th><th>Raw variables</th><th>Files</th><th>Availability</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>` },
      generic && { id: "columns", title: "Match your columns", help: "Tell Q2E which column in your file holds each item.", html: generic },
      custom.length && { id: "proposed", title: "Approve the AI's suggested variables", help: "The AI suggested these. They will not be used until you approve them.",
        html: `<div class="card">${custom.map((c) => `<div class="crit"><div class="lbl"><b>${esc(c.label)}</b> <code>${esc(c.name)} = ${esc(c.expr)}</code></div><button class="btn sm" data-act="fix" data-id="custom_${c.name}">Approve</button></div>`).join("")}</div>` },
      { id: "dictionary", title: "Search the data dictionary (optional)", help: "Look up any survey item, for example to check a variable exists. You can skip this step.",
        html: `<div class="card"><div class="row"><input type="text" id="dictQ" placeholder="Search the ${p.dataset.type === "nhanes" ? "NHANES" : "dataset"} dictionary (e.g. transferrin, liver stiffness, insulin)" style="flex:1"><button class="btn" data-act="dict">Search</button></div>
          ${S.dict ? `<table class="t" style="margin-top:10px"><thead><tr><th>Variable</th><th>Label</th><th>File</th><th>Cycles</th><th>Match</th><th></th></tr></thead><tbody>${S.dict.map((h) => `<tr><td><code>${esc(h.variable)}</code></td><td>${esc(h.label)}</td><td>${esc(h.table)}</td><td>${esc((h.cycles || []).join(", "))}</td><td><div style="width:80px;height:6px;background:var(--line-2);border-radius:3px"><div style="width:${h.confidence * 100}%;height:6px;background:var(--accent);border-radius:3px"></div></div><span class="tiny muted">${h.confidence}</span></td><td>${p.dataset.type === "nhanes" ? `<button class="btn sm" data-act="teach" data-var="${esc(h.variable)}" title="Remember a phrase for this variable in future questions">Teach</button>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}</div>` },
    ] };
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
  return { title: "How the analysis will be done", tag: `plan v${p.version}`,
    lede: "The AI statistician drafted this and an AI reviewer checked it. Go through it step by step; the last step is your approval.",
    parts: [
      { id: "model", title: "How the result is measured", help: "Which statistical model is used and what number it reports (for example an odds ratio).",
        html: `<div class="card"><h3 class="sub" style="margin-top:0">Estimand & model</h3>
      <label class="field">Model family<select data-act="family">${[["quasipoisson", "Survey quasi-Poisson (prevalence ratio)"], ["quasibinomial", "Survey logistic (odds ratio)"], ["gaussian", "Survey linear (mean difference)"]].map(([v, l]) => `<option value="${v}" ${p.model.family === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <p class="small" style="margin:10px 0 0">${nice(p.rationale.statistician)}</p>
      ${p.rationale.statistician_llm ? `<p class="small" style="margin:8px 0 0"><span class="chip accent">LLM</span> ${nice(p.rationale.statistician_llm)}</p>` : ""}
      <h3 class="sub">Adjustment sets</h3><ol class="small" style="margin:0;padding-left:18px">${p.adjustment_sets.map((a) => `<li><b>${esc(a.label)}</b>: ${a.covariates.length ? esc(a.covariates.join(", ")) : "none"}</li>`).join("") || "<li>Descriptive only</li>"}</ol>
      <h3 class="sub">Missing data</h3><p class="small" style="margin:0">${esc(p.missing_data.rationale)}</p>
    </div>` },
      { id: "adjust", title: "What the analysis takes into account", help: "<b>Covariates</b> are other factors the analysis adjusts for so the comparison is fair. Use × to remove one or <b>+ add</b> to add one.",
        html: `<div class="card"><h3 class="sub" style="margin-top:0">Variables</h3>
      <p class="small" style="margin:0 0 6px"><b>Covariates</b> <span class="muted">${esc(p.rationale.epidemiologist).slice(0, 220)}…</span></p>${pills("covariates", p.covariates, blockOpts)}
      ${Object.entries(p.covariate_notes || {}).map(([c, n]) => `<p class="tiny muted" style="margin:6px 0 0"><b>${esc(c)}</b>: ${nice(n)}</p>`).join("")}
      <p class="small" style="margin:14px 0 6px"><b>Subgroups</b></p>${pills("subgroups", p.subgroups, catOpts)}
      ${p.study_type === "association" ? `<p class="small" style="margin:14px 0 6px"><b>Effect modifiers (interaction tests)</b></p>${pills("interactions", p.interactions, catOpts)}` : ""}
      <h3 class="sub">Data</h3><div class="row"><span class="small muted">Cycles</span><div class="seg">${cyc}</div><span class="small muted">Source</span><div class="seg">${src}</div></div>
      ${p.benchmarks?.length ? `<h3 class="sub">Benchmark against published literature</h3>${p.benchmarks.map((b) => `<p class="small" style="margin:0 0 4px">${esc(b.label)}: <b>${pct(b.estimate, 0)}</b> (${pct(b.lcl, 0)}-${pct(b.ucl, 0)}), n=${(b.n || 0).toLocaleString()}</p>`).join("")}` : ""}
    </div>` },
      { id: "sensitivity", title: "Extra checks (sensitivity analyses)", help: "Repeat the analysis in slightly different ways to see if the answer holds up. Switch checks on or off.",
        html: `<div class="card">${sens || `<p class="small muted">None planned.</p>`}
          <details style="margin-top:8px"><summary>Add your own check</summary><div class="grid g3" style="margin-top:8px;align-items:end"><label class="field">Label<input type="text" id="sLabel" placeholder="Exclude current smokers"></label><label class="field">Exclude if<input type="text" id="sExpr" placeholder='smoking == "Current"'></label><button class="btn sm" data-act="addsens">Validate & add</button></div></details></div>` },
      p.arms && { id: "arms", title: "Comparison groups", help: "Who is compared with whom. Choose how the control group is defined and what happens to people positive for more than one group.",
        html: armsCard(p) },
      { id: "audit", title: "Design audit", help: "Checks against common criticisms of this kind of study (e.g. TriNetX-style EHR studies).",
        html: auditCard(p.design_audit) || `<p class="small muted">No audit available.</p>` },
      { id: "review", title: "AI reviewer's concerns", help: `${blockers.length || pendingAck.length ? "<b>Action needed:</b> press the button next to each item marked blocker or major before you can approve." : "Read each point. Press <b>Apply fix</b> or <b>Acknowledge</b> where offered."}`,
        noAttn: true,
        html: `<div class="card">${issues.length ? issues.map(issuePoint).join("") : `<p class="muted small">No issues - the reviewer found nothing to fix.</p>`}</div>` },
      { id: "approve", title: "Approve the plan", help: "Approving locks this exact version of the plan so it can be run. Any later change needs approval again.",
        html: `<div class="card">${approved ? `<div class="banner ok" style="margin:0 0 12px">Approved: plan v${p.version} (sha256 ${esc(S.project.plan_hash.slice(0, 12))}) by ${esc((p.approvals.filter((a) => (a.stage || "protocol") === "protocol").pop() || {}).by || "")}.</div>
      ${S.project.stats_signed_current ? `<p class="small"><span class="chip ok">Statistical review signed</span> ${esc((p.approvals.filter((a) => a.stage === "statistics").pop() || {}).by || "")}</p>` : `<div class="row" style="margin-bottom:10px"><input type="text" id="statname" placeholder="Statistician / epidemiologist name"><button class="btn sm" data-act="statsign">Record statistical sign-off</button></div>`}
      <button class="btn primary" data-act="run">Run analysis in R →</button>` :
    `${blockers.length ? `<div class="banner bad">Resolve ${blockers.length} blocker(s) before approval.</div>` : ""}${pendingAck.length ? `<div class="banner warn">Acknowledge ${pendingAck.length} operational assumption(s) (see critique).</div>` : ""}
    <div class="row"><input type="text" id="approver" placeholder="Your name" value="${esc(store.get("q2e.name", ""))}"><label class="row small"><input type="checkbox" id="attest"> I reviewed the protocol, variable mappings, definitions and this analysis plan.</label>
    <button class="btn primary" data-act="approve" ${canApprove ? "" : "disabled"}>Approve protocol</button></div>`}</div>` },
    ] };
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
  const head = { title: "Run & check the analysis", lede: "Your approved plan is run by the R engine, and every result is checked automatically before you see it." };
  if (!lr) return { ...head, parts: [{ id: "start", title: "Start the analysis", help: "Approve the plan first (last step of the Analysis plan), then run it.",
    html: `<div class="empty"><button class="btn primary" data-act="run" ${S.project.approved_current ? "" : "disabled"}>Run analysis</button></div>` }] };
  const stale = lr.plan_hash !== S.project.plan_hash;
  const staleBanner = stale ? `<div class="banner warn">The plan has changed since this run (run plan ${esc(lr.plan_hash.slice(0, 10))}). Re-approve and re-run to update results. ${S.project.approved_current ? `<button class="btn sm" data-act="run">Re-run now</button>` : ""}</div>` : "";
  if (r.status === "running") return { ...head, parts: [{ id: "running", title: "Running…", help: "This usually takes under a minute. The page updates by itself.", noTalk: true,
    html: `${staleBanner}<div class="card"><p><span class="spinner"></span> Executing approved plan in the R engine (survey package)…</p><div class="console" id="console">${esc(r.log.join("\n"))}</div></div>` }] };
  if (r.status === "failed") return { ...head, parts: [{ id: "failed", title: "The run failed", help: "Read the message below. You can leave a comment for the lead investigator.",
    html: `${staleBanner}<div class="banner bad"><b>Run failed:</b> ${esc(r.error)}</div>${/not found|download/i.test(r.error || "") ? `<div class="banner info">NHANES files were not available. Place the .xpt files in <code>${esc(S.meta.data.local_dir)}</code>, enable CDC downloads, or switch the data source to <b>Synthetic</b> in the analysis plan for an offline demo.</div>` : ""}<div class="console">${esc(r.log.join("\n"))}</div>` }] };
  if (!S.results) return { ...head, parts: [{ id: "wait", title: "Loading results…", html: `<p class="small muted">One moment.</p>`, noTalk: true }] };
  {
    const R = S.results; const c = R.checks; const cnt = (s) => c.filter((x) => x.status === s).length;
    return { ...head, parts: [
      { id: "checks", title: "Automatic quality checks", help: "Green passed. <b>Yellow</b> means look carefully. <b>Red</b> failed and needs a written reason at sign-off.",
        html: `${staleBanner}${R.meta.synthetic ? `<div class="banner warn">Synthetic NHANES-like data - pipeline demonstration only; estimates are not population estimates.</div>` : ""}
    <div class="row" style="margin-bottom:12px"><span class="chip ok">${cnt("pass")} pass</span><span class="chip warn">${cnt("warn")} warn</span><span class="chip bad">${cnt("fail")} fail</span><span class="chip info">${cnt("info")} info</span><span class="small muted">${R.meta.seconds}s · ${esc(R.meta.r_version)}</span></div>
    <div class="checks">${c.map((x) => `<div class="check ${x.status}"><span class="tiny muted">${esc(x.category)} · ${x.status.toUpperCase()}</span><b>${nice(x.title)}</b><p>${nice(x.message)}</p>
      ${x.status === "warn" || x.status === "fail" ? ptTalk(`qc:${x.id || x.title}`, `Quality check: ${x.title}`) : ""}</div>`).join("")}</div>` },
      { id: "flow", title: "Who was included", help: "How many people were in the data, how many were left out and why, and how the survey design was handled.",
        html: `<div class="grid g2"><div class="card"><h3 class="sub" style="margin-top:0">Participant flow</h3><div class="flow">${R.flow.map((f, i) => `${i ? `<div class="arrow">${f.excluded ? `<span>− ${f.excluded.toLocaleString()} ${esc(f.kind === "exclusion" ? "excluded" : "not eligible")}</span>` : ""}</div>` : ""}<div class="box"><b>${f.n.toLocaleString()}</b> <span class="small">${nice(f.label)}</span></div>`).join("")}</div></div>
      <div class="card"><h3 class="sub" style="margin-top:0">Survey design</h3><dl class="kv"><dt>Weight</dt><dd><code>${esc(R.design.weight_variable)}</code> (${esc(R.design.weight_level)})</dd><dt>Cycles</dt><dd>${esc(R.design.cycles.join(", "))}</dd><dt>Strata / PSUs</dt><dd>${R.design.n_strata} / ${R.design.n_psu} (design df ${R.design.design_df})</dd><dt>Analytic df</dt><dd>${R.design.analytic_df}</dd><dt>Represents</dt><dd>${fx(R.design.sum_weights_millions, 1)} million people</dd><dt>Variance</dt><dd>Taylor linearization; lonely PSU: ${esc(R.design.lonely_psu)}</dd></dl>
      <h3 class="sub">Source files</h3><ul class="tiny" style="padding-left:16px;margin:0">${R.meta.files.map((f) => `<li>${esc(f.file)} · ${esc(f.origin)} · n=${f.nrow.toLocaleString()} · md5 <span class="hash">${esc(f.md5.slice(0, 12))}</span></li>`).join("")}</ul></div></div>` },
      { id: "technical", title: "Technical details (optional)", help: "For checking the exact calculations. You can skip this step.",
        html: `<details class="card"><summary>Derivation audit (${R.derivation_audit.length} variables)</summary><table class="t" style="margin-top:8px"><thead><tr><th>Variable</th><th>Expression</th><th>Non-missing</th><th>Positive / distribution</th></tr></thead><tbody>${R.derivation_audit.map((a) => `<tr><td><code>${esc(a.name)}</code></td><td><code class="tiny">${esc(a.expr)}</code></td><td class="num">${a.n_nonmissing.toLocaleString()}</td><td class="tiny">${a.n_positive != null ? a.n_positive.toLocaleString() + " positive" : a.quantiles ? "min/Q1/med/Q3/max: " + a.quantiles.join(" / ") : a.levels ? Object.entries(a.levels).map(([k2, v]) => `${esc(k2)}: ${v}`).join("; ") : ""}</td></tr>`).join("")}</tbody></table></details>
    <details class="card" style="margin-top:10px"><summary>Engine log & executed calls</summary><div class="console" style="margin-top:8px">${esc(R.log.join("\n"))}\n\n${esc(R.trace.join("\n"))}</div></details>` },
    ] };
  }
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
      <div class="bar"><i class="rep" style="left:${pos(b.replicated_lcl)};width:calc(${pos(b.replicated_ucl)} - ${pos(b.replicated_lcl)})"></i><em style="left:${pos(b.replicated)}"></em></div>
      ${b.overlap ? "" : ptTalk(`bench:${b.outcome_label}`, `Differs from literature: ${b.outcome_label}`)}</div>`;
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
  if (!R) return { title: "Results", parts: [{ id: "none", title: "No results yet", html: `<div class="empty">Run the analysis first.</div>`, noTalk: true }] };
  const base = `/api/projects/${S.project.id}/runs/${lr.id}`;
  const prevRows = R.prevalence.map((x) => `<tr><td>${nice(x.outcome_label)}${x.outcome_level ? " - " + esc(x.outcome_level) : ""}</td><td>${esc(x.group_var === "Overall" ? "" : x.group_label)}</td><td>${esc(x.group)}</td><td class="num">${x.n.toLocaleString()}</td><td class="num">${pct(x.est)} (${pct(x.lcl)}-${pct(x.ucl)})</td><td class="num">${x.pop_millions ?? ""}</td><td>${x.nchs === "meets standard" ? `<span class="chip ok" style="font-size:10.5px">ok</span>` : `<span class="chip warn" style="font-size:10.5px" title="${esc(x.nchs)}">flag</span>`}</td></tr>`).join("");
  const mrows = R.models.flatMap((m) => m.terms.filter((t) => t.term !== "(Intercept)" && (p.study_type !== "association" || t.variable === R.primary_estimate?.term)).map((t) => `<tr><td>${esc(m.label)}</td><td>${nice(t.label)}</td><td class="num">${m.n.toLocaleString()}</td><td class="num">${fx(t.est)} (${fx(t.lcl)} to ${fx(t.ucl)})</td><td class="num">${pfmt(t.p)}</td></tr>`)).join("");
  const srows = R.sensitivity.map((s) => `<tr><td>${nice(s.label)}</td><td class="num">${s.n?.toLocaleString() ?? ""}</td><td class="num">${s.error ? `<span style="color:var(--bad)">${esc(s.error)}</span>` : s.effect === "prevalence" ? `${pct(s.est)} (${pct(s.lcl)}-${pct(s.ucl)})` : `${esc(s.effect)} ${fx(s.est)} (${fx(s.lcl)} to ${fx(s.ucl)})`}</td><td class="tiny">${esc(s.note || "")}</td></tr>`).join("");
  const synth = R.meta.synthetic ? `<div class="banner warn">Synthetic demonstration data - illustrative estimates only.</div>` : "";
  return { title: "Results", lede: nice(p.refined_question), parts: [
    { id: "main", title: "The main finding", help: "The headline number, then the same result in plain words. Press Listen to hear it.",
      html: `${synth}<div class="card">${headline()}</div>
  <div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Plain-language summary</h3><p style="margin:0 0 10px">${nice(sm.plain_language || "")}</p>
    <div class="row"><button class="btn sm" data-act="listen">🔊 Listen${S.meta.voice ? " (ElevenLabs)" : ""}</button><span class="tiny muted">Key point: ${nice(sm.key_points?.findings || "")}</span></div><audio id="audio" controls style="display:none;margin-top:8px;width:100%"></audio></div>` },
    benchCards() && { id: "bench", title: "Does it match published studies?", help: "Q2E's numbers next to numbers already published, as a sanity check.",
      html: `<div class="grid g2">${benchCards()}</div>` },
    R.figures.length && { id: "figures", title: "Figures", help: "Charts of the results.",
      html: `<div class="grid g2">${R.figures.map((f, i) => `<figure class="fig"><img src="${base}/files/${f.file}" alt="${esc(f.title)}" loading="lazy"><figcaption><b>Figure ${i + 1}.</b> ${nice(f.title)}</figcaption></figure>`).join("")}</div>` },
    { id: "tables", title: "Tables", help: "Table 1 describes the people in the study; the other tables give the detailed numbers.",
      html: `<h3 class="sub" style="margin-top:0">Table 1. Characteristics${R.table1?.by_label ? " by " + nice(R.table1.by_label) : ""}</h3>${table1()}
  ${prevRows ? `<h3 class="sub">Table 2. Weighted prevalence</h3><div class="tablewrap"><table class="t"><thead><tr><th>Outcome</th><th>Subgroup</th><th>Level</th><th>n</th><th>Weighted % (95% CI)</th><th>Millions</th><th>NCHS</th></tr></thead><tbody>${prevRows}</tbody></table></div>` : ""}
  ${mrows ? `<h3 class="sub">Table 3. Regression (${esc(R.models[0].effect_label)})</h3><div class="tablewrap"><table class="t"><thead><tr><th>Model</th><th>Term</th><th>n</th><th>Estimate (95% CI)</th><th>P</th></tr></thead><tbody>${mrows}</tbody></table></div>` : ""}
  ${R.interactions.length ? `<h3 class="sub">Effect modification</h3><div class="card">${R.interactions.map((it) => `<p class="small" style="margin:0 0 6px"><b>${esc(it.label)}</b> · P<sub>interaction</sub> ${pfmt(it.p_interaction)} · ${it.strata.map((s) => `${esc(s.level)}: ${fx(s.est)} (${fx(s.lcl)} to ${fx(s.ucl)})`).join(" · ")}</p>`).join("")}</div>` : ""}` },
    R.arms && R.arms.vs_reference && { id: "arms", title: "Comparison groups", help: "Each group against the control group, every pair of groups, and an overall test of whether the groups differ.",
      html: armsResults(R.arms) },
    { id: "sensitivity", title: "Extra checks (sensitivity analyses)", help: "If these give similar answers to the main finding, the result is more trustworthy.",
      html: `<div class="tablewrap"><table class="t"><thead><tr><th>Analysis</th><th>n</th><th>Estimate</th><th>Note</th></tr></thead><tbody>${srows}</tbody></table></div>` },
    { id: "literature", title: "Related published studies", help: "Search PubMed for NHANES studies on the same topic.",
      html: `<div class="card">${S.lit ? (S.lit.error ? `<p class="small" style="color:var(--bad)">${esc(S.lit.error)}</p>` : S.lit.results.map((r) => `<p class="small" style="margin:0 0 6px"><a href="${r.url}" target="_blank" rel="noopener">${esc(r.title)}</a> <span class="muted">${esc(r.first_author)} · ${esc(r.journal)} · ${esc(r.pubdate)}</span></p>`).join("") || `<p class="muted small">No matches.</p>`) + `<p class="tiny muted">Query: <code>${esc(S.lit.query)}</code></p>` : `<button class="btn sm" data-act="lit">Search PubMed for related NHANES studies</button>`}</div>
` },
    { id: "where", title: "Where to publish and get funding", help: "Journals that publish studies like this, upcoming conference deadlines, and NIH funding leads.",
      html: whereNext() },
    { id: "outputs", title: "Download your outputs", help: "The manuscript draft, the data bundle so anyone can repeat the analysis, and the exact plan that was run.",
      html: `<div class="card row">
    <a class="btn primary" href="${base}/report.html" target="_blank">Manuscript (JAMA Netw Open style)</a>
    ${S.meta.llm.enabled ? `<a class="btn" href="${base}/report.html?llm=true" target="_blank">Manuscript + AI narrative</a>` : ""}
    <a class="btn" href="${base}/report.md" target="_blank">Markdown</a>
    <a class="btn" href="${base}/bundle.zip">Reproducibility bundle (.zip)</a>
    <a class="btn ghost" href="/api/projects/${S.project.id}/compiled" target="_blank">Compiled plan JSON</a></div>` },
  ] };
}

function armsCard(p) {
  const a = p.arms; const on = (c) => c ? "on" : "";
  return `<div class="card"><p class="small" style="margin:0 0 8px">${a.levels.map((l, i) => `<span class="chip ${i === 0 ? "accent" : ""}">${esc(l)}${i === 0 ? " (reference)" : ""}</span>`).join(" ")}</p>
    <div class="row" style="gap:16px;flex-wrap:wrap;margin-bottom:8px">
      <div><div class="tiny muted">Control group</div><div class="seg"><button class="${on(a.control_mode === "seronegative")}" data-act="armset" data-k="control_mode" data-v="seronegative">Negative for all groups</button><button class="${on(a.control_mode === "healthy")}" data-act="armset" data-k="control_mode" data-v="healthy">Healthy controls</button></div></div>
      ${a.arms.length > 1 ? `<div><div class="tiny muted">Positive for more than one</div><div class="seg"><button class="${on(a.both === "separate")}" data-act="armset" data-k="both" data-v="separate">Own group</button><button class="${on(a.both === "exclude")}" data-act="armset" data-k="both" data-v="exclude">Exclude</button></div></div>` : ""}
    </div>
    ${a.control_mode === "healthy" ? `<p class="small" style="margin:0 0 4px"><b>Healthy controls</b> are negative for every group and free of: ${a.control_criteria.map((c) => esc(c.label.toLowerCase())).join(", ") || "-"}.</p>` : `<p class="small" style="margin:0 0 4px">Controls are negative for every group, with no health restriction.</p>`}
    ${(a.control_criteria_unavailable || []).length ? `<p class="tiny muted" style="margin:0">Not used: ${a.control_criteria_unavailable.map(esc).join(", ")} (not measured in this cycle or part of the outcome).</p>` : ""}
    ${a.control_mode === "healthy" ? `<p class="tiny muted" style="margin:4px 0 0">Healthy controls inflate group differences (healthy-control bias); the all-negative control group is run as a sensitivity analysis.</p>` : ""}</div>`;
}

function armsResults(a) {
  const f = (x) => x == null ? "NA" : (a.effect === "Beta" ? x.toFixed(2) : x.toFixed(2));
  const rows = (lst) => lst.map((r) => `<tr><td>${esc(r.comparison)}</td><td>${esc(r.versus)}</td><td><b>${f(r.est)}</b> (${f(r.lcl)}-${f(r.ucl)})</td><td>${pfmt(r.p)}</td></tr>`).join("");
  const n = a.n_by_group ? Object.entries(a.n_by_group).map(([k2, v]) => `${esc(k2)}: ${v}`).join(" · ") : "";
  return `<div class="card"><p class="tiny muted" style="margin:0 0 6px">Effect measure: ${esc(a.effect)}</p><div class="tablewrap"><table class="t"><thead><tr><th>Group</th><th>Compared with</th><th>Estimate (95% CI)</th><th>P</th></tr></thead><tbody>${rows(a.vs_reference)}${a.pairwise.length ? `<tr><td colspan="4" class="tiny muted">Between groups</td></tr>${rows(a.pairwise)}` : ""}</tbody></table></div>
    <p class="tiny muted" style="margin:6px 0 0">Overall test that the groups differ: P ${pfmt(a.p_overall)} (design-based Wald, ${a.df} df). Analytic n by group: ${n}.</p></div>`;
}

function auditCard(a) {
  if (!a) return "";
  const cls = { pass: "ok", caution: "warn", fail: "bad" };
  return `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><b>${esc(a.grade)}</b><span class="tiny muted">${a.counts.pass} pass · ${a.counts.caution} caution · ${a.counts.fail} fail</span></div>
  ${a.checks.map((c, i) => `<div class="issue"><span class="chip ${cls[c.status]}">${esc(c.area)}</span><div><b class="small">${esc(c.title)}</b> <span class="tiny muted">answers: ${esc(c.critique)}</span><div class="small muted">${esc(c.detail)}${c.fix && c.fix.op === "note" ? " " + esc(c.fix.text) : ""}</div>
    ${c.status !== "pass" ? ptTalk(`audit:${i}:${c.area}`, `Design audit: ${c.title}`) : ""}</div><div></div></div>`).join("")}</div>`;
}

function noveltyGauge() {
  const n = S.project.novelty;
  if (!n || n.score == null) return `<div class="card gauge"><div class="ring" style="--p:0"><div>?</div></div><div><b>Novelty</b><div class="tiny muted">${n?.error ? esc(n.error) : "PubMed/MEDLINE precedent"}</div><button class="btn sm" data-act="novelty" style="margin-top:6px">Check novelty</button></div></div>`;
  const stale = n.plan_version !== S.project.plan.version;
  return `<div class="card gauge"><div class="ring nov" style="--p:${n.score}"><div>${n.score}</div></div><div><b>${esc(n.label)} novelty</b><div class="tiny muted">${n.exact} NHANES paper(s) in PubMed, 10 y${stale ? " · plan changed - recheck" : ""}</div>
    <details><summary class="tiny">evidence</summary><div class="tiny" style="max-width:340px">${esc(n.summary)}${n.levers.length ? `<ul style="padding-left:16px;margin:4px 0">${n.levers.map((l) => `<li>+${l.points} ${esc(l.lever)}</li>`).join("")}</ul>` : ""}${(n.closest || []).slice(0, 3).map((c) => `<div style="margin-top:3px"><a href="${c.url}" target="_blank" rel="noopener">${esc(c.title)}</a> <span class="muted">${esc(c.journal)}</span></div>`).join("")}${(n.suggestions || []).length ? `<div style="margin-top:6px"><b>Differentiate:</b><ul style="padding-left:16px;margin:2px 0">${n.suggestions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}<button class="btn sm" data-act="novelty" style="margin-top:6px">Recheck</button></div></details></div></div>`;
}

function whereNext() {
  const W = S.where;
  if (!W) return `<div class="card"><p class="small muted" style="margin:0 0 10px">Score journals by how often they publish NHANES studies like this one, list the next conference abstract windows, and find NIH funding that pays for this topic.</p><button class="btn sm" data-act="where">Find journals, deadlines &amp; funding</button></div>`;
  const chipFor = (u) => u === "this month" ? "bad" : u === "soon" ? "warn" : "info";
  const jr = W.journals.map((j) => `<tr><td><b>${j.score}</b></td><td>${j.url ? `<a href="${j.url}" target="_blank" rel="noopener">${esc(j.journal)}</a>` : esc(j.journal)}${j.open_access ? ' <span class="chip ok">OA</span>' : ""}</td><td class="small muted">${esc(j.why)}</td></tr>`).join("");
  const cr = W.conferences.map((c) => `<tr><td><span class="chip ${chipFor(c.urgency)}">${esc(c.deadline_estimate)}</span></td><td><a href="${c.url}" target="_blank" rel="noopener">${esc(c.conference)}</a><div class="tiny muted">${esc(c.society)} · meets ${esc(c.meeting)}</div></td><td class="small">${c.days_until_estimate} d</td></tr>`).join("");
  const F = W.funding;
  const rep = F.reporter ? `<p class="small" style="margin:8px 0 4px"><b>${F.reporter.total}</b> NIH-funded projects ${esc(F.reporter.scope || "match this topic")} · ${Object.entries(F.reporter.by_institute).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")} · ${Object.entries(F.reporter.by_mechanism).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</p>${F.reporter.examples.map((p) => `<p class="tiny" style="margin:0 0 3px">${p.url ? `<a href="${p.url}" target="_blank" rel="noopener">${esc(p.number)}</a>` : esc(p.number)} · ${esc(p.title || "")} <span class="muted">(${esc(p.ic || "")}, FY${p.fiscal_year})</span></p>`).join("")}` : "";
  const opp = F.opportunities?.opportunities?.length ? `<p class="small" style="margin:10px 0 4px"><b>Open / forecasted NIH opportunities</b></p>${F.opportunities.opportunities.map((o) => `<p class="tiny" style="margin:0 0 3px"><a href="${o.url}" target="_blank" rel="noopener">${esc(o.number)}</a> · ${esc(o.title)} <span class="muted">(${esc(o.status)}, closes ${esc(o.close_date)})</span></p>`).join("")}` : "";
  return `${W.errors.length ? `<p class="tiny muted">Live sources unavailable (${esc(W.errors.join("; "))}) - showing curated results.</p>` : ""}
  <div class="grid g2">
    <div class="card"><h3 class="sub" style="margin-top:0">Journal match score</h3><div class="tablewrap"><table class="t"><thead><tr><th>Score</th><th>Journal</th><th>Evidence</th></tr></thead><tbody>${jr}</tbody></table></div></div>
    <div class="card"><h3 class="sub" style="margin-top:0">Next abstract deadlines</h3><div class="tablewrap"><table class="t"><thead><tr><th>Deadline (est.)</th><th>Conference</th><th>In</th></tr></thead><tbody>${cr}</tbody></table></div><p class="tiny muted">Typical windows - confirm exact dates on each official page.</p></div>
  </div>
  <div class="card" style="margin-top:14px"><h3 class="sub" style="margin-top:0">Funding leads</h3>
    <p class="small" style="margin:0 0 4px">${F.institutes.map((i) => `<a href="${i.url}" target="_blank" rel="noopener">NIH ${esc(i.ic)}</a>`).join(" · ")}${F.foundations.length ? " · " + F.foundations.map((f) => `<a href="${f.url}" target="_blank" rel="noopener">${esc(f.name)}</a>`).join(" · ") : ""}</p>
    <p class="tiny muted" style="margin:0 0 6px">${F.mechanisms.map((m) => `<b>${esc(m.code)}</b> ${esc(m.fit)}`).join(" · ")}</p>${rep}${opp}
    <details style="margin-top:10px"><summary class="small">Specific Aims seed (uses this study as preliminary data)</summary><pre class="tiny" style="white-space:pre-wrap">${esc(W.aims_seed)}</pre></details>
    <p class="tiny muted" style="margin-top:8px">${esc(W.method)}</p></div>`;
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
    return { title: "Signed off", parts: [{ id: "certificate", title: "Sign-off certificate", help: "This study is finished and locked. You can still leave comments for the record.",
      html: `<div class="cert"><h3>${esc(pj.plan.title)}</h3><p class="small">Signed by <b>${esc(so.by)}</b> on ${esc(so.at.replace("T", " "))}${so.synthetic ? ` · <span class="chip warn">synthetic data</span>` : ""}</p>
      <dl class="kv"><dt>Plan hash</dt><dd class="hash">${esc(so.plan_hash)}</dd><dt>Results hash</dt><dd class="hash">${esc(so.results_sha256)}</dd><dt>Run</dt><dd>${esc(so.run_id)}</dd><dt>Provenance</dt><dd>${pj.chain.valid ? `✓ ${pj.chain.events} events, chain intact` : "✗ chain broken"} <span class="hash">${esc(pj.chain.head || "")}</span></dd>
      ${Object.keys(so.overrides || {}).length ? `<dt>Overrides</dt><dd>${Object.entries(so.overrides).map(([k2, v]) => `<b>${esc(k2)}</b>: ${esc(v)}`).join("<br>")}</dd>` : ""}</dl></div>` },
      { id: "ledger", title: "Full record of every action", help: "Every action ever taken on this study, in a tamper-evident chain.", html: provTable(true) }] };
  }
  const fails = (R?.checks || []).filter((c) => c.status === "fail");
  return { title: "Investigator sign-off", lede: "The AI drafted and ran the study; you make the final decision. Signing links your name to this exact plan and these exact results.",
    parts: [
      { id: "human", title: "What you are responsible for", help: "Read what stays under human control before you sign.",
        html: `<div class="card"><h3 class="sub" style="margin-top:0">What stays under human supervision</h3><ul class="small" style="padding-left:18px;margin:0">
    <li><b>Question framing</b> - the AI proposes; the investigator decides what is clinically meaningful.</li>
    <li><b>Case definitions</b> - guideline thresholds and every operational assumption require explicit acknowledgement; AI-proposed definitions cannot run until approved.</li>
    <li><b>Confounder selection</b> - agents flag mediators and definitional overlap; causal structure is the investigator's call.</li>
    <li><b>Approval gate</b> - nothing executes without approval of the exact plan hash; any edit invalidates approval.</li>
    <li><b>QC failures</b> - cannot be silently ignored; each needs a documented override.</li>
    <li><b>Interpretation & publication</b> - narrative is drafted from aggregate results only, filtered for causal language, and signed by a human.</li>
    <li><b>Data governance</b> - restricted data use only approved/local models; row-level data never reach an LLM.</li></ul></div>` },
      { id: "ledger", title: "Full record of every action", help: "Every action taken on this study so far, in a tamper-evident chain. You can skim this.", html: provTable(true) },
      { id: "sign", title: "Sign off", help: "Tick each box you agree with, explain any failed check, type your name and sign.",
        html: `<div class="card">${ATTEST.map((a, i) => `<label class="row small" style="align-items:flex-start;margin-bottom:8px"><input type="checkbox" class="att" data-i="${i}"> ${esc(a)}</label>`).join("")}
    ${fails.map((c) => `<label class="field" style="margin-top:8px">Override reason for failed check: ${esc(c.title)}<textarea class="ovr" data-id="${esc(c.id)}" rows="2"></textarea></label>`).join("")}
    <div class="row" style="margin-top:12px"><input type="text" id="signer" placeholder="Your name" value="${esc(store.get("q2e.name", ""))}"><button class="btn primary" data-act="sign">Sign off results</button></div></div>` },
    ] };
}
function provTable(noTitle) {
  const ev = S.project.events;
  return `${noTitle ? "" : `<h2 class="sec">Provenance ledger</h2>`}<div class="tablewrap"><table class="t"><thead><tr><th>#</th><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Plan</th><th>Hash</th></tr></thead><tbody>${ev.slice().reverse().map((e) => `<tr><td class="num">${e.seq}</td><td class="num">${esc(e.at.replace("T", " ").slice(0, 19))}</td><td>${esc(e.actor)}</td><td>${esc(e.action.replace(/_/g, " "))}<div class="tiny muted">${esc(JSON.stringify(e.detail).slice(0, 140))}</div></td><td class="hash">${esc(e.plan_hash.slice(0, 10))}</td><td class="hash">${esc(e.hash.slice(0, 10))}</td></tr>`).join("")}</tbody></table></div>`;
}

/* ------------------------------------------------------------------ actions */
async function createProject(q, extra, el) {
  el.disabled = true; el.innerHTML = `<span class="spinner"></span> Agents designing your study…`;
  try {
    const pj = await api("/api/projects", { method: "POST", body: { question: q, cycles: S.ask.cycles, source: S.ask.source, provider: $("#provSel").value || null, dataset_id: $("#dsSel").value || null, actor: store.get("q2e.name", "") || "investigator", ...(extra || {}) } });
    S.project = pj; S.clarify = null; S.rewrite = null; location.hash = `#/p/${pj.id}/protocol`;
  } catch (e) {
    toast(e.message, true); S.clarify = null;
    try { S.assess = await api("/api/assess", { method: "POST", body: { question: q, cycles: S.ask.cycles } }); } catch {}
    rerender();
  }
}
async function edit(fix, note, step, stepTitle) {
  try { S.project = await api(`/api/projects/${S.project.id}/edit`, { method: "POST", body: { fix, actor: store.get("q2e.name", "") || "investigator", note, step: step || null, step_title: stepTitle || null } }); rerender(); }
  catch (e) { toast(e.message, true); }
}
const A = {
  home: () => (location.hash = "#/"),
  go: (el) => el.dataset.stage && go(el.dataset.stage),
  example: (el) => { $("#q").value = el.dataset.q; store.set("q2e.q", el.dataset.q); },
  cycle: (el) => { const c = S.ask.cycles; const id = el.dataset.id; S.ask.cycles = c.includes(id) ? c.filter((x) => x !== id) : [...c, id]; rerender(); },
  cycleauto: () => { S.ask.cycles = []; rerender(); },
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
    store.set("q2e.q", q); el.disabled = true; el.innerHTML = `<span class="spinner"></span> Reading your idea…`;
    let c = null;
    try { c = await api("/api/clarify", { method: "POST", body: { question: q, cycles: S.ask.cycles } }); } catch {}
    S.rewrite = null;
    if (c && c.needs_rewrite) {
      S.rewrite = c.needs_rewrite; S.clarify = null;
      await rerender();
      $("#rewriteCard")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (c && c.questions.length) {
      S.clarify = { ...c, question: q, step: 0, answers: {} };
      return rerender();
    }
    // nothing to ask: still send (empty) answers so the server applies spelling fixes and records what it understood
    await createProject(q, c ? { answers: {}, level: c.level_used } : null, el);
  },
  level: async (el) => {
    try {
      const c = await api("/api/clarify", { method: "POST", body: { question: S.clarify.question, cycles: S.ask.cycles, level: el.value } });
      S.clarify = { ...c, question: S.clarify.question, step: 0, answers: S.clarify.answers }; rerender();
    } catch (e) { toast(e.message, true); }
  },
  cqClose: () => { S.clarify = null; rerender(); },
  rwClose: () => { S.rewrite = null; rerender(); },
  rwUse: async (el) => {
    store.set("q2e.q", el.dataset.q); S.rewrite = null; await rerender();
    const box = $("#q"); box.focus(); box.setSelectionRange(box.value.length, box.value.length);
    toast("Example added to the box. Edit it if you like, then press Design my study.");
  },
  rwSwap: async (el) => {
    const box = $("#q"); const miss = ((S.rewrite && S.rewrite.missing) || [])[0]; const use = el.dataset.use;
    const re = miss ? new RegExp(`\\b${miss.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i") : null;
    const swapped = re && re.test(box.value);
    const text = swapped ? box.value.replace(re, use) : `${box.value.trim()} ${use}`.trim();
    store.set("q2e.q", text); S.rewrite = null; await rerender();
    $("#q").focus();
    toast(swapped ? `Swapped "${miss}" for "${use}". Check your idea reads well, then press Design my study.`
                  : `Added "${use}" to your idea. Check it reads well, then press Design my study.`);
  },
  backToStudy: () => { S.clarify = null; go("protocol"); },
  backToAsk: async () => {
    // Reopen the follow-up questions with this study's earlier answers, on the last question
    const cl = S.project?.plan?.clarification; const idea = cl?.original_question || S.project?.question || "";
    store.set("q2e.q", idea); S.clarify = null;
    if (cl?.answers) {
      try {
        const c = await api("/api/clarify", { method: "POST", body: { question: idea, cycles: S.ask.cycles, level: cl.level_used } });
        if (c.questions.length) S.clarify = { ...c, question: idea, step: c.questions.length - 1, answers: { ...cl.answers }, fromProject: true };
      } catch (e) { toast(e.message, true); }
    }
    location.hash = "#/";
  },
  cqBack: () => { if (S.clarify.step > 0) { S.clarify.step--; rerender(); } },
  cqNext: () => { const c = S.clarify; const q = c.questions[c.step]; if (answered(q, c.answers[q.id] || {})) { c.step++; rerender(); } },
  clarifyGo: (el) => $("#q").value.trim() !== S.clarify.question ? A.design(el) : createProject(S.clarify.question, { answers: S.clarify.answers, level: S.clarify.level_used }, el),
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
  sub: (el) => {
    const key = stepKey(route().stage); const i = parseInt(el.dataset.i, 10) || 0;
    S.sub[key] = i; S.reach[key] = Math.max(S.reach[key] || 0, i); saveSteps(); render();
  },
  histToggle: () => { S.histOpen = !S.histOpen; rerender(); },
  ptOpen: (el) => { S.openPt = el.dataset.pt; rerender().then(() => { const i = $("#pcInput"); if (i) i.focus(); }); },
  ptClose: () => { S.openPt = null; rerender(); },
  ptFix: (el) => {
    const i = (S.project.plan.review || []).find((x) => x.id === el.dataset.id); if (!i || !i.fix) return;
    edit({ ...i.fix, by: store.get("q2e.name", "") || "investigator" }, `fix: ${i.title}`, el.dataset.pt, el.dataset.ptitle);
  },
  pcSend: async (el) => {
    const inp = $("#pcInput"); const msg = (el.dataset.msg || (inp && inp.value) || "").trim();
    if (msg.length < 2) return toast("Type what you want to change first", true);
    const pt = el.dataset.pt || (inp && inp.dataset.pt) || ""; const ptitle = el.dataset.ptitle || (inp && inp.dataset.ptitle) || "";
    const btn = $("#pcBtn"); if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Working…`; }
    try {
      S.project = await api(`/api/projects/${S.project.id}/protocol-chat`, { method: "POST", body: { message: msg, actor: store.get("q2e.name", "") || "analyst", step: pt || null, step_title: ptitle || null } });
      S.openPt = null; await rerender();
    } catch (e) { toast(e.message, true); if (btn) { btn.disabled = false; btn.textContent = "Ask the AI to change it"; } }
  },
  comment: async (el) => {
    const inp = $("#pcInput"); const msg = ((inp && inp.value) || "").trim();
    if (msg.length < 2) return toast("Type your comment first", true);
    const pt = (el && el.dataset && el.dataset.pt) || (inp && inp.dataset.pt) || ""; const ptitle = (el && el.dataset && el.dataset.ptitle) || (inp && inp.dataset.ptitle) || "";
    try {
      S.project = await api(`/api/projects/${S.project.id}/comments`, { method: "POST", body: { message: msg, actor: store.get("q2e.name", "") || "analyst", step: pt || null, step_title: ptitle || null } });
      S.openPt = null; toast("Comment saved with today's date and time"); await rerender();
    } catch (e) { toast(e.message, true); }
  },
  amUndo: async (el) => {
    try { S.project = await api(`/api/projects/${S.project.id}/amendments/${el.dataset.id}/undo`, { method: "POST", body: { actor: store.get("q2e.name", "") || "analyst" } }); toast("Change undone"); rerender(); }
    catch (e) { toast(e.message, true); }
  },
  amReason: async (el) => {
    const why = prompt("Why did you make this change? (optional - helps the lead investigator)"); if (!why || !why.trim()) return;
    try { S.project = await api(`/api/projects/${S.project.id}/amendments/${el.dataset.id}/reason`, { method: "POST", body: { reason: why.trim(), actor: store.get("q2e.name", "") || "analyst" } }); rerender(); }
    catch (e) { toast(e.message, true); }
  },
  amCopy: async () => {
    try { await navigator.clipboard.writeText(weeklySummary()); toast("Weekly summary copied - paste it into an email or report"); }
    catch (e) { prompt("Copy this summary:", weeklySummary()); }
  },
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
  teach: async (el) => {
    const v = el.dataset.var; const term = prompt(`Which words should Q2E read as ${v} in future questions?`, ($("#dictQ").value || "").trim());
    if (!term) return;
    const by = store.get("q2e.name", "") || prompt("Your name (recorded with the mapping)") || "";
    if (!by) return toast("A name is required", true);
    try { const r = await api("/api/learn", { method: "POST", body: { term, target: "var:" + v, by } }); toast(`Learned: "${r.saved.term}" -> ${v}. Ask the question again to use it.`); } catch (e) { toast(e.message, true); }
  },
  dict: async () => { const q = $("#dictQ").value.trim(); if (!q) return; S.dict = await api("/api/dictionary/match", { method: "POST", body: { query: q, dataset_id: S.project.plan.dataset.dataset_id || null } }); rerender(); },
  approve: async () => {
    const by = $("#approver").value.trim(); if (!by) return toast("Enter your name", true); if (!$("#attest").checked) return toast("Confirm you reviewed the plan", true);
    store.set("q2e.name", by);
    try { S.project = await api(`/api/projects/${S.project.id}/approve`, { method: "POST", body: { by } }); toast("Protocol approved and locked by hash"); rerender(); } catch (e) { toast(e.message, true); }
  },
  armset: (el) => edit({ op: "set_arms", [el.dataset.k]: el.dataset.v }, "Comparison groups changed"),
  statsign: async () => {
    const by = $("#statname").value.trim(); if (!by) return toast("Enter the statistician's name", true);
    try { S.project = await api(`/api/projects/${S.project.id}/approve`, { method: "POST", body: { by, role: "statistician", statement: "I reviewed the design, comparator, outcome definitions and statistical analysis plan." } }); toast("Statistical sign-off recorded"); rerender(); } catch (e) { toast(e.message, true); }
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
  novelty: async () => { toast("Searching PubMed/MEDLINE for prior NHANES work..."); S.project.novelty = await api(`/api/projects/${S.project.id}/novelty`, { method: "POST" }); rerender(); },
  where: async () => { toast("Searching PubMed, NIH RePORTER and Grants.gov..."); S.where = await api(`/api/projects/${S.project.id}/where-next`); rerender(); },
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
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && e.target.id === "pcInput") {
    e.preventDefault();
    if ($("#pcBtn")) A.pcSend(e.target); else A.comment(e.target);
  }
});
document.addEventListener("change", (e) => {
  const el = e.target; const act = el.dataset?.act; if (!act) return;
  if (act === "level") A.level(el);
  else if (act === "cqopt") { const q = S.clarify.questions[S.clarify.step]; S.clarify.answers[q.id] = { ...(S.clarify.answers[q.id] || {}), option: el.value }; refreshNext(); }
  else if (act === "setdef") edit({ op: "set_definition", role: el.dataset.role, value: el.value });
  else if (act === "scale") edit({ op: "set", path: "exposure.scale", value: parseFloat(el.value) || 1 });
  else if (act === "crit") edit({ op: "enable_criterion", id: el.dataset.id, value: el.checked });
  else if (act === "sens") edit({ op: "enable_sensitivity", id: el.dataset.id, value: el.checked });
  else if (act === "family") edit({ op: "set", path: "model.family", value: el.value });
  else if (act === "addpill" && el.value) { const f = el.dataset.field; edit({ op: `set_${f}`, value: [...S.project.plan[f], el.value] }); }
});
document.addEventListener("input", (e) => {
  if (e.target.id?.startsWith("cqt_") && S.clarify) { const id = e.target.id.slice(4); S.clarify.answers[id] = { ...(S.clarify.answers[id] || {}), text: e.target.value }; refreshNext(); }
  if (e.target.id === "q") store.set("q2e.q", e.target.value); if (e.target.id === "dsSel") S.ask.dataset = e.target.value; if (e.target.id === "provSel") S.ask.provider = e.target.value; });
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark"; store.set("q2e.theme", document.documentElement.dataset.theme);
});
(async function init() {
  const t = store.get("q2e.theme", ""); if (t) document.documentElement.dataset.theme = t;
  try { S.meta = await api("/api/meta"); } catch (e) { $("#main").innerHTML = `<div class="banner bad">Cannot reach the Q2E server: ${esc(e.message)}</div>`; return; }
  renderBoundary(); render();
})();
