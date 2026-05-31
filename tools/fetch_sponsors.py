"""Fetch Litestar's current sponsors across GitHub Sponsors, OpenCollective and Polar.

Returns a single merged set of *named* (public) sponsors plus a count of anonymous /
private ones. Private GitHub sponsors and incognito OpenCollective backers are never
named — they only contribute to the anonymous count. Each provider is independent: a
missing token or a failing request skips that provider rather than aborting.

Used by tools/prepare_release.py to fill the Sponsors section of the GitHub release notes.
Run standalone to preview:  GH_TOKEN=$(gh auth token) python tools/fetch_sponsors.py
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import click
import httpx

# Litestar's identifiers on each platform
_GH_ORG = "litestar-org"
_OC_SLUG = "litestar"

_GITHUB_GRAPHQL = "https://api.github.com/graphql"
_OPENCOLLECTIVE_GRAPHQL = "https://api.opencollective.com/graphql/v2"
_POLAR_API = "https://api.polar.sh"

# OpenCollective records cross-platform money under conduit accounts; these are not individual
# sponsors and would double-count the direct GitHub/Polar queries, so drop them. Incognito
# backers surface with this display name and must only add to the anonymous count.
_OC_CONDUIT_ACCOUNTS = {"github sponsors", "polar.sh", "open collective", "opencollective"}
_OC_ANONYMOUS_NAMES = {"incognito"}


@dataclass
class Sponsor:
    name: str
    url: str | None = None
    monthly_cents: int = 0
    source: str = ""  # "GitHub Sponsors" | "OpenCollective" | "Polar" — used to group the notes


async def _github(client: httpx.AsyncClient, token: str) -> tuple[list[Sponsor], int]:
    """Public sponsors are named; PRIVATE ones (we can see them, they don't want to be shown) count as anonymous."""
    query = """
    query ($org: String!, $after: String) {
      organization(login: $org) {
        sponsorshipsAsMaintainer(first: 100, after: $after, includePrivate: true, activeOnly: true) {
          pageInfo { hasNextPage endCursor }
          nodes {
            privacyLevel
            tier { monthlyPriceInCents }
            sponsorEntity {
              __typename
              ... on User { login name url }
              ... on Organization { login name url }
            }
          }
        }
      }
    }
    """
    named: list[Sponsor] = []
    anonymous = 0
    cursor: str | None = None
    while True:
        res = await client.post(
            _GITHUB_GRAPHQL,
            headers={"Authorization": f"Bearer {token}"},
            json={"query": query, "variables": {"org": _GH_ORG, "after": cursor}},
        )
        res.raise_for_status()
        payload = res.json()
        if payload.get("errors"):
            raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))
        organization = payload["data"]["organization"]
        if organization is None:
            raise RuntimeError("cannot read organization sponsors (token needs read:org + maintainer access)")
        conn = organization["sponsorshipsAsMaintainer"]
        for node in conn["nodes"]:
            entity = node.get("sponsorEntity")
            if node.get("privacyLevel") != "PUBLIC" or not entity:
                anonymous += 1
                continue
            cents = (node.get("tier") or {}).get("monthlyPriceInCents") or 0
            named.append(
                Sponsor(name=f"@{entity['login']}", url=entity.get("url"), monthly_cents=cents, source="GitHub Sponsors")
            )
        if not conn["pageInfo"]["hasNextPage"]:
            return named, anonymous
        cursor = conn["pageInfo"]["endCursor"]


