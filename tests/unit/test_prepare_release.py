"""Tests for the GitHub-release-notes generation kept in ``tools/prepare_release.py``.

Pure / no GitHub API: constructs fixtures and asserts the rendered markdown structure.
"""

from __future__ import annotations

import datetime

from tools.prepare_release import PRInfo, ReleaseInfo, RepoUser, build_gh_release_notes


def _pr(number: int, cc_type: str, title: str, login: str) -> PRInfo:
    return PRInfo(
        url=f"https://github.com/litestar-org/litestar/pull/{number}",
        title=title,
        clean_title=title.split(": ", 1)[-1],
        cc_type=cc_type,
        number=number,
        closes=[],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        description="body",
        user=RepoUser(login=login, id=number, type="User"),
    )


def test_build_gh_release_notes_has_all_sections() -> None:
    feat = _pr(10, "feat", "feat: a shiny feature", "alice")
    info = ReleaseInfo(
        base="v2.9.0",
        release_tag="v3.0.0",
        version="3.0.0",
        pull_requests={
            "feat": [feat],
            "fix": [_pr(11, "fix", "fix: a nasty bug", "bob")],
            "perf": [_pr(12, "perf", "perf: faster startup", "carol")],
            "refactor": [_pr(13, "refactor", "refactor: tidy internals", "dave")],
            "docs": [_pr(14, "docs", "docs: better guide", "erin")],
            "build": [_pr(15, "build", "build: bump a dependency", "frank")],
            "chore": [_pr(16, "chore", "chore: internal noise", "grace")],
        },
        first_time_prs=[feat],
    )

    notes = build_gh_release_notes(info)

    assert "### New features" in notes and "a shiny feature" in notes
    assert "### Bugfixes" in notes and "a nasty bug" in notes
    assert "### Performance" in notes and "faster startup" in notes
    assert "### Refactors" in notes and "tidy internals" in notes
    assert "### Documentation" in notes and "better guide" in notes
    assert "### Other changes" in notes and "bump a dependency" in notes  # build -> Other
    assert "internal noise" not in notes  # chore -> dropped
    assert "## New contributors" in notes and "@alice made their first contribution" in notes
    assert "compare/v2.9.0...v3.0.0" in notes
    # installation section with uv + pip, pinned to the version
    assert "## Installation" in notes
    assert 'uv add "litestar==3.0.0"' in notes
    assert 'pip install --upgrade "litestar==3.0.0"' in notes
    # sponsors comes after the changes and the installation block (uv-style layout)
    assert notes.index("## Sponsors") > notes.index("## Installation") > notes.index("## What's changed")
