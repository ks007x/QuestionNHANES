"""Sample size and power for survey-weighted NHANES analyses.

Before the run (protocol): uses the blinded probe's counts (n per group, outcome-rate band) and an assumed design
effect. After the run: uses the model's own design-based standard error, which already reflects weighting,
clustering and covariate adjustment - the most honest basis for a minimum detectable effect.

Binary outcome, two groups (reference p0, comparison p1 = RR*p0), log prevalence-ratio scale:
    SE(log RR) = sqrt(DEFF * [(1-p1)/(n1 p1) + (1-p0)/(n0 p0)])
    detectable when |log RR| >= (z_{1-a/2} + z_{power}) * SE
Continuous exposure, binary outcome:   SE(log PR per SD) ~ sqrt(DEFF / events)
Continuous outcome, two groups:        MDE (in SD units) = (z_a + z_b) * sqrt(DEFF * (1/n0 + 1/n1))
Continuous outcome, continuous exposure: MDE (standardized beta) = (z_a + z_b) * sqrt(DEFF / n)
Prevalence:                            95% CI half-width = z * sqrt(DEFF p(1-p)/n)
Multiple arms: alpha is optionally Bonferroni-split across the arm-vs-control comparisons.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

N = NormalDist()
DEFAULTS = {"alpha": 0.05, "power": 0.80, "target_ratio": 1.5, "target_sd": 0.2, "target_halfwidth": 0.02,
            "deff": 1.8, "multiplicity": "bonferroni", "p0_assumed": 0.10}


def settings_of(plan: dict) -> dict:
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (plan.get("power_settings") or {}).items() if k in DEFAULTS and v is not None})
    return s


def _z(alpha: float, power: float) -> tuple[float, float]:
    return N.inv_cdf(1 - alpha / 2), N.inv_cdf(power)


def _se_rr(p0: float, rr: float, n0: float, n1: float, deff: float) -> float:
    p1 = min(rr * p0, 0.999)
    return math.sqrt(deff * ((1 - p1) / (max(n1, 1) * p1) + (1 - p0) / (max(n0, 1) * p0)))


def mde_ratio(p0: float, n0: float, n1: float, deff: float, za: float, zb: float) -> float | None:
    """Smallest prevalence ratio > 1 detectable with the given power (bisection on log RR)."""
    if not (0 < p0 < 1) or n0 < 2 or n1 < 2:
        return None
    hi = min(1 / p0, 50.0)
    f = lambda rr: math.log(rr) - (za + zb) * _se_rr(p0, rr, n0, n1, deff)
    if f(hi) < 0:
        return None          # even the largest possible ratio is not detectable
    lo = 1.0000001
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return hi


def required_n0(p0: float, rr: float, ratio: float, deff: float, za: float, zb: float) -> float | None:
    """Reference-group size needed (comparison group = ratio * n0) to detect `rr`."""
    p1 = rr * p0
    if not (0 < p0 < 1) or not (0 < p1 < 1) or rr == 1:
        return None
    return deff * (za + zb) ** 2 * ((1 - p1) / (ratio * p1) + (1 - p0) / p0) / math.log(rr) ** 2


def power_at(p0: float, rr: float, n0: float, n1: float, deff: float, za: float) -> float | None:
    if not (0 < p0 < 1) or rr * p0 >= 1:
        return None
    return N.cdf(abs(math.log(rr)) / _se_rr(p0, rr, n0, n1, deff) - za)


def _band_mid(b) -> float | None:
    return (b[0] + b[1]) / 2 if b and len(b) == 2 and b[1] > 0 else None


def assess(plan: dict, probe: dict | None = None, results: dict | None = None) -> dict[str, Any]:
    s = settings_of(plan)
    y = plan["outcome"]
    x = plan.get("exposure")
    arms = plan.get("arms")
    probe = probe if probe and not probe.get("stale") else None
    out: dict[str, Any] = {"settings": s, "assumptions": [], "comparisons": [], "basis": "probe" if probe else "assumed",
                           "outcome_type": y["type"]}
    n_cc = (probe or {}).get("n_complete_case")
    p0 = _band_mid(((probe or {}).get("outcome") or {}).get("rate_band"))
    if p0 is None and y["type"] == "binary":
        p0 = s["p0_assumed"]
        out["assumptions"].append(f"Outcome prevalence assumed {100 * p0:.0f}% (run the blinded probe for the real rate band).")
    elif p0 is not None:
        out["assumptions"].append(f"Outcome prevalence {100 * p0:.1f}% (mid-point of the blinded probe's 5-point band).")
    out["assumptions"].append(f"Design effect {s['deff']} (typical for NHANES; the post-run check uses the actual design-based SE).")

    # ---------------- prevalence study ----------------
    if not x:
        n = n_cc or (probe or {}).get("n_analytic")
        if n and p0:
            hw = 1.96 * math.sqrt(s["deff"] * p0 * (1 - p0) / n)
            need = math.ceil(s["deff"] * 1.96 ** 2 * p0 * (1 - p0) / s["target_halfwidth"] ** 2)
            out["comparisons"].append({"label": "Overall prevalence", "n": n, "halfwidth_pts": round(100 * hw, 2),
                                       "target_halfwidth_pts": 100 * s["target_halfwidth"], "required_n": need,
                                       "status": "ok" if n >= need else "caution"})
        out["verdict"] = _verdict(out["comparisons"])
        return _post_run(out, plan, results, s)

    # ---------------- groups (binary or multi-arm exposure) ----------------
    groups = None
    e = (probe or {}).get("exposure") or {}
    if e.get("type") == "categorical" and e.get("levels"):
        groups = {lv["level"]: lv["n"] for lv in e["levels"]}
    ref = (arms or {}).get("reference") if arms else None
    if groups and ref is None:
        ref = "No" if "No" in groups else max(groups, key=groups.get)
    k_cmp = max(len(groups) - 1, 1) if groups else (len(arms["levels"]) - 1 if arms else 1)
    alpha = s["alpha"] / k_cmp if (s["multiplicity"] == "bonferroni" and k_cmp > 1) else s["alpha"]
    if alpha != s["alpha"]:
        out["assumptions"].append(f"Alpha {s['alpha']} split across {k_cmp} comparisons with the control group (Bonferroni: {alpha:.4f}).")
    za, zb = _z(alpha, s["power"])

    if y["type"] == "binary" and (groups or x["type"] in ("binary", "categorical")):
        if groups and ref in groups:
            n0 = groups[ref]
            for lvl, n1 in groups.items():
                if lvl == ref:
                    continue
                out["comparisons"].append(_binary_cmp(f"{lvl} vs {ref}", p0, n0, n1, s, za, zb))
        else:
            out["assumptions"].append("Group sizes unknown before the probe - showing the total sample needed for equal groups.")
            n0r = required_n0(p0, s["target_ratio"], 1.0, s["deff"], za, zb)
            out["comparisons"].append({"label": f"Two equal groups, PR {s['target_ratio']}", "required_n_total": math.ceil(2 * n0r) if n0r else None,
                                       "status": "unknown"})
    elif y["type"] == "binary":
        events = (n_cc or 0) * (p0 or 0)
        if events:
            mde = math.exp((za + zb) * math.sqrt(s["deff"] / events))
            need_events = s["deff"] * (za + zb) ** 2 / math.log(s["target_ratio"]) ** 2
            out["comparisons"].append({"label": "Per 1 SD of exposure", "events": round(events), "mde": round(mde, 3),
                                       "target": s["target_ratio"], "required_n_total": math.ceil(need_events / p0),
                                       "power_at_target": round(N.cdf(math.log(s["target_ratio"]) / math.sqrt(s["deff"] / events) - za), 3),
                                       "status": "ok" if mde <= s["target_ratio"] else "underpowered"})
    else:   # continuous outcome
        if groups and ref in groups:
            n0 = groups[ref]
            for lvl, n1 in groups.items():
                if lvl == ref:
                    continue
                mde = (za + zb) * math.sqrt(s["deff"] * (1 / max(n0, 1) + 1 / max(n1, 1)))
                out["comparisons"].append({"label": f"{lvl} vs {ref}", "n0": n0, "n1": n1, "mde_sd": round(mde, 3), "target_sd": s["target_sd"],
                                           "status": "ok" if mde <= s["target_sd"] else "underpowered"})
        elif n_cc:
            mde = (za + zb) * math.sqrt(s["deff"] / n_cc)
            need = math.ceil(s["deff"] * (za + zb) ** 2 / s["target_sd"] ** 2)
            out["comparisons"].append({"label": "Per 1 SD of exposure (standardized)", "n": n_cc, "mde_sd": round(mde, 3),
                                       "target_sd": s["target_sd"], "required_n_total": need,
                                       "status": "ok" if mde <= s["target_sd"] else "underpowered"})
    out["verdict"] = _verdict(out["comparisons"])
    return _post_run(out, plan, results, s)


def _binary_cmp(label, p0, n0, n1, s, za, zb) -> dict:
    mde = mde_ratio(p0, n0, n1, s["deff"], za, zb)
    ratio = n1 / max(n0, 1)
    need0 = required_n0(p0, s["target_ratio"], ratio, s["deff"], za, zb)
    pw = power_at(p0, s["target_ratio"], n0, n1, s["deff"], za)
    return {"label": label, "n0": n0, "n1": n1, "p0": round(p0, 4), "mde": round(mde, 3) if mde else None,
            "target": s["target_ratio"], "power_at_target": round(pw, 3) if pw is not None else None,
            "required_n_total": math.ceil(need0 * (1 + ratio)) if need0 else None,
            "status": "ok" if (mde and mde <= s["target_ratio"]) else "underpowered"}


def _verdict(cmps: list[dict]) -> str:
    st = [c.get("status") for c in cmps]
    if not st or all(x == "unknown" for x in st):
        return "Run the blinded probe to estimate power"
    if all(x == "ok" for x in st):
        return "Adequately powered for the target effect"
    if any(x == "ok" for x in st):
        return "Powered for some comparisons, not all"
    return "Underpowered for the target effect"


def _post_run(out: dict, plan: dict, results: dict | None, s: dict) -> dict:
    """After the run: minimum detectable effect from the model's own design-based SE."""
    if not results:
        return out
    za, zb = _z(s["alpha"], s["power"])
    rows = []
    arms = (results.get("arms") or {}).get("vs_reference") or []
    pe = results.get("primary_estimate") or {}
    cands = [(r["comparison"] + " vs " + r["versus"], r) for r in arms] or ([(pe.get("label", "Primary"), pe)] if pe.get("est") is not None else [])
    for lab, r in cands:
        est, lcl, ucl = r.get("est"), r.get("lcl"), r.get("ucl")
        if None in (est, lcl, ucl):
            continue
        ratio = (pe.get("effect") or (results.get("arms") or {}).get("effect")) in ("PR", "OR", "RR")
        if ratio and lcl > 0:
            se = (math.log(ucl) - math.log(lcl)) / (2 * 1.96)
            mde = math.exp((za + zb) * se)
            pw = N.cdf(math.log(s["target_ratio"]) / se - za)
            rows.append({"label": lab, "estimate": round(est, 3), "se_log": round(se, 4), "mde": round(mde, 3),
                         "power_at_target": round(pw, 3), "target": s["target_ratio"],
                         "ci_excludes_null": lcl > 1 or ucl < 1})
        elif not ratio:
            se = (ucl - lcl) / (2 * 1.96)
            rows.append({"label": lab, "estimate": round(est, 4), "se": round(se, 4), "mde": round((za + zb) * se, 4),
                         "ci_excludes_null": lcl > 0 or ucl < 0})
    out["post_run"] = rows
    cont = [r for r in rows if r.get("se") is not None and r.get("target") is None]
    if cont and out.get("verdict", "").startswith("Run the blinded probe"):
        out["verdict"] = "Minimum detectable difference estimated from the run's design-based standard errors"
    if rows and out.get("verdict", "").startswith("Run the blinded probe"):
        st = ["ok" if r.get("mde") is not None and r.get("target") and r["mde"] <= r["target"] else "underpowered" for r in rows if r.get("target")]
        if st:
            out["verdict"] = _verdict([{"status": x} for x in st]) + " (from the run's design-based standard errors)"
    return out


