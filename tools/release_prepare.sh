#!/usr/bin/env bash
# Prepare a release LOCALLY: create a vX.Y.Z branch, bump the version, assemble the
# changelog from news fragments, and commit. Does NOT push and does NOT touch GitHub.
# Review the result, then push + open a PR (or run the "Release" workflow with
# dry_run off). Pairs with tools/release_preview.sh (which writes nothing).
#
# Usage: tools/release_prepare.sh [bump]
#   bump: patch | minor | major | stable | alpha | beta | rc   (default: patch)
set -euo pipefail

BUMP="${1:-patch}"

if ! git diff --quiet || ! git diff --cached --quiet; then
	echo "✖ working tree is not clean — commit or stash first." >&2
	exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "${CURRENT_BRANCH}" != "main" ]; then
	printf '⚠ not on main (on "%s"). Continue anyway? [y/N] ' "${CURRENT_BRANCH}"
	read -r reply
	case "${reply}" in [yY]*) ;; *) echo "aborted." >&2; exit 1 ;; esac
fi

NEW_VERSION="$(uv version --dry-run --bump "${BUMP}" --output-format json \
	| python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
TAG="v${NEW_VERSION}"

if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null 2>&1; then
	echo "✖ tag ${TAG} already exists." >&2
	exit 1
fi
if git show-ref -q --verify "refs/heads/${TAG}"; then
	echo "✖ branch ${TAG} already exists." >&2
	exit 1
fi

echo "→ preparing ${TAG} (bump: ${BUMP}) on a new branch — nothing will be pushed"
git switch -c "${TAG}"
uv version --bump "${BUMP}" --no-sync
uvx --from 'towncrier>=24,<26' towncrier build --yes --version "${NEW_VERSION}"

# Pre-releases keep their own section; at a FINAL release, fold the pre-release
# sections (aN/bN/rcN/.devN) of this version into a single consolidated section.
if printf '%s' "${NEW_VERSION}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(\.post[0-9]+)?$'; then
	python3 tools/consolidate_prereleases.py "${NEW_VERSION}"
fi

git commit -am "chore(release): prepare release ${TAG}"

cat <<EOF

✅ Prepared ${TAG} on branch ${TAG} — nothing pushed.

Next:
  git push origin ${TAG}
  gh pr create --base main --title "chore(release): ${TAG}"
  # after the PR is merged:
  python tools/prepare_release.py ${NEW_VERSION} --create-draft-release
  # then click "Publish" on the draft release  ->  publish.yml  ->  PyPI

(Or skip all of the above and just run the "Release" workflow with dry_run off.)
EOF
