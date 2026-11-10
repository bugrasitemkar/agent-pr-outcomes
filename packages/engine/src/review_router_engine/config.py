"""Engine configuration. Defaults make the app useful with zero setup.

Custom `.github/review-router.yml` values are a paid-tier feature (product
decision); the worker decides whether to load them. The engine just accepts a
Config object.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .codeowners import CODEOWNERS_LOCATIONS

CONFIG_PATH = ".github/review-router.yml"

# Files that control the router itself. A PR touching them is always T3,
# because otherwise a PR could lower its own tier.
CONTROL_FILES: tuple[str, ...] = (CONFIG_PATH, *CODEOWNERS_LOCATIONS)


class PathThreshold(BaseModel):
    """Per-path T1 size limit, for monorepos."""

    pattern: str
    t1_max_lines: int


class Config(BaseModel):
    critical_paths: list[str] = Field(
        default_factory=lambda: [
            "**/migrations/**",
            "**/migrate/**",
            "*.sql",
            ".github/workflows/",
            ".github/actions/",
            "**/terraform/**",
            "*.tf",
            "infra/",
            "**/k8s/**",
            "**/helm/**",
            "Dockerfile",
            "*.dockerfile",
            "docker-compose*.yml",
            "**/auth/**",
            "**/security/**",
            "**/*secret*",
            # dependency manifests (version changes are supply-chain risk)
            "package.json",
            "pyproject.toml",
            "requirements*.txt",
            "go.mod",
            "Cargo.toml",
            "Gemfile",
            "pom.xml",
            "build.gradle*",
        ]
    )
    # Excluded from size counting (they inflate size without review effort).
    size_ignore: list[str] = Field(
        default_factory=lambda: [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "uv.lock",
            "Cargo.lock",
            "go.sum",
            "Gemfile.lock",
            "*.min.js",
            "*.snap",
            "**/__snapshots__/**",
            "**/generated/**",
            "*.pb.go",
            "*_pb2.py",
        ]
    )
    test_paths: list[str] = Field(
        default_factory=lambda: [
            "**/tests/**",
            "**/test/**",
            "**/__tests__/**",
            "**/spec/**",
            "test_*.py",
            "*_test.py",
            "*_test.go",
            "*.test.*",
            "*.spec.*",
        ]
    )
    docs_paths: list[str] = Field(
        default_factory=lambda: ["*.md", "*.mdx", "*.rst", "*.txt", "docs/", "LICENSE*", ".gitignore"]
    )
    t1_max_lines: int = 150
    t1_max_files: int = 10
    t3_min_lines: int = 800
    t3_min_deleted_files: int = 10
    t3_min_owner_sets: int = 3
    max_files_evaluable: int = 3000
    path_thresholds: list[PathThreshold] = Field(default_factory=list)
    require_ticket_for_agent_t1: bool = True
    extra_agent_logins: list[str] = Field(default_factory=list)
    senior_teams: list[str] = Field(default_factory=list)
