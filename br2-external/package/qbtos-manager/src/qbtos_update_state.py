#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run qbtOS state migration before network-facing services start."""

import sys

import qbtos_update


def main():
    if sys.argv[1:] != ["migrate"]:
        print("usage: qbtos-update-state migrate", file=sys.stderr)
        return 2
    try:
        qbtos_update.migrate_state(qbtos_update.target_schema())
    except qbtos_update.UpdateError as error:
        print(f"qbtOS state migration failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