async def _opencollective(client: httpx.AsyncClient, token: str | None) -> tuple[list[Sponsor], int]:
    """Named backers are listed; incognito backers count as anonymous. Public data needs no token."""
    query = """
    query ($slug: String!, $offset: Int) {
      account(slug: $slug) {
        members(role: BACKER, limit: 100, offset: $offset) {
          totalCount
          nodes { account { name slug isIncognito } }
        }
      }
    }
    """
    headers = {"Personal-Token": token} if token else {}
    named: list[Sponsor] = []
    anonymous = 0
    offset = 0
    while True:
        res = await client.post(
            _OPENCOLLECTIVE_GRAPHQL, headers=headers, json={"query": query, "variables": {"slug": _OC_SLUG, "offset": offset}}
        )
        res.raise_for_status()
        members = res.json()["data"]["account"]["members"]
        nodes = members["nodes"]
        for node in nodes:
            account = node["account"]
            name = (account.get("name") or "").strip()
            if account.get("isIncognito") or name.lower() in _OC_ANONYMOUS_NAMES or not name:
                anonymous += 1
                continue
            if name.lower() in _OC_CONDUIT_ACCOUNTS:
                continue  # cross-platform conduit, not an individual — counted via its own provider
            named.append(Sponsor(name=name, url=f"https://opencollective.com/{account['slug']}", source="OpenCollective"))
        offset += len(nodes)
        if not nodes or offset >= members["totalCount"]:
            return named, anonymous


async def _polar(client: httpx.AsyncClient, token: str) -> tuple[list[Sponsor], int]:
    """Active subscribers; a customer with a name is listed, otherwise counted as anonymous.

    The Organization Access Token already scopes the listing to Litestar's org. Names come from
    Polar customer records — the release notes are reviewed by a human before publishing.
    """
    headers = {"Authorization": f"Bearer {token}"}
    named: list[Sponsor] = []
    anonymous = 0
    page = 1
    while True:
        res = await client.get(
            f"{_POLAR_API}/v1/subscriptions", headers=headers, params={"active": "true", "page": page, "limit": 100}
        )
        res.raise_for_status()
        data = res.json()
        items = data.get("items", [])
        for sub in items:
            name = (sub.get("customer") or {}).get("name")
            if name:
                named.append(Sponsor(name=name, monthly_cents=sub.get("amount") or 0, source="Polar"))
            else:
                anonymous += 1
        if not items or page >= (data.get("pagination") or {}).get("max_page", 1):
            return named, anonymous
        page += 1


async def fetch_sponsors(*, gh_token: str | None = None) -> dict:
    """Aggregate sponsors across all platforms. Returns {"named": [Sponsor], "anonymous": int}.

    GitHub uses gh_token (or GH_TOKEN); OpenCollective uses OPENCOLLECTIVE_TOKEN (optional — public
    data works without it); Polar uses POLAR_TOKEN. Providers without a usable token/response are skipped.
    """
    gh_token = gh_token or os.getenv("GH_TOKEN")
    oc_token = os.getenv("OPENCOLLECTIVE_TOKEN")
    polar_token = os.getenv("POLAR_TOKEN")

    async with httpx.AsyncClient(timeout=20) as client:
        labelled = [("OpenCollective", _opencollective(client, oc_token))]
        if gh_token:
            labelled.insert(0, ("GitHub Sponsors", _github(client, gh_token)))
        if polar_token:
            labelled.append(("Polar", _polar(client, polar_token)))
        results = await asyncio.gather(*(coro for _, coro in labelled), return_exceptions=True)

    named: list[Sponsor] = []
    anonymous = 0
    for (label, _), result in zip(labelled, results, strict=True):
        if isinstance(result, Exception):
            click.secho(f"  sponsors: {label} lookup failed ({result})", fg="yellow")
            continue
        provider_named, provider_anonymous = result
        named.extend(provider_named)
        anonymous += provider_anonymous

    # dedup within a platform (not across — the notes group by platform), highest tier first
    seen: set[tuple[str, str]] = set()
    deduped: list[Sponsor] = []
    for sponsor in sorted(named, key=lambda s: (-s.monthly_cents, s.name.lower())):
        key = (sponsor.source, sponsor.name.lower())
        if key not in seen:
            seen.add(key)
            deduped.append(sponsor)

    return {"named": deduped, "anonymous": anonymous}


@click.command()
def _main() -> None:
    result = asyncio.run(fetch_sponsors())
    click.secho(f"named ({len(result['named'])}):", fg="cyan")
    for sponsor in result["named"]:
        click.echo(f"  - {sponsor.name}  {sponsor.url or ''}  ({sponsor.monthly_cents}c)")
    click.secho(f"anonymous: {result['anonymous']}", fg="cyan")


if __name__ == "__main__":
    _main()
