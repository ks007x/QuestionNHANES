import pytest

from q2e.expressions import ExpressionError, identifiers, validate


def test_identifiers_skip_functions_and_named_args():
    assert identifiers('cases(lsm < 10, "a", .default = "b")') == ["lsm"]
    assert identifiers("any_of(egfr < 60, uacr >= 30)") == ["egfr", "uacr"]
    assert identifiers("coalesce(RIDEXPRG, 2) == 1") == ["RIDEXPRG"]


@pytest.mark.parametrize("bad", ['system("rm -rf /")', "x <- 1", "a = 3", "eval(parse(text='1'))", "x[1]", "df$col",
                                 "base::sum(x)", "{x}", "Sys.getenv('HOME')", "(a"])
def test_rejects_unsafe(bad):
    with pytest.raises(ExpressionError):
        validate(bad)


def test_unknown_variable():
    with pytest.raises(ExpressionError):
        validate("ferritin < 30 & nonexistent > 1", {"ferritin"})


def test_accepts_guideline_expressions():
    from q2e.knowledge import get_knowledge
    k = get_knowledge()
    known = set(k.blocks) | set(k.definitions) | set(k.dictionary)
    for d in k.definitions.values():
        validate(d["expr"], known)
    for b in k.blocks.values():
        validate(b.get("nhanes") or b["expr"], known)
