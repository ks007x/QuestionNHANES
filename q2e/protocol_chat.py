"""Protocol agent: back-and-forth between the analyst and the AI on the research protocol.

The analyst writes what they want in plain words ("only adults over 40", "report odds ratios",
"don't adjust for income", "use 2015-2018"). The agent applies the change right away (no
"are you sure?" step - there is an Undo), explains exactly what changed, and records it in an
amendment history with a timestamp so the lead investigator can follow every change without
emails or meetings. It only asks a question when a request cannot be grounded in Q2E's
knowledge base / the NHANES catalog - it never guesses.

Everything is rule-based (no LLM), so nothing is invented: changes are made with the same
planner operations and parser the rest of Q2E uses.
"""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from . import agents, expertise, planner
from .knowledge import Knowledge, get_knowledge

FAMILY_NAMES = {"quasipoisson": "prevalence ratio", "quasibinomial": "odds ratio", "gaussian": "mean difference"}
# Plan keys that are history, not design: carried over when the plan is rebuilt from a text request
KEEP_KEYS = ("clarification", "approvals", "acknowledgements", "privacy")


# ---------------------------------------------------------------------------
# What changed? (plain-language diff between two plan versions)
# ---------------------------------------------------------------------------
def _role(plan: dict, role: str, k: Knowledge) -> str:
    v = plan.get(role) or {}
    if not v:
        return "none"
    label = v.get("concept_label") or v.get("label") or v.get("variable", "")
    d = v.get("variable")
    if d in k.definitions:
        label += f" ({k.definitions[d].get('short') or k.definitions[d].get('label')})"
    return label


def _cycles(plan: dict, k: Knowledge) -> str:
    cs = (plan.get("dataset") or {}).get("cycles") or []
    return ", ".join(k.cycles[c]["label"].replace("NHANES ", "") if c in k.cycles else c for c in cs) or "automatic"


def diff_plans(old: dict, new: dict, k: Knowledge | None = None) -> list[dict]:
    """[{what, before, after}] for the parts of the protocol a reader cares about."""
    k = k or get_knowledge()
    out = []

    def add(what: str, a: Any, b: Any):
        if a != b:
            out.append({"what": what, "before": a if a not in ("", None) else "none", "after": b if b not in ("", None) else "none"})

    add("Outcome", _role(old, "outcome", k), _role(new, "outcome", k))
    add("Exposure", _role(old, "exposure", k), _role(new, "exposure", k))
    pop_o = {c["label"] for c in old.get("population", []) if c.get("enabled")}
    pop_n = {c["label"] for c in new.get("population", []) if c.get("enabled")}
    for lab in sorted(pop_n - pop_o):
        out.append({"what": "Population", "before": "-", "after": f"added: {lab}"})
    for lab in sorted(pop_o - pop_n):
        out.append({"what": "Population", "before": f"removed: {lab}", "after": "-"})
    cov_o, cov_n = set(old.get("covariates") or []), set(new.get("covariates") or [])
    for c in sorted(cov_n - cov_o):
        out.append({"what": "Adjusted for", "before": "-", "after": f"added: {k.label(c)}"})
    for c in sorted(cov_o - cov_n):
        out.append({"what": "Adjusted for", "before": f"removed: {k.label(c)}", "after": "-"})
    add("Survey years", _cycles(old, k), _cycles(new, k))
    fo, fn = (old.get("model") or {}).get("family"), (new.get("model") or {}).get("family")
    add("Effect measure", FAMILY_NAMES.get(fo, fo), FAMILY_NAMES.get(fn, fn))
    add("Title", old.get("title"), new.get("title"))
    return out


def summary_lines(changes: list[dict]) -> list[str]:
    lines = []
    for c in changes:
        if c["before"] == "-":
            lines.append(f"{c['what']}: {c['after']}")
        elif c["after"] == "-":
            lines.append(f"{c['what']}: {c['before']}")
        else:
            lines.append(f"{c['what']}: {c['before']} → {c['after']}")
    return lines


# ---------------------------------------------------------------------------
# Turning a request into a change
# ---------------------------------------------------------------------------
def _cycle_codes(text: str, k: Knowledge) -> list[str]:
    """Survey cycles named by years in the text ('2015-2018', '2017-2018 and 2021-2023'), limited to cycles Q2E has."""
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d\d\b", text)]
    if not years:
        return []
    lo, hi = min(years), max(years)
    codes = [c for c, (a, b) in expertise.CYCLE_YEARS.items() if c in k.cycles and a >= lo and b <= max(hi, lo + 1)]
    if "P" in codes and ("J" in codes or "I" in codes):     # 2017-March 2020 overlaps 2017-2018; keep the separate cycles
        codes.remove("P")
    return codes


