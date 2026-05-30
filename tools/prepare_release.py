from __future__ import annotations

import asyncio
import datetime
import os
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass

import click
import httpx
import msgspec

_polar = "[Polar.sh](https://polar.sh/litestar-org)"
_open_collective = "[OpenCollective](https://opencollective.com/litestar)"
_github_sponsors = "[GitHub Sponsors](https://github.com/sponsors/litestar-org/)"

# repository slug; overridable so the tool also works on forks (Actions sets GITHUB_REPOSITORY)
_REPO = os.getenv("GITHUB_REPOSITORY", "litestar-org/litestar")
_OWNER, _, _NAME = _REPO.partition("/")


class PullRequest(msgspec.Struct, kw_only=True):
    title: str
    number: int
    body: str
    created_at: str
    user: RepoUser
    merge_commit_sha: str | None = None


class Comp(msgspec.Struct):
    sha: str

    class _Commit(msgspec.Struct):
        message: str
        url: str

    commit: _Commit


class RepoUser(msgspec.Struct):
    login: str
    id: int
    type: str


@dataclass
class PRInfo:
    url: str
    title: str
    clean_title: str
    cc_type: str
    number: int
    closes: list[int]
    created_at: datetime.datetime
    description: str
    user: RepoUser


@dataclass
class ReleaseInfo:
    base: str
    release_tag: str
    version: str
    pull_requests: dict[str, list[PRInfo]]
    first_time_prs: list[PRInfo]

    @property
    def compare_url(self) -> str:
        return f"https://github.com/{_REPO}/compare/{self.base}...{self.release_tag}"


def _pr_number_from_commit(comp: Comp) -> int:
    # this is an ugly hack, but it appears to actually be the most reliably way to
    # extract the most "reliable" way to extract the info we want from GH ¯\_(ツ)_/¯
    message_head = comp.commit.message.split("\n\n")[0]
    match = re.search(r"\(#(\d+)\)$", message_head)
    if not match:
        print(f"Could not find PR number in {message_head}")  # noqa: T201
    return int(match[1]) if match else None


