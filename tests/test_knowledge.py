from q2e.knowledge import get_knowledge
from q2e.planner import _raw_dependencies


def test_every_measure_maps_to_dictionary():
    k = get_knowledge()
    for b in k.blocks.values():
        if b["tier"] == "measure":
            raw = _raw_dependencies(b["name"], k)
            assert raw, b["name"]
            assert all(r in k.dictionary for r in raw), b["name"]


def test_definitions_cite_sources_and_status():
    k = get_knowledge()
    for d in k.definitions.values():
        assert d["source"].get("citation"), d["id"]
        assert d["status"] in ("verified", "secondary-source", "proposed", "investigator-approved"), d["id"]
        assert d["type"] in ("binary", "categorical")


def test_guideline_versions_present():
    k = get_knowledge()
    for i in ("id_ash2026", "ckd_id_kdigo2026", "csph_baveno8", "csph_baveno7", "fid_tawfik2024"):
        assert i in k.definitions


def test_concept_targets_exist():
    k = get_knowledge()
    for c in k.concepts.values():
        for d in c.get("definitions", []) + c.get("alt_definitions", []) + c.get("companion_definitions", []):
            assert d in k.definitions, (c["id"], d)
        if c.get("block"):
            assert c["block"] in k.blocks, c["id"]