def _block_for(text: str, k: Knowledge) -> str | None:
    """A building block (adjustable variable) Q2E knows for a word like 'smoking' or 'income'; None if unknown."""
    t = text.lower().strip()
    if not t:
        return None
    if t.replace(" ", "_") in k.blocks:
        return t.replace(" ", "_")
    for c in k.concepts.values():
        if t in [s.lower() for s in c.get("synonyms", [])] + [c["label"].lower()] and c.get("block") in k.blocks:
            return c["block"]
    for cid in expertise.LAY_TERMS.get(t, []):
        if k.concepts.get(cid, {}).get("block") in k.blocks:
            return k.concepts[cid]["block"]
    for name, b in k.blocks.items():
        if t == str(b.get("label", "")).lower():
            return name
    return None


AGE_WORDS = [(r"\b(?:over|older than|above)\s+(\d{1,2})(?!\s*(?:years|y\b|yrs))", r"aged \1 and older"),
             (r"\b(\d{1,2})\s*\+", r"aged \1 and older"),
             (r"\b(?:under|younger than|below)\s+(\d{1,2})(?!\s*(?:years|y\b|yrs))", r"under \1 years"),
             (r"\bbetween\s+(\d{1,2})\s+and\s+(\d{1,2})\b", r"aged \1 to \2")]


def _normalise(text: str) -> str:
    """Everyday age wording -> the forms the question parser reads ('over 40' -> 'aged 40 and older')."""
    for pat, rep in AGE_WORDS:
        text = re.sub(pat, rep, text, flags=re.I)
    return text


def _direct_ops(msg: str, plan: dict, k: Knowledge) -> list[dict]:
    """Requests that map to one planner operation without re-reading the question."""
    m = msg.lower()
    ops: list[dict] = []
    if re.search(r"\bodds ratios?\b|\blogistic\b", m) and not re.search(r"\b(?:not|no|instead of) (?:odds|logistic)", m):
        ops.append({"op": "set", "path": "model.family", "value": "quasibinomial"})
    elif re.search(r"\bprevalence ratios?\b|\bpoisson\b", m):
        ops.append({"op": "set", "path": "model.family", "value": "quasipoisson"})
    if re.search(r"\b(?:swap|switch|reverse|flip)\b.*\b(?:exposure|outcome|roles?|direction|around)\b|\bother way (?:a)?round\b", m):
        ops.append({"op": "swap_roles"})
    rm = re.search(r"\b(?:don'?t|do not|stop|no longer|without)\s+(?:adjust(?:ing)?|control(?:ling)?)\s+(?:for\s+)?(.+)|"
                   r"\bremove\s+(?:the\s+)?(?:covariate\s+)?(.+?)\s+(?:from the|as a)\s+(?:covariates?|adjustment)", m)
    if rm:
        target = (rm.group(1) or rm.group(2) or "").strip(" .")
        for c in plan.get("covariates") or []:
            lab = k.label(c).lower()
            if c.lower() in target or any(w in target for w in re.findall(r"[a-z]{3,}", lab)):
                ops.append({"op": "remove_covariate", "name": c})
    else:
        add = re.search(r"\b(?:adjust(?:ing)?|control(?:ling)?)\s+(?:also\s+)?for\s+(.+)|\badd\s+(.+?)\s+(?:as an?\s+)?(?:covariates?|adjustments?)\b", m)
        if add:
            for piece in re.split(r",|\band\b|\bplus\b", (add.group(1) or add.group(2) or "").strip(" .")):
                b = _block_for(piece.strip(), k)
                if b and b not in (plan.get("covariates") or []):
                    ops.append({"op": "add_covariate", "name": b})
    cyc = _cycle_codes(m, k) if re.search(r"\b(?:cycles?|years?|data from|use|only)\b", m) else []
    if cyc and cyc != (plan.get("dataset") or {}).get("cycles"):
        ops.append({"op": "set_cycles", "value": cyc})
    return ops


