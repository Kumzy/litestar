"""Fold pre-release changelog sections into the final version's section.

At a FINAL release, towncrier has just created a ``.. changelog:: <final>`` section from
the fragments accumulated since the last pre-release. This merges the ``.. change::``
blocks from every section of the same release line — the final itself plus any
``<final>aN`` / ``<final>bN`` / ``<final>rcN`` / ``<final>.devN`` pre-releases — into a
single ``.. changelog:: <final>`` section, and removes the separate pre-release sections.

The Sphinx ``changelog`` directive regroups changes by ``:type:`` at render time, so the
order in which the blocks are concatenated does not affect the rendered page.

Usage: python tools/consolidate_prereleases.py <final_version>     e.g. 3.0.0
"""

from __future__ import annotations

import pathlib
import re
import sys

CHANGELOG = pathlib.Path("docs/release-notes/changelog.rst")
_HEADER = re.compile(r"^\.\. changelog:: (?P<version>\S+)\s*$")


def _same_line(version: str, final: str) -> bool:
    # the final itself, or a PEP 440 pre-release of it (aN / bN / rcN / .devN)
    return version == final or re.fullmatch(rf"{re.escape(final)}(?:(?:a|b|rc)\d+|\.dev\d+)", version) is not None


def consolidate(text: str, final: str) -> str:
    lines = text.split("\n")
    headers = [(i, m.group("version")) for i, line in enumerate(lines) if (m := _HEADER.match(line))]
    if not headers:
        return text

    spans = []  # (version, start, end-exclusive)
    for k, (start, version) in enumerate(headers):
        end = headers[k + 1][0] if k + 1 < len(headers) else len(lines)
        spans.append((version, start, end))

    line_spans = [(v, s, e) for (v, s, e) in spans if _same_line(v, final)]
    if len(line_spans) < 2:
        return text  # nothing to merge (towncrier inserts newest first, so these are contiguous)

    first, last = line_spans[0][1], line_spans[-1][2]
    date = ""
    change_blocks: list[str] = []
    for version, s, e in line_spans:
        body = lines[s + 1 : e]
        i = 0
        while i < len(body) and (body[i].strip().startswith(":date:") or body[i].strip() == ""):
            if body[i].strip().startswith(":date:"):
                d = body[i].strip()[len(":date:") :].strip()
                if version == final or not date:
                    date = d
            i += 1
        block = body[i:]
        while block and block[-1].strip() == "":
            block.pop()
        if block:
            change_blocks.extend(block)
            change_blocks.append("")  # separator between merged sections

    while change_blocks and change_blocks[-1].strip() == "":
        change_blocks.pop()

    merged = [f".. changelog:: {final}"]
    if date:
        merged.append(f"    :date: {date}")
    merged.append("")
    merged.extend(change_blocks)
    merged.append("")

    return "\n".join(lines[:first] + merged + lines[last:])


def main(final: str) -> int:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.post\d+)?", final):
        print(f"refusing to consolidate into non-final version {final!r}", file=sys.stderr)  # noqa: T201
        return 1
    text = CHANGELOG.read_text()
    new = consolidate(text, final)
    if new != text:
        CHANGELOG.write_text(new)
        print(f"Consolidated pre-release sections into '.. changelog:: {final}'")  # noqa: T201
    else:
        print(f"No pre-release sections to consolidate for {final}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
