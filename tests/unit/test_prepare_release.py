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
    fix = _pr(11, "fix", "fix: a nasty bug", "bob")
    info = ReleaseInfo(
        base="v2.9.0",
        release_tag="v3.0.0",
        version="3.0.0",
        pull_requests={"feat": [feat], "fix": [fix]},
        first_time_prs=[feat],
    )

    notes = build_gh_release_notes(info)

    assert "## Sponsors" in notes
    assert "### New features" in notes
    assert "feat: a shiny feature by @alice" in notes
    assert "### Bugfixes" in notes
    assert "fix: a nasty bug by @bob" in notes
    assert "## New contributors" in notes
    assert "@alice made their first contribution" in notes
    assert "compare/v2.9.0...v3.0.0" in notes