def summary_text(a: dict) -> str:
    s = a["settings"]
    tgt = f"target {s['target_sd']} SD" if a.get("outcome_type") == "continuous" else f"target PR {s['target_ratio']}"
    head = f"Alpha {s['alpha']} (two-sided), power {int(100 * s['power'])}%, {tgt}, DEFF {s['deff']}: {a['verdict']}."
    bits = []
    for c in a["comparisons"][:6]:
        if c.get("mde"):
            bits.append(f"{c['label']}: detectable PR {c['mde']:.2f}" + (f", power {100 * c['power_at_target']:.0f}% at PR {c['target']}" if c.get("power_at_target") is not None else ""))
        elif c.get("halfwidth_pts") is not None:
            bits.append(f"{c['label']}: 95% CI +/-{c['halfwidth_pts']:.1f} points")
        elif c.get("mde_sd"):
            bits.append(f"{c['label']}: detectable difference {c['mde_sd']:.2f} SD")
    post = [f"{r['label']}: minimum detectable PR {r['mde']:.2f}" if r.get("target") else f"{r['label']}: minimum detectable difference {r['mde']:g} (outcome units)"
            for r in a.get("post_run", []) if r.get("mde") is not None]
    txt = head + (" " + "; ".join(bits) + "." if bits else "")
    return txt + (" After the run: " + "; ".join(post[:6]) + "." if post else "")