def _rebuild(proj: dict, extra_requests: list[str]) -> dict:
    """Re-read the study question plus the analyst's text requests, then re-apply earlier answers and edits."""
    plan = proj["plan"]
    question = " ".join([proj["question"]] + extra_requests)
    ds = plan.get("dataset") or {}
    new = agents.design_study(question, ds.get("cycles"), ds if ds.get("type") == "generic" else
                              {"type": "nhanes", "cycles": ds.get("cycles"), "source": ds.get("source", "auto")})
    clar = plan.get("clarification") or {}
    if clar.get("answers"):
        try:
            fixes = expertise.apply_answers(clar.get("original_question") or proj["question"], clar["answers"],
                                            clar.get("level_used"), ds.get("cycles"),
                                            use_ai=any(a.startswith("ai") for a in clar["answers"]))["fixes"]
            new = expertise.apply_fixes(new, fixes)
        except Exception:  # noqa: BLE001 - an old answer may no longer apply to the new design
            pass
    # earlier changes that still stand (manual edits on the protocol pages and direct requests), best effort
    for am in proj.get("amendments", []):
        if am.get("undone"):
            continue
        for fix in am.get("ops") or am.get("edit_ops") or []:
            if fix and fix.get("op") != "swap_roles":
                try:
                    new = planner.apply_fix(new, fix)
                except Exception:  # noqa: BLE001
                    pass
    for key in KEEP_KEYS:
        if key in plan:
            new[key] = copy.deepcopy(plan[key])
    new["plan_id"] = plan.get("plan_id", new.get("plan_id"))
    return new


def respond(proj: dict, message: str) -> dict:
    """Decide what the analyst's request changes. Returns {reply, new_plan|None, changes, ops, text_request, ask}."""
    k = get_knowledge()
    plan = proj["plan"]
    msg = message.strip()
    ops = _direct_ops(msg, plan, k)
    text_request = None
    new_plan = None
    if ops:
        new_plan = copy.deepcopy(plan)
        todo = [o for o in ops if o["op"] != "swap_roles"]
        if len(todo) < len(ops):
            new_plan = planner.apply_fix(new_plan, {"op": "swap_roles"}, k)
            # swapping re-designs the study, so earlier changes that still stand are put back
            todo = [f for am in proj.get("amendments", []) if not am.get("undone")
                    for f in (am.get("ops") or am.get("edit_ops") or []) if f and f.get("op") != "swap_roles"] + todo
        for op in todo:
            try:
                new_plan = planner.apply_fix(new_plan, op, k)
            except Exception:  # noqa: BLE001 - an earlier change may no longer fit the swapped design
                if op in ops:
                    raise
        for key in KEEP_KEYS:
            if key in plan:
                new_plan[key] = copy.deepcopy(plan[key])
        old_c = (plan.get("dataset") or {}).get("cycles") or []
        new_c = (new_plan.get("dataset") or {}).get("cycles") or []
        if old_c and new_c and old_c != new_c and new_plan.get("title"):
            new_plan["title"] = new_plan["title"].replace(planner._cycle_text(old_c, k), planner._cycle_text(new_c, k))
    elif META_REQUEST.search(msg):
        return {"reply": None, "new_plan": None, "changes": [], "ops": [], "text_request": None, "ask": _ask_close(proj, k)}
    elif _is_new_question(msg, plan, k):
        ds = plan.get("dataset") or {}
        try:
            new_plan = agents.design_study(msg, ds.get("cycles"), ds if ds.get("type") == "generic" else
                                           {"type": "nhanes", "cycles": ds.get("cycles"), "source": ds.get("source", "auto")})
        except (planner.HardStop, ValueError) as e:
            return {"reply": f"I can't switch to that question: {e}", "new_plan": None, "changes": [], "ops": [], "text_request": None, "ask": None}
        for key in KEEP_KEYS:
            if key in plan:
                new_plan[key] = copy.deepcopy(plan[key])
        new_plan["plan_id"] = plan.get("plan_id", new_plan.get("plan_id"))
        changes = [{"what": "Study question", "before": proj.get("question", ""), "after": msg}] + diff_plans(plan, new_plan, k)
        new_plan = agents.refresh_plan(new_plan)
        new_plan["status"] = "draft"
        return {"reply": "Done. I switched the study to this question:", "new_plan": new_plan, "changes": changes, "ops": [],
                "text_request": None, "ask": None, "new_question": msg}
    else:
        text_request = _normalise(msg if msg.endswith((".", "?", "!")) else msg + ".")
        try:
            new_plan = _rebuild(proj, proj.get("protocol_requests", []) + [text_request])
        except planner.HardStop as e:
            return {"reply": f"I can't make that change: {e}", "new_plan": None, "changes": [], "ops": [], "text_request": None, "ask": None}
        except ValueError:
            new_plan = None
    changes = diff_plans(plan, new_plan, k) if new_plan else []
    if not re.search(r"\btitle\b", msg.lower()) and all(c["what"] == "Title" for c in changes):
        changes = []          # only the auto-generated title moved: the request itself changed nothing
    if not changes:
        add = re.search(r"\b(?:adjust(?:ing)?|control(?:ling)?)\s+(?:also\s+)?for\s+(.+)", msg.lower())
        already = [b for b in (_block_for(p.strip(), k) for p in re.split(r",|\band\b|\bplus\b", add.group(1).strip(" ."))) if b] if add else []
        already = [b for b in already if b in (plan.get("covariates") or [])]
        if already:
            return {"reply": "The protocol already adjusts for " + ", ".join(k.label(b) for b in already) + ", so nothing needed to change.",
                    "new_plan": None, "changes": [], "ops": [], "text_request": None, "ask": None}
        return {"reply": None, "new_plan": None, "changes": [], "ops": [], "text_request": None, "ask": _ask(msg, k)}
    new_plan = agents.refresh_plan(new_plan)
    new_plan["status"] = "draft"
    reply = "Done. I changed the protocol:"
    if proj.get("approved_current") or any(a.get("stage", "protocol") == "protocol" for a in plan.get("approvals", [])):
        reply += " (the protocol was approved before, so it needs approval again before running)"
    return {"reply": reply, "new_plan": new_plan, "changes": changes, "ops": ops, "text_request": text_request, "ask": None}


