import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import backtest as bt  # noqa: E402


def pr(**kw):
    base = {
        "repo": "o/r",
        "number": 42,
        "title": "Add retry to client",
        "mergedAt": "2026-09-01T10:00:00Z",
        "mergeCommit": {"oid": "abcdef1234567890"},
    }
    base.update(kw)
    return base


def c(msg, when="2026-09-03T10:00:00Z", oid="1111111"):
    return {"oid": oid, "committedDate": when, "message": msg}


def test_revert_by_sha():
    assert bt.outcomes(pr(), [c("Revert commit abcdef1, broke prod")])["revert"]


def test_revert_by_github_button_message():
    o = bt.outcomes(pr(), [c('Revert "Add retry to client" (#57)\n\nReverts o/r#42')])
    assert o["revert"] and o["event"]


def test_revert_by_title_only():
    assert bt.outcomes(pr(), [c('Revert "Add retry to client"')])["revert"]


def test_unrelated_revert_is_ignored():
    assert not bt.outcomes(pr(), [c('Revert "Something else" (#58)')])["event"]


def test_fix_requires_explicit_reference():
    assert bt.outcomes(pr(), [c("fix: retry loop from #42 never ends")])["fix"]
    assert not bt.outcomes(pr(), [c("fix: retry loop never ends")])["event"]


def test_reference_to_longer_number_does_not_match():
    assert not bt.outcomes(pr(), [c("fix: bug from #421")])["event"]


def test_outside_window_is_ignored():
    assert not bt.outcomes(pr(), [c("Revert abcdef1", when="2026-09-20T10:00:00Z")])["event"]
    assert not bt.outcomes(pr(), [c("Revert abcdef1", when="2026-08-30T10:00:00Z")])["event"]


def test_own_merge_commit_is_ignored():
    assert not bt.outcomes(pr(), [c("Merge pull request #42 fix bug", oid="abcdef1234567890")])["event"]


def test_to_input_maps_graphql_payload():
    p = {
        "author": {"login": "copilot-swe-agent", "__typename": "Bot"},
        "files": {"nodes": [{"path": "a.py", "additions": 3, "deletions": 1, "changeType": "DELETED"}]},
        "commits": {"nodes": [{"commit": {"message": "x"}}]},
        "last": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]},
        "changedFiles": 1,
        "codeowners": "* @a",
    }
    i = bt.to_input(p)
    assert i.author_is_bot and i.ci_state == "failure" and i.files[0].change_type.value == "removed"


def test_to_input_no_rollup_is_none():
    assert bt.to_input({"last": {"nodes": [{"commit": {"statusCheckRollup": None}}]}}).ci_state == "none"


def test_split_is_deterministic():
    assert bt.split_of("a/b") == bt.split_of("a/b")


def test_fisher_matches_known_value():
    # Classic tea-tasting table [[3,1],[1,3]] -> two-sided p = 0.4857
    assert abs(bt.fisher_two_sided(3, 1, 1, 3) - 0.48571) < 1e-4


def test_holm_is_monotone_and_capped():
    out = bt.holm({"a": 0.01, "b": 0.02, "c": 0.5})
    assert out["a"] == 0.03 and out["b"] == 0.04 and out["c"] == 0.5


def test_release_commit_listing_many_prs_is_ignored():
    body = "chore(main): release 2.55.0 (#5482)\n\n* fix: a (#42)\n* fix: b (#43)\n* fix: c (#44)\n* fix: d (#45)"
    assert not bt.outcomes(pr(), [c(body)])["event"]


def test_merge_branch_commit_is_ignored():
    assert not bt.outcomes(pr(), [c("[automated] Merge branch 'release/11.0' => 'main' (#69175)\n\nfix #42")])["event"]


def test_fix_keyword_must_be_in_subject():
    assert not bt.outcomes(pr(), [c("feat: new thing (#50)\n\nfollow-up to #42, fixes nothing")])["event"]


def test_revert_body_listing_is_not_a_revert():
    assert not bt.outcomes(pr(), [c("Release develop to master (#281)\n\n* Revert something (#42)")])["event"]


def test_own_commit_under_different_sha_is_ignored():
    assert not bt.outcomes(pr(), [c("Add retry to client (#42)", oid="9999999")])["event"]


def test_short_title_does_not_swallow_real_followups():
    p = pr(title="Fix bug")
    assert bt.outcomes(p, [c("Fix bug in parser introduced by #42")])["fix"]
