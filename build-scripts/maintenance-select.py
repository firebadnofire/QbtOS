#!/usr/bin/env python3
"""Select final upstream tags and validate revision names (stdin is fixture friendly)."""

import re
import sys

PATTERNS = {
    "buildroot": re.compile(r"^(20[0-9]{2})\.([0-9]{2})(?:\.([0-9]+))?$"),
    "qbittorrent": re.compile(r"^release-([1-9][0-9]*)\.([0-9]+)\.([0-9]+)(?:\.([0-9]+))?$"),
}
REVISION = re.compile(r"^revision-([1-9][0-9]*)$")


def select(kind, lines):
    pattern = PATTERNS[kind]
    candidates = []
    for line in lines:
        fields = line.strip().split("\t")
        if len(fields) == 1:
            tag = fields[0]
        elif len(fields) == 2 and fields[1].startswith("refs/tags/"):
            tag = fields[1][len("refs/tags/"):]
        else:
            continue
        if tag.endswith("^{}"):
            tag = tag[:-3]
        match = pattern.fullmatch(tag)
        if match:
            candidates.append((tuple(int(part or 0) for part in match.groups()), tag))
    if not candidates:
        raise ValueError(f"no stable final {kind} release tags found")
    return max(candidates)[1]


def next_revision(tags):
    highest = 0
    for tag in tags:
        tag = tag.strip()
        if tag.startswith(("revision-", "revsion-")):
            match = REVISION.fullmatch(tag)
            if not match:
                raise ValueError(f"invalid revision tag: {tag}")
            highest = max(highest, int(match.group(1)))
    return f"revision-{highest + 1}"


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: maintenance-select.py buildroot|qbittorrent|revision")
        if sys.argv[1] == "revision":
            print(next_revision(sys.stdin))
        elif sys.argv[1] in PATTERNS:
            print(select(sys.argv[1], sys.stdin))
        else:
            raise ValueError("unknown selector")
    except ValueError as exc:
        print(f"maintenance-select: {exc}", file=sys.stderr)
        sys.exit(2)
