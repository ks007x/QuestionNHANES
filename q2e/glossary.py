"""Plain-language meanings for abbreviations shown in the app.

NHANES variable names, data-file names and cycle letters come from the CDC files in knowledge/nhanes
(dictionary.csv, catalog.csv, tables.csv, cycles.yaml). Everything else comes from the fixed list below -
standard expansions only, no guessing: an abbreviation that is not found is simply left out.
"""
from __future__ import annotations

import re

from .knowledge import get_knowledge

TERMS = {
    "NHANES": "National Health and Nutrition Examination Survey, run by the CDC",
    "CDC": "Centers for Disease Control and Prevention",
    "NCHS": "National Center for Health Statistics, the part of the CDC that runs NHANES",
    "MEC": "Mobile Examination Center - the NHANES trailer where the physical exam and lab samples are done",
    "PSU": "Primary sampling unit - the groups of counties NHANES samples from (needed for correct survey statistics)",
    "SRS": "Simple random sampling - what ordinary statistics assume (NHANES is not one)",
    "DEFF": "Design effect - how much the survey design widens uncertainty compared with simple random sampling",
    "MDE": "Minimum detectable effect - the smallest effect the study has enough data to detect",
    "OR": "Odds ratio", "PR": "Prevalence ratio", "RR": "Risk ratio",
    "CI": "Confidence interval - the range the true value is likely to fall in",
    "SE": "Standard error", "SD": "Standard deviation", "IQR": "Interquartile range (middle 50% of values)",
    "Q1": "First quartile (lowest 25%)", "Q4": "Fourth quartile (highest 25%)",
    "BMI": "Body mass index (weight in kg divided by height in metres squared)",
    "BP": "Blood pressure", "SBP": "Systolic blood pressure (top number)", "DBP": "Diastolic blood pressure (bottom number)",
    "HbA1c": "Glycated hemoglobin - average blood sugar over about the last 3 months",
    "eGFR": "Estimated glomerular filtration rate - how well the kidneys filter blood",
    "CKD": "Chronic kidney disease",
    "UACR": "Urine albumin-to-creatinine ratio - a urine test for kidney damage",
    "CRP": "C-reactive protein - a blood marker of inflammation",
    "hsCRP": "High-sensitivity C-reactive protein - a blood marker of inflammation",
    "LDL": "Low-density lipoprotein ('bad') cholesterol", "HDL": "High-density lipoprotein ('good') cholesterol",
    "PHQ": "Patient Health Questionnaire (the PHQ-9 depression screener used in NHANES)",
    "GED": "General Educational Development - a high-school equivalency certificate",
    "ACC": "American College of Cardiology", "AHA": "American Heart Association", "ADA": "American Diabetes Association",
    "AASM": "American Academy of Sleep Medicine",
    "JNC": "Joint National Committee on high blood pressure (JNC7 = its 7th report)",
    "JNC7": "7th report of the Joint National Committee on high blood pressure",
    "KDIGO": "Kidney Disease: Improving Global Outcomes (kidney guideline group)",
    "WHO": "World Health Organization", "NIH": "National Institutes of Health",
    "PICO": "Population, Intervention/exposure, Comparison, Outcome - the parts of a research question",
    "EHR": "Electronic health record",
    "TriNetX": "A commercial network of electronic health records used for research",
    "PubMed": "The free search engine for medical research papers", "MEDLINE": "The main database of medical journal articles behind PubMed",
    "JAMA": "Journal of the American Medical Association",
    "QC": "Quality check", "AI": "Artificial intelligence", "LLM": "Large language model (the kind of AI behind chatbots)",
    "SHA": "A fingerprint code (SHA-256): if anything in the plan changes, the code changes",
    "MD5": "A fingerprint code for a data file, to prove the same file was used",
    "CSV": "Comma-separated values (a spreadsheet file)", "JSON": "A plain-text data file format",
    "XPT": "SAS transport file - the format NHANES data files are published in",
    "UTC": "Coordinated Universal Time", "US": "United States",
}
FILES = {"DEMO": "Demographic Variables and Sample Weights"}


def _stem(code: str) -> str:
    s = re.sub(r"^P_", "", code)
    return re.sub(r"_[A-L]$", "", s)


def lookup(terms: list[str]) -> dict[str, dict]:
    k = get_knowledge()
    tables = {**{c: {"description": d} for c, d in FILES.items()}, **{t["table"]: t for t in k.tables}}
    out: dict[str, dict] = {}
    for raw in dict.fromkeys(terms):
        t = raw.strip()
        if not t or len(t) > 40:
            continue
        base = t[:-1] if t.endswith("s") and t[:-1] in TERMS else t
        if base in TERMS:
            out[t] = {"meaning": TERMS[base], "kind": "term"}
        elif t in k.dictionary:
            r = k.dictionary[t]
            f = tables.get(_stem(r.get("file", "")), {})
            where = f" - in the {f['description']} file ({r['file']})" if f else (f" - file {r['file']}" if r.get("file") else "")
            out[t] = {"meaning": f"NHANES variable: {r.get('label') or t}{where}", "kind": "variable", "source": "CDC NHANES codebook"}
        elif _stem(t) in tables:
            out[t] = {"meaning": f"NHANES data file: {tables[_stem(t)]['description']}", "kind": "file", "source": "CDC NHANES file list"}
    return out
