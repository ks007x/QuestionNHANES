"""AI interviewer: an LLM suggests extra follow-up questions about the idea, grounded in the NHANES catalog.

The LLM only writes the question and why it matters, and picks choices from Q2E's own catalog (topics, groups of
people, age ranges). Every choice is turned into wording by Q2E and kept only if the rule-based parser reads it back
as intended, so the AI cannot offer something NHANES does not have. Results are cached so the same idea always gets
the same questions (answers are matched to them later).
"""
from __future__ import annotations

from typing import Any

from . import planner
from .knowledge import Knowledge
from .llm import LLMClient, LLMError
from .language_guard import scan_causal

MAX_AI_QUESTIONS = 2
_CACHE: dict[tuple, list[dict]] = {}

SYSTEM = ("You are the Interviewer agent of Q2E, a tool that turns a research idea into an NHANES study. You help a "
          "researcher make their idea specific before the study is designed. You never invent data: every answer choice "
          "you offer must come from the catalog you are given. Reply with JSON only.")


def _catalog(k: Knowledge) -> str:
    topics = "\n".join(f"  {cid}: {c['label']}" for cid, c in sorted(k.concepts.items()))
    groups = "\n".join(f"  {p['id']}: {(p.get('patterns') or [p['id']])[0]}" for p in k.populations)
    return f"TOPICS NHANES MEASURES (id: name):\n{topics}\n\nGROUPS OF PEOPLE (id: name):\n{groups}"


def _prompt(question: str, understood: list[dict], asked: list[dict], k: Knowledge) -> str:
    read = "\n".join(f"  - {u['label']}: {u['value']}" for u in understood) or "  - nothing yet"
    already = "\n".join(f"  - {q['text']}" for q in asked) or "  - none"
    return (f"{_catalog(k)}\n\nRESEARCH IDEA: \"{question}\"\n\nWHAT Q2E ALREADY READ FROM IT:\n{read}\n\n"
            f"QUESTIONS Q2E IS ALREADY ASKING:\n{already}\n\n"
            f"Is anything else in the idea still vague, so a study designer would have to guess? Examples: which measure of "
            f"a topic is meant, which group of people, which ages, whether to compare by a subgroup. Ask about it. "
            f"Do not repeat the questions above or ask about what was already read. If nothing is vague, return no questions.\n\n"
            f"Return JSON {{\"questions\": [at most {MAX_AI_QUESTIONS} of {{\"text\": short plain-language question, "
            f"\"why\": one sentence on why it matters for this idea, \"options\": 2 to 4 choices, each ONE of "
            f"{{\"outcome\": topic id}}, {{\"exposure\": topic id}}, {{\"subgroup\": topic id}}, {{\"group\": group id}}, "
            f"{{\"age_from\": number, \"age_to\": number or null}}}}]}}. Use only ids from the lists above.")


def _option(raw: dict, i: int, question: str, k: Knowledge) -> dict | None:
    """Turn one AI choice into a Q2E option; None when it is not in the catalog or the parser does not read it back."""
    base = question.rstrip()
    if base and base[-1] not in ".?!":
        base += "."
    groups = {p["id"]: p for p in k.populations}
    for role in ("outcome", "exposure"):
        cid = raw.get(role)
        if cid is not None:
            if cid not in k.concepts:
                return None
            c = k.concepts[cid]
            return {"id": f"ai{i}", "label": c["label"], "hint": f"Use {c['label'].lower()} as the "
                    f"{'health topic' if role == 'outcome' else 'factor to compare'}.",
                    "fixes": [{"op": f"set_{role}", "concept": cid}]}
    if raw.get("subgroup") is not None:
        cid = raw["subgroup"]
        if cid not in k.concepts:
            return None
        add = f" Look at it separately by {k.concepts[cid]['synonyms'][0]}."
        if cid not in (planner.parse_question(base + add, k).get("subgroup_concepts") or []):
            return None
        return {"id": f"ai{i}", "label": f"Compare by {k.concepts[cid]['label'].lower()}",
                "hint": "Results are also shown separately for each group.", "append": add}
    if raw.get("group") is not None:
        p = groups.get(raw["group"])
        if not p or not p.get("patterns"):
            return None
        phrase = p["patterns"][0]
        add = f" Study {'people ' + phrase if phrase.startswith(('with ', 'without ')) else phrase}."
        if p["id"] not in (planner.parse_question(base + add, k).get("populations") or []):
            return None
        return {"id": f"ai{i}", "label": add.strip()[6:-1].capitalize(), "hint": "Only these people are included.", "append": add}
    if raw.get("age_from") is not None:
        try:
            lo = int(raw["age_from"])
            hi = int(raw["age_to"]) if raw.get("age_to") is not None else None
        except (TypeError, ValueError):
            return None
        if not 0 <= lo <= 85 or (hi is not None and not lo < hi <= 120):
            return None
        span = f"{lo} to {hi}" if hi is not None else f"{lo} and older"
        add = f" Study people aged {span}."
        if planner.parse_question(base + add, k).get("age_range") != (lo, hi):
            return None
        return {"id": f"ai{i}", "label": f"Age {span}", "hint": "Only people of these ages are included.", "append": add}
    return None


def suggest(question: str, understood: list[dict], asked: list[dict], k: Knowledge,
            provider: str | None = None) -> tuple[list[dict], str | None]:
    """Up to MAX_AI_QUESTIONS checked follow-up questions from the LLM, plus a note when the AI could not help."""
    client = LLMClient(provider)
    if not client.enabled:
        return [], None
    key = (question, client.provider.name, client.provider.model, tuple(q["id"] for q in asked))
    if key in _CACHE:
        return _CACHE[key], None
    try:
        out = client.complete_json("Interviewer", SYSTEM, _prompt(question, understood, asked, k), max_tokens=900)
    except LLMError as e:
        return [], f"The AI interviewer is unavailable ({str(e)[:160]}); the questions below come from Q2E's rules."
    qs: list[dict[str, Any]] = []
    seen_text = {q["text"].lower() for q in asked}
    who_asked = any(q["id"] in ("population", "ages") for q in asked)    # the rules already ask who / which ages
    for n, raw in enumerate((out.get("questions") or [])[:MAX_AI_QUESTIONS]):
        if not isinstance(raw, dict):
            continue
        text, why = str(raw.get("text") or "").strip()[:200], str(raw.get("why") or "").strip()[:300]
        if not text or text.lower() in seen_text or scan_causal(text):
            continue
        opts, labels = [], set()
        for i, o in enumerate(raw.get("options") or []):
            if not isinstance(o, dict) or (who_asked and ("group" in o or "age_from" in o)):
                continue
            opt = _option(o, i, question, k)
            if opt and opt["label"] not in labels:
                labels.add(opt["label"])
                opts.append(opt)
        if len(opts) < 2:
            continue                # fewer than two real choices: not worth asking
        qs.append({"id": f"ai{n}", "text": text, "why": why, "options": opts[:4], "source": "ai",
                   "free_text": {"placeholder": "Or type your own answer", "template": " {text}."}})
    _CACHE[key] = qs
    return qs, None
