#!/usr/bin/env bash
# Release preview / readiness check. Writes NOTHING (no version bump, no changelog
# build, no tag, no push). Shared by `make release-preview` (local) and the dry-run
# path of .github/workflows/release.yml (CI).
#
# Usage: tools/release_preview.sh [bump]
#   bump: patch | minor | major | stable | alpha | beta | rc   (default: patch)
set -euo pipefail

BUMP="${1:-patch}"
fail=0

check() { # check "<label>" <exit-status>
	if [ "$2" -eq 0 ]; then printf '  \033[32m✅\033[0m %s\n' "$1"; else printf '  \033[31m❌\033[0m %s\n' "$1"; fail=1; fi
}

CUR_VERSION="$(uv version --short)"
NEW_VERSION="$(uv version --dry-run --bump "$BUMP" --output-format json \
	| python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
TAG="v${NEW_VERSION}"

printf '\nRelease preview: %s --(%s)--> %s\n\n' "$CUR_VERSION" "$BUMP" "$NEW_VERSION"
echo "Readiness checks"

git diff --quiet && git diff --cached --quiet
check "working tree clean" $?

uv lock --check >/dev/null 2>&1
check "uv.lock up to date" $?

if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null 2>&1 \
	|| git ls-remote --exit-code --tags origin "${TAG}" >/dev/null 2>&1; then
	check "tag ${TAG} does not exist yet" 1
else
	check "tag ${TAG} does not exist yet" 0
fi

if CHANGELOG_PREVIEW="$(uvx --from 'towncrier>=24,<26' towncrier build --draft --version "${NEW_VERSION}" 2>/dev/null)"; then
	check "news fragments parse" 0
else
	check "news fragments parse" 1
	CHANGELOG_PREVIEW="(towncrier build --draft failed)"
fi

HAVE_TOKEN=0
if [ -n "${GH_TOKEN:-}" ] || gh auth token >/dev/null 2>&1; then
	check "GitHub token available" 0
	HAVE_TOKEN=1
else
	check "GitHub token available (needed for the draft release)" 1
fi

printf '\nChangelog preview (towncrier --draft, not written):\n'
if printf '%s' "${NEW_VERSION}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(\.post[0-9]+)?$'; then
	ESC="${NEW_VERSION//./\\.}"
	PRE_COUNT="$(grep -cE "^\.\. changelog:: ${ESC}((a|b|rc)[0-9]+|\.dev[0-9]+)\$" docs/release-notes/changelog.rst 2>/dev/null)" || PRE_COUNT=0
	if [ "${PRE_COUNT}" -gt 0 ]; then
		printf '(final release: %s existing pre-release section(s) will be folded into %s at release time)\n' "${PRE_COUNT}" "${NEW_VERSION}"
	fi
else
	printf '(pre-release: this section is kept and later folded into the final release)\n'
fi
printf -- '------------------------------------------------------------\n%s\n' "${CHANGELOG_PREVIEW}"
printf -- '------------------------------------------------------------\n'

if [ "${HAVE_TOKEN}" -eq 1 ]; then
	printf '\nGitHub release notes preview:\n'
	printf -- '------------------------------------------------------------\n'
	uv run python tools/prepare_release.py "${NEW_VERSION}" 2>/dev/null || echo "(could not generate GH notes preview)"
	printf -- '------------------------------------------------------------\n'
fi

printf '\n'
if [ "${fail}" -eq 0 ]; then
	echo "✅ READY to release ${NEW_VERSION} (re-run release.yml with dry_run=false to cut it)."
else
	echo "❌ NOT READY — resolve the ❌ items above."
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
	{
		printf '## Release preview: `%s` → `%s` (bump: `%s`)\n\n' "${CUR_VERSION}" "${NEW_VERSION}" "${BUMP}"
		if [ "${fail}" -eq 0 ]; then
			printf '**✅ READY** — re-run with `dry_run: false` to cut the release.\n\n'
		else
			printf '**❌ NOT READY** — resolve the failing checks.\n\n'
		fi
		printf '### Changelog entry (preview)\n\n```rst\n%s\n```\n' "${CHANGELOG_PREVIEW}"
	} >>"${GITHUB_STEP_SUMMARY}"
fi

exit "${fail}"
