import pytest

from edgefeed import pairs
from edgefeed.arb import Relation


def test_repo_pairs_file_loads():
    ps = pairs.load("config/pairs.yaml")
    assert len(ps) >= 20 and all(p.relation is Relation.SAME for p in ps)


def test_duplicates_and_missing_fields_rejected(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("pairs:\n  - {kalshi: A, polymarket: '1'}\n  - {kalshi: A, polymarket: '1'}\n")
    with pytest.raises(ValueError, match="duplicate"):
        pairs.load(f)
    f.write_text("pairs:\n  - {kalshi: A}\n")
    with pytest.raises(ValueError, match="needs both"):
        pairs.load(f)


def test_fingerprint_ignores_whitespace_and_case():
    assert pairs.fingerprint("If X  wins,\nYes") == pairs.fingerprint("if x wins, yes")
    assert pairs.fingerprint("If X wins") != pairs.fingerprint("If Y wins")


def test_named_outcome_in_key():
    assert pairs.Pair("K", "P", outcome="Hawks").key == "K<>P:Hawks"