META_REQUEST = re.compile(r"\b(?:something (?:close|similar|related|else)|close to it|closest|nearest|similar|alternatives?|"
                          r"what (?:can|does) nhanes|nhanes can (?:answer|do|measure|change)|that nhanes (?:has|can))\b", re.I)


def _is_new_question(msg: str, plan: dict, k: Knowledge) -> bool:
    """A whole research question (e.g. picked from the suggestions) rather than an edit to the current one."""
    m = msg.strip().lower()
    if not re.search(r"\?$|^(?:is|are|does|do|can|how|what)\b", m):
        return False
    p = planner.parse_question(msg, k)
    if not p.get("outcome_concept") or not p.get("exposure_concept"):
        return False
    cur = {(plan.get("outcome") or {}).get("concept"), (plan.get("exposure") or {}).get("concept")}
    return {p["outcome_concept"], p["exposure_concept"]} != cur


def _ask_close(proj: dict, k: Knowledge) -> dict:
    """'Relate it to something close that NHANES has': offer whole questions NHANES can answer."""
    alts = expertise.close_questions(proj.get("question", ""), k)
    if not alts:
        plan = proj["plan"]
        if plan.get("exposure") and plan.get("outcome"):
            return {"text": "Your study already uses topics NHANES measures, so there is nothing to swap. "
                            "Tell me what you'd like to change (for example a group of people or survey years).", "options": []}
        return {"text": "I couldn't find a close topic in NHANES for this question. Try naming the health measures you're interested in.",
                "options": []}
    return {"text": "NHANES can't answer your question exactly, but it can answer these close versions. "
                    "Click one to switch the study to it (you can undo).",
            "options": [{"label": a["question"], "hint": a["why"], "send": a["question"]} for a in alts]}


def _ask(msg: str, k: Knowledge) -> dict:
    """The request could not be turned into a change: say so, and offer the closest grounded wording."""
    parsed = planner.parse_question(msg, k)
    options = []
    for term in expertise.unclear_terms(parsed)[:2]:
        for s in expertise.term_suggestions(term, k)[:3]:
            options.append({"label": s["label"], "hint": s["hint"],
                            "send": re.sub(r"\b" + re.escape(term) + r"\b", s["replace"], msg, count=1, flags=re.I)})
    text = ("I couldn't turn that into a change to the protocol using what Q2E knows about NHANES, so I left the protocol as it was."
            + (" Did you mean one of these?" if options else
               " Try naming a health topic, a group of people (e.g. 'only adults over 40'), survey years (e.g. '2015-2018'), "
               "an adjustment (e.g. 'adjust for smoking') or an effect measure (e.g. 'report odds ratios')."))
    return {"text": text, "options": options}


def new_amendment(by: str, request: str, changes: list[dict], v_before: int | None, v_after: int | None,
                  ops: list[dict], text_request: str | None, at: str, source: str = "chat",
                  edit_ops: list[dict] | None = None, step: str | None = None, step_title: str | None = None) -> dict:
    """One entry in the protocol's amendment history.
    source: 'chat' (asked the Protocol agent), 'edit' (changed a field), 'undo', or 'comment' (a note, no change)."""
    return {"id": "am_" + uuid.uuid4().hex[:8], "at": at, "by": by, "source": source, "request": request,
            "step": step, "step_title": step_title,
            "changes": changes, "summary": summary_lines(changes), "reason": None, "version_before": v_before,
            "version_after": v_after, "ops": ops, "edit_ops": edit_ops or [], "text_request": text_request, "undone": False}