class _Thing:
    def __init__(self, *, gh_token: str, base: str, release_branch: str, tag: str, version: str) -> None:
        self._gh_token = gh_token
        self._base = base
        self._new_release_tag = tag
        self._release_branch = release_branch
        self._new_release_version = version
        self._base_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {gh_token}",
            }
        )
        self._api_client = httpx.AsyncClient(
            headers={
                **self._base_client.headers,
                "X-GitHub-Api-Version": "2022-11-28",
                "Accept": "application/vnd.github+json",
            },
            base_url=f"https://api.github.com/repos/{_REPO}/",
        )

    async def get_closing_issues_references(self, pr_number: int) -> list[int]:
        graphql_query = """{
        repository(owner: "%s", name: "%s") {
            pullRequest(number: %d) {
                id
                closingIssuesReferences (first: 10) {
                    edges {
                        node {
                            number
                        }
                    }
                }
            }
        }
    }"""
        query = graphql_query % (_OWNER, _NAME, pr_number)
        res = await self._base_client.post("https://api.github.com/graphql", json={"query": query})
        res.raise_for_status()
        data = res.json()
        return [
            edge["node"]["number"]
            for edge in data["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["edges"]
        ]

    async def _get_pr_info_for_pr(self, number: int) -> PRInfo | None:
        res = await self._api_client.get(f"/pulls/{number}")
        if res.is_client_error:
            click.secho(
                f"Could not get PR info for {number}.  Fetch request returned a status of {res.status_code}",
                fg="yellow",
            )
            return None
        res.raise_for_status()
        data = res.json()
        if not data["body"]:
            data["body"] = ""
        if not data:
            return None
        pr = msgspec.convert(data, type=PullRequest)

        cc_prefix, clean_title = pr.title.split(":", maxsplit=1)
        cc_type = cc_prefix.split("(", maxsplit=1)[0].lower()
        closes_issues = await self.get_closing_issues_references(pr_number=pr.number)

        return PRInfo(
            number=pr.number,
            cc_type=cc_type,
            clean_title=clean_title.strip(),
            url=f"https://github.com/{_REPO}/pull/{pr.number}",
            closes=closes_issues,
            title=pr.title,
            created_at=datetime.datetime.strptime(pr.created_at, "%Y-%m-%dT%H:%M:%S%z"),
            description=pr.body,
            user=pr.user,
        )

    async def get_prs(self) -> dict[str, list[PRInfo]]:
        res = await self._api_client.get(f"/compare/{self._base}...{self._release_branch}")
        res.raise_for_status()
        compares = msgspec.convert(res.json()["commits"], list[Comp])
        pr_numbers = list(filter(None, (_pr_number_from_commit(c) for c in compares)))
        pulls = await asyncio.gather(*map(self._get_pr_info_for_pr, pr_numbers))

        prs = defaultdict(list)
        for pr in pulls:
            if not pr:
                continue
            if pr.user.type != "Bot":
                prs[pr.cc_type].append(pr)
        return prs

    async def _get_first_time_contributions(self, prs: dict[str, list[PRInfo]]) -> list[PRInfo]:
        # there's probably a way to peel this information out of the GraphQL API but
        # this was easier to implement, and it works well enough ¯\_(ツ)_/¯
        # the logic is: if we don't find a commit to the main branch, dated before the
        # first commit within this release, it's the user's first contribution
        prs_by_user_login: dict[str, list[PRInfo]] = defaultdict(list)
        for pr in [p for type_prs in prs.values() for p in type_prs]:
            prs_by_user_login[pr.user.login].append(pr)

        first_prs: list[PRInfo] = []

        async def is_user_first_commit(user_login: str) -> None:
            first_pr = sorted(prs_by_user_login[user_login], key=lambda p: p.created_at)[0]
            res = await self._api_client.get(
                "/commits",
                params={
                    "author": user_login,
                    "sha": "main",
                    "until": first_pr.created_at.isoformat(),
                    "per_page": 1,
                },
            )
            res.raise_for_status()

            if len(res.json()) == 0:
                first_prs.append(first_pr)

        await asyncio.gather(*map(is_user_first_commit, prs_by_user_login.keys()))

        return first_prs

    async def get_release_info(self) -> ReleaseInfo:
        prs = await self.get_prs()
        first_time_contributors = await self._get_first_time_contributions(prs)
        return ReleaseInfo(
            pull_requests=prs,
            first_time_prs=first_time_contributors,
            base=self._base,
            release_tag=self._new_release_tag,
            version=self._new_release_version,
        )

    async def create_draft_release(self, body: str, release_branch: str) -> str:
        # mark alpha/beta/rc/dev versions as a GitHub pre-release (the API won't derive this)
        is_prerelease = bool(re.search(r"(a|b|rc)\d+|\.dev\d+", self._new_release_version))
        res = await self._api_client.post(
            "/releases",
            json={
                "tag_name": self._new_release_tag,
                "target_commitish": release_branch,
                "name": self._new_release_tag,
                "draft": True,
                "prerelease": is_prerelease,
                "body": body,
            },
        )
        res.raise_for_status()
        return res.json()["html_url"]  # type: ignore[no-any-return]


class GHReleaseWriter:
    def __init__(self) -> None:
        self.text = ""

    def add_line(self, line: str) -> None:
        self.text += line + "\n"

    def add_pr_descriptions(self, infos: list[PRInfo]) -> None:
        for info in infos:
            # clean_title drops the conventional-commit prefix (e.g. "docs: ");
            # capitalize only the first char (not .capitalize(), which mangles acronyms like "OpenAPI")
            title = info.clean_title[:1].upper() + info.clean_title[1:]
            self.add_line(f"* {title} by @{info.user.login} in {info.url}")


def build_gh_release_notes(release_info: ReleaseInfo) -> str:
    # this is for the most part just recreating GitHub's autogenerated release notes
    # but with three important differences:
    # 1. PRs are sorted into categories
    # 2. The conventional commit type is stripped from the title
    # 3. It works with our release branch process. GitHub doesn't pick up (all) commits
    #    made there depending on how things were merged
    doc = GHReleaseWriter()

    # conventional-commit type -> release-notes section, in display order
    sections = (
        ("feat", "### New features 🚀"),
        ("fix", "### Bugfixes 🐛"),
        ("perf", "### Performance ⚡"),
        ("refactor", "### Refactors 🔧"),
        ("docs", "### Documentation 📚"),
    )
    titled_types = {cc_type for cc_type, _ in sections}
    ignored_types = {"ci", "chore"}  # internal noise, kept out of the notes

    doc.add_line("## What's changed")
    for cc_type, title in sections:
        if prs := release_info.pull_requests.get(cc_type):
            doc.add_line(f"\n{title}")
            doc.add_pr_descriptions(prs)

    if other := [
        pr
        for cc_type, prs in release_info.pull_requests.items()
        if cc_type not in titled_types and cc_type not in ignored_types
        for pr in prs
    ]:
        doc.add_line("\n<!-- Review these: Not all of them should go into the release notes -->")
        doc.add_line("### Other changes")
        doc.add_pr_descriptions(other)

    if release_info.first_time_prs:
        doc.add_line("\n## New contributors 🎉")
        for pr in release_info.first_time_prs:
            doc.add_line(f"* @{pr.user.login} made their first contribution in {pr.url}")

    doc.add_line("\n**Full Changelog**")
    doc.add_line(release_info.compare_url)

    doc.add_line("\n## Installation")
    doc.add_line(f"Install or upgrade to `{release_info.version}`:")
    doc.add_line("```shell")
    doc.add_line("# uv")
    doc.add_line(f'uv add "litestar=={release_info.version}"')
    doc.add_line("# pip")
    doc.add_line(f'pip install --upgrade "litestar=={release_info.version}"')
    doc.add_line("```")

    # sponsors at the end (mirrors astral-sh/uv release layout)
    doc.add_line("\n## Sponsors 🌟")
    doc.add_line(
        "⚠️ Maintainers: Please adjust business/individual sponsors section here as defined by our tier rewards"
    )
    doc.add_line(f"- A huge 'Thank you!' to all sponsors across {_polar}, {_open_collective} and {_github_sponsors}!")

    return doc.text


def _get_gh_token() -> str:
    if gh_token := os.getenv("GH_TOKEN"):
        click.secho("Using GitHub token from env", fg="blue")
        return gh_token

    gh_executable = shutil.which("gh")
    if not gh_executable:
        click.secho("GitHub CLI not installed", fg="yellow")
    else:
        click.secho("Using GitHub CLI to obtain GitHub token", fg="blue")
        proc = subprocess.run([gh_executable, "auth", "token"], check=True, capture_output=True, text=True)
        if out := (proc.stdout or "").strip():
            return out

    click.secho("Could not find any GitHub token", fg="red")
    quit(1)


def _get_latest_tag() -> str:
    click.secho("Using latest tag", fg="blue")
    # The highest version tag = the latest release (e.g. v2.23.0). NOT `--sort=taggerdate`,
    # which wrongly orders litestar's many lightweight tags (no tagger date) and can return
    # e.g. v2.9.1; and NOT `git describe`, which only sees tags reachable from HEAD (the 3.0
    # branch diverged at v2.17.0, so it would miss the later 2.x maintenance releases).
    out = subprocess.run(  # noqa: S602
        "git tag --sort=-v:refname", check=False, capture_output=True, text=True, shell=True
    ).stdout.strip()
    if not out:
        raise ValueError("no git tags found")
    return out.splitlines()[0]


@click.command()
@click.argument("version")
@click.option("--base", help="Previous release tag. Defaults to the latest tag")
@click.option("--branch", help="Release branch", default="main")
@click.option(
    "--gh-token",
    help="GitHub token. If not provided, read from the GH_TOKEN env variable. "
    "Alternatively, if the GitHub CLI is installed, it will be used to fetch a token",
)
@click.option("-c", "--create-draft-release", is_flag=True, help="Create draft release on GitHub")
def cli(
    base: str | None,
    branch: str,
    version: str,
    gh_token: str | None,
    create_draft_release: bool,
) -> None:
    if gh_token is None:
        gh_token = _get_gh_token()
    if base is None:
        base = _get_latest_tag()

    if not re.match(r"\d+\.\d+\.\d+", version):
        click.secho(f"Invalid version: {version!r}")
        quit(1)

    new_tag = f"v{version}"

    click.secho(f"Creating release notes for tag {new_tag}, using {base} as a base", fg="cyan")

    thing = _Thing(gh_token=gh_token, base=base, release_branch=branch, tag=new_tag, version=version)
    loop = asyncio.new_event_loop()

    release_info = loop.run_until_complete(thing.get_release_info())
    gh_release_notes = build_gh_release_notes(release_info)

    if create_draft_release:
        click.secho("Creating draft release", fg="blue")
        release_url = loop.run_until_complete(thing.create_draft_release(body=gh_release_notes, release_branch=branch))
        click.echo(f"Draft release available at: {release_url}")
    else:
        click.echo(gh_release_notes)

    loop.close()


if __name__ == "__main__":
    cli()
