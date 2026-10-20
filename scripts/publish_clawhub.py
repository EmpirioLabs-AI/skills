#!/usr/bin/env python3
"""Publish each skill to ClawHub when its SKILL.md version is not there yet.

The version comes from the skill's own SKILL.md (`metadata.version`), and the
listing fields (display name, categories, topics) from clawhub.json, so this
repository stays the one source for what ClawHub shows. A version that is
already published is skipped, so the script is safe to run on every push.

Usage (the ClawHub CLI must already be logged in):
  python scripts/publish_clawhub.py [--dry-run] [--clawhub "npx -y clawhub@0.23.3"]

Source provenance comes from GITHUB_REPOSITORY, GITHUB_SHA and GITHUB_REF_NAME
when they are set (GitHub Actions), or from --source-commit and --source-ref.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
VERSION_RE = re.compile(r'^\s+version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$', re.M)


def skill_version(name):
    with open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8") as handle:
        text = handle.read()
    frontmatter = text.split("---", 2)[1]
    match = VERSION_RE.search(frontmatter)
    if not match:
        raise SystemExit(f"{name}: SKILL.md has no metadata version")
    return match.group(1)


def published_versions(cli, owner, name):
    result = subprocess.run(cli + ["inspect", f"@{owner}/{name}", "--versions", "--json"],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        if "not found" in (result.stdout + result.stderr).lower():
            return set()
        raise SystemExit(f"{name}: could not read ClawHub versions: {result.stderr.strip()[-300:]}")
    data = json.loads(result.stdout)
    return {item.get("version") for item in (data.get("versions") or []) if isinstance(item, dict)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clawhub", default="clawhub", help="Command that runs the ClawHub CLI.")
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--source-ref", default=os.environ.get("GITHUB_REF_NAME", "main"))
    parser.add_argument("--source-repo", default=os.environ.get("GITHUB_REPOSITORY", "EmpirioLabs-AI/skills"))
    args = parser.parse_args(argv)
    cli = shlex.split(args.clawhub)
    with open(os.path.join(ROOT, "clawhub.json"), encoding="utf-8") as handle:
        config = json.load(handle)
    owner = config["owner"]
    on_disk = sorted(d for d in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))
    missing = [name for name in on_disk if name not in config["skills"]]
    if missing:
        raise SystemExit("clawhub.json has no listing for: " + ", ".join(missing))
    published = 0
    for name in on_disk:
        listing = config["skills"][name]
        version = skill_version(name)
        if version in published_versions(cli, owner, name):
            print(f"{name} {version}: already on ClawHub")
            continue
        command = cli + [
            "skill", "publish", os.path.join(SKILLS, name),
            "--slug", name,
            "--name", listing["name"],
            "--owner", owner,
            "--version", version,
            "--categories", ",".join(listing["categories"]),
            "--topics", ",".join(listing["topics"]),
            "--changelog", f"Version {version}. Changes: https://github.com/{args.source_repo}/commits/{args.source_ref}/skills/{name}",
            "--source-repo", args.source_repo,
            "--source-ref", args.source_ref,
            "--source-path", f"skills/{name}",
        ]
        if args.source_commit:
            command += ["--source-commit", args.source_commit]
        if args.dry_run:
            command.append("--dry-run")
        print(f"{name} {version}: publishing" + (" (dry run)" if args.dry_run else ""))
        result = subprocess.run(command, text=True, encoding="utf-8")
        if result.returncode != 0:
            return result.returncode
        published += 1
    print(f"published {published} skill version(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
