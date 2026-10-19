#!/usr/bin/env python3
"""Build the /.well-known/skills/ tree that publishes these skills from a website.

Writes OUT/index.json plus a copy of every skill file at OUT/<skill>/<path>, in the
well-known skills index format that Hermes Agent (`hermes skills install
well-known:https://site/.well-known/skills/<skill>`) and the skills CLI
(`npx skills add https://site`) read:

  {"skills": [{"name": "...", "description": "...", "files": ["SKILL.md", ...]}]}

Serve OUT at https://<site>/.well-known/skills/ so that index.json and each listed
file resolve at https://<site>/.well-known/skills/<skill>/<file>.

Usage:
  python scripts/build_well_known.py --out path/to/site/.well-known/skills
  python scripts/build_well_known.py --check path/to/site/.well-known/skills

Exit codes: 0 written or in sync, 1 --check found drift or a skill is invalid, 2 could not run.
Python 3.8+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TEXT_SUFFIXES = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".sh"}
SKIP_DIRS = {"__pycache__"}


class BuildError(Exception):
    pass


def frontmatter_fields(path):
    """Top-level `key: value` scalars from a SKILL.md frontmatter block."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.startswith("---"):
        raise BuildError(path + ": missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end < 0:
        raise BuildError(path + ": frontmatter is not closed")
    fields = {}
    for line in text[3:end].splitlines():
        if not line or line[0] in " \t#-":
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if value in ("|", ">", "|-", ">-"):
            raise BuildError(path + ": " + key + " must be a single-line value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def skill_files(folder):
    """SKILL.md first, then every other text file, as sorted POSIX paths."""
    files = []
    for current, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(names):
            if name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(current, name), folder).replace(os.sep, "/")
            if rel == "SKILL.md":
                continue
            if os.path.splitext(name)[1].lower() not in TEXT_SUFFIXES:
                raise BuildError(folder + ": " + rel + " is not a text file; the well-known format serves text only")
            files.append(rel)
    return ["SKILL.md"] + sorted(files)


def plan():
    """[(entry, {relative_output_path: source_path})] for every skill."""
    entries = []
    sources = {}
    for name in sorted(os.listdir(SKILLS)):
        folder = os.path.join(SKILLS, name)
        skill_md = os.path.join(folder, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        fields = frontmatter_fields(skill_md)
        if fields.get("name") != name:
            raise BuildError(name + ": frontmatter name " + repr(fields.get("name")) + " must match the folder name")
        if not NAME_RE.match(name) or len(name) > 64:
            raise BuildError(name + ": names use 1-64 lowercase letters, digits, and single hyphens")
        description = fields.get("description") or ""
        if not description or len(description) > 1024:
            raise BuildError(name + ": description must be 1-1024 characters")
        files = skill_files(folder)
        entries.append({"name": name, "description": description, "files": files})
        for rel in files:
            sources[name + "/" + rel] = os.path.join(folder, *rel.split("/"))
    if not entries:
        raise BuildError("no skills found under " + SKILLS)
    index = json.dumps({"skills": entries}, indent=2, ensure_ascii=False) + "\n"
    return index.encode("utf-8"), sources


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def existing_files(out):
    found = set()
    for current, _dirs, names in os.walk(out):
        for name in names:
            found.add(os.path.relpath(os.path.join(current, name), out).replace(os.sep, "/"))
    return found


def check(out, index, sources):
    problems = []
    index_path = os.path.join(out, "index.json")
    if not os.path.isfile(index_path) or read(index_path) != index:
        problems.append("index.json")
    for rel, src in sorted(sources.items()):
        target = os.path.join(out, *rel.split("/"))
        if not os.path.isfile(target) or read(target) != read(src):
            problems.append(rel)
    extra = existing_files(out) - set(sources) - {"index.json"} if os.path.isdir(out) else set()
    problems.extend(sorted(e + " (not in the build)" for e in extra))
    return problems


def write(out, index, sources):
    if os.path.isdir(out) and os.listdir(out):
        previous = os.path.join(out, "index.json")
        if not os.path.isfile(previous):
            raise BuildError(out + " is not empty and has no index.json; refusing to replace its contents")
    os.makedirs(out, exist_ok=True)
    for rel in sorted(existing_files(out) - set(sources) - {"index.json"}):
        os.remove(os.path.join(out, *rel.split("/")))
    for current, dirs, _names in os.walk(out, topdown=False):
        for d in dirs:
            path = os.path.join(current, d)
            if not os.listdir(path):
                os.rmdir(path)
    for rel, src in sorted(sources.items()):
        target = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(src, target)
    with open(os.path.join(out, "index.json"), "wb") as handle:
        handle.write(index)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", help="Directory to write (served as /.well-known/skills/).")
    group.add_argument("--check", metavar="DIR", help="Compare DIR with a fresh build without writing.")
    args = parser.parse_args(argv)
    try:
        index, sources = plan()
    except (BuildError, OSError) as exc:
        print("build_well_known: " + str(exc), file=sys.stderr)
        return 1 if isinstance(exc, BuildError) else 2
    if args.check:
        problems = check(os.path.abspath(args.check), index, sources)
        if problems:
            print("build_well_known: out of date: " + ", ".join(problems), file=sys.stderr)
            return 1
        print("build_well_known: " + args.check + " matches " + str(len(sources)) + " files and index.json")
        return 0
    try:
        write(os.path.abspath(args.out), index, sources)
    except (BuildError, OSError) as exc:
        print("build_well_known: " + str(exc), file=sys.stderr)
        return 2
    count = json.loads(index.decode("utf-8"))["skills"]
    print("build_well_known: wrote index.json with " + str(len(count)) + " skills and "
          + str(len(sources)) + " files to " + args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
