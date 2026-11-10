from review_router_engine.codeowners import CodeOwners
from review_router_engine.globs import matches


def test_unanchored_pattern_matches_any_depth():
    assert matches("*.md", "README.md")
    assert matches("*.md", "docs/a/b.md")
    assert not matches("*.md", "README.mdx")


def test_anchored_and_directory_patterns():
    assert matches("/infra/", "infra/main.tf")
    assert not matches("/infra/", "src/infra/main.tf")
    assert matches("infra/", "infra/x/y")
    assert matches(".github/workflows/", ".github/workflows/ci.yml")
    assert matches("docs/", "docs/x.md")


def test_double_star():
    assert matches("**/migrations/**", "app/db/migrations/0001.py")
    assert matches("**/migrations/**", "migrations/0001.py")
    assert not matches("**/migrations/**", "app/migration.py")


def test_star_does_not_cross_slash_in_anchored_pattern():
    assert matches("src/*.py", "src/a.py")
    assert not matches("src/*.py", "src/sub/a.py")


def test_codeowners_last_match_wins():
    co = CodeOwners.parse(
        """
        # comment
        *           @org/everyone
        /api/       @org/api   # inline comment
        /api/auth/  @org/security
        /api/auth/README.md
        """
    )
    assert co.owners_for("web/index.ts") == ("@org/everyone",)
    assert co.owners_for("api/users.py") == ("@org/api",)
    assert co.owners_for("api/auth/login.py") == ("@org/security",)
    assert co.owners_for("api/auth/README.md") == ()  # ownership removed


def test_owner_sets_counts_distinct_groups():
    co = CodeOwners.parse("/a/ @x\n/b/ @y\n/c/ @x")
    assert len(co.owner_sets(["a/1", "b/1", "c/1"])) == 2


def test_empty_codeowners():
    assert CodeOwners.parse(None).owners_for("x") == ()
