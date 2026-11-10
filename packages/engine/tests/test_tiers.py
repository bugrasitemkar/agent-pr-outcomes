import pytest

from review_router_engine import (
    AuthorKind,
    ChangeType,
    Confidence,
    Config,
    FileChange,
    PathThreshold,
    PRInput,
    Tier,
    evaluate,
    fail_closed,
)


def f(path, add=10, dele=0, ct=ChangeType.MODIFIED):
    return FileChange(path=path, additions=add, deletions=dele, change_type=ct)


def pr(**kw):
    base = dict(author_login="alice", ci_state="success", files=[f("src/app.py"), f("tests/test_app.py")])
    base.update(kw)
    return PRInput(**base)


# --- plan's end-to-end scenarios ---------------------------------------------------------


def test_docs_only_human_pr_is_t1():
    d = evaluate(pr(files=[f("README.md", 20), f("docs/guide.md", 5)]))
    assert d.tier == Tier.T1 and d.status == "final"


def test_small_agent_pr_with_trailer_tests_and_ticket_is_t1():
    d = evaluate(
        pr(
            commit_messages=["fix bug\n\nCo-Authored-By: Claude <noreply@anthropic.com>"],
            body="Fixes #42\n\nGenerated with [Claude Code]",
        )
    )
    assert d.author.kind == AuthorKind.AGENT and d.author.agent_name == "claude"
    assert d.author.confidence == Confidence.MEDIUM
    assert d.tier == Tier.T1


def test_agent_pr_without_ticket_is_t2_with_missing_evidence():
    d = evaluate(pr(author_login="copilot-swe-agent[bot]", author_is_bot=True))
    assert d.tier == Tier.T2
    assert "Agent PR without a linked issue/ticket" in d.missing_evidence


def test_agent_pr_touching_migration_and_workflow_is_t3():
    d = evaluate(
        pr(
            author_login="devin-ai-integration[bot]",
            files=[f("app/migrations/0002_add.py"), f(".github/workflows/ci.yml")],
        )
    )
    assert d.tier == Tier.T3
    assert any(r.code == "critical_paths" for r in d.reasons)


@pytest.mark.parametrize("path", [".github/review-router.yml", ".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"])
def test_pr_changing_control_files_is_always_t3(path):
    d = evaluate(pr(files=[f(path, 1)]))
    assert d.tier == Tier.T3
    assert d.reasons[0].code == "control_files"


# --- fail-closed and edge cases ----------------------------------------------------------


def test_truncated_file_list_is_t3():
    d = evaluate(pr(changed_files_total=5000))
    assert d.tier == Tier.T3 and any(r.code == "too_many_files" for r in d.reasons)


def test_failing_ci_blocks_t1():
    d = evaluate(pr(ci_state="failure"))
    assert d.tier == Tier.T2 and "CI is failing" in d.missing_evidence


def test_no_ci_blocks_t1():
    assert evaluate(pr(ci_state="none")).tier == Tier.T2


def test_pending_ci_waits_instead_of_downgrading():
    d = evaluate(pr(ci_state="pending"))
    assert d.tier == Tier.T1 and d.status == "waiting_ci"


def test_source_without_tests_is_t2():
    d = evaluate(pr(files=[f("src/app.py")]))
    assert d.tier == Tier.T2 and "Source changes without test changes" in d.missing_evidence


def test_lock_files_do_not_count_toward_size():
    d = evaluate(pr(files=[f("src/app.py", 20), f("tests/t.py", 10), f("uv.lock", 5000)]))
    assert d.counted_lines == 30
    assert d.tier == Tier.T1


def test_large_change_is_t3():
    assert evaluate(pr(files=[f("src/a.py", 900), f("tests/t.py", 10)])).tier == Tier.T3


def test_medium_change_is_t2():
    d = evaluate(pr(files=[f("src/a.py", 300), f("tests/t.py", 10)]))
    assert d.tier == Tier.T2 and any(r.code == "medium_size" for r in d.reasons)


def test_many_codeowner_groups_is_t3():
    co = "/a/ @x\n/b/ @y\n/c/ @z"
    files = [f("a/1.py", 1), f("b/1.py", 1), f("c/1.py", 1), f("tests/t.py", 1)]
    assert evaluate(pr(files=files, codeowners_text=co)).tier == Tier.T3


def test_monorepo_path_threshold_is_stricter():
    cfg = Config(path_thresholds=[PathThreshold(pattern="services/payments/", t1_max_lines=20)])
    files = [f("services/payments/x.py", 40), f("tests/t.py", 5)]
    assert evaluate(pr(files=files), cfg).tier == Tier.T2
    files_other = [f("services/search/x.py", 40), f("tests/t.py", 5)]
    assert evaluate(pr(files=files_other), cfg).tier == Tier.T1


def test_unknown_bot_never_t1():
    assert evaluate(pr(author_login="some-bot[bot]", author_is_bot=True)).tier == Tier.T2


def test_dependency_bot_detected():
    d = evaluate(pr(author_login="dependabot[bot]", author_is_bot=True, files=[f("package.json", 2)]))
    assert d.author.kind == AuthorKind.DEPENDENCY_BOT
    assert d.tier == Tier.T3  # manifest change is a critical path


def test_branch_only_agent_signal_is_low_confidence_and_not_t1():
    d = evaluate(pr(head_ref="codex/fix-thing", body="Fixes #1"))
    assert d.author.kind == AuthorKind.AGENT and d.author.confidence == Confidence.LOW
    assert d.tier == Tier.T2


def test_utf8_is_not_a_ticket():
    d = evaluate(pr(author_login="copilot-swe-agent[bot]", author_is_bot=True, title="Handle UTF-8 input"))
    assert "Agent PR without a linked issue/ticket" in d.missing_evidence


def test_linear_key_counts_as_ticket():
    d = evaluate(pr(author_login="copilot-swe-agent[bot]", author_is_bot=True, title="ENG-123 handle input"))
    assert d.tier == Tier.T1


def test_fail_closed_is_never_t1():
    assert fail_closed("alice", "timeout").tier == Tier.T3
