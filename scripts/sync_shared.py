#!/usr/bin/env python3
"""Copy shared/empiriolabs_api.py into every skill whose scripts import it.

Each skill must work on its own after it is installed (ClawHub, Hermes, and
skills.sh install one skill folder at a time), so the client is vendored into
skills/<name>/scripts/. shared/empiriolabs_api.py is the only copy to edit.

Usage:
  python scripts/sync_shared.py          write the copies
  python scripts/sync_shared.py --check  exit 1 when any copy is missing or differs

Exit codes: 0 in sync (or written), 1 drift found by --check, 2 could not run.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "shared", "empiriolabs_api.py")
SKILLS = os.path.join(ROOT, "skills")
MODULE = "empiriolabs_api"


def consumers():
    """Skill folders whose own scripts import the shared module."""
    found = []
    for name in sorted(os.listdir(SKILLS)):
        scripts = os.path.join(SKILLS, name, "scripts")
        if not os.path.isdir(scripts):
            continue
        for entry in sorted(os.listdir(scripts)):
            if not entry.endswith(".py") or entry == MODULE + ".py":
                continue
            with open(os.path.join(scripts, entry), "r", encoding="utf-8") as handle:
                text = handle.read()
            if "import " + MODULE in text:
                found.append(scripts)
                break
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Report drift without writing.")
    args = parser.parse_args(argv)
    try:
        with open(SOURCE, "rb") as handle:
            source = handle.read()
        targets = consumers()
    except OSError as exc:
        print("sync_shared: could not run: " + str(exc), file=sys.stderr)
        return 2
    if not targets:
        print("sync_shared: no skill imports " + MODULE, file=sys.stderr)
        return 2
    drift = []
    for scripts in targets:
        path = os.path.join(scripts, MODULE + ".py")
        current = None
        if os.path.exists(path):
            with open(path, "rb") as handle:
                current = handle.read()
        if current == source:
            continue
        drift.append(os.path.relpath(path, ROOT))
        if not args.check:
            with open(path, "wb") as handle:
                handle.write(source)
    if args.check:
        if drift:
            print("sync_shared: out of date: " + ", ".join(drift)
                  + ". Run python scripts/sync_shared.py.", file=sys.stderr)
            return 1
        print("sync_shared: " + str(len(targets)) + " copies match shared/" + MODULE + ".py")
        return 0
    print("sync_shared: wrote " + str(len(drift)) + " of " + str(len(targets)) + " copies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
