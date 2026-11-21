#!/usr/bin/env python3
"""Build the well-known trees that publish these skills from a website.

Two formats, both served by empiriolabs.ai from this repository's main branch:

/.well-known/agent-skills/ (Agent Skills Discovery v0.2.0, read first by the skills CLI):
  index.json  {"$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
               "skills": [{"name", "type": "archive", "description", "url": "<name>.zip",
                           "digest": "sha256:<hex>"}]}
  <name>.zip  the skill's files at the archive root, stored without compression and with fixed
              metadata, so the same files always give the same bytes and the same digest.

/.well-known/skills/ (the earlier format that Hermes Agent reads,
`hermes skills install well-known:https://site/.well-known/skills/<skill>`):
  index.json  {"skills": [{"name": "...", "description": "...", "files": ["SKILL.md", ...]}]}
  plus every listed file at <skill>/<path>.

Usage:
  python scripts/build_well_known.py --publish    # after changing a skill
  python scripts/build_well_known.py --out path/to/site/.well-known/skills
  python scripts/build_well_known.py --check path/to/site/.well-known/skills
  python scripts/build_well_known.py --index .well-known/skills/index.json
  python scripts/build_well_known.py --agent-skills path/to/site/.well-known/agent-skills
  python scripts/build_well_known.py --check-agent-skills path/to/site/.well-known/agent-skills

--publish writes what this repository commits: .well-known/skills/index.json (empiriolabs.ai serves
each listed file from skills/<skill>/<file>) and the whole .well-known/agent-skills/ tree.
tests/test_build_well_known.py fails when either is out of date. --out and --agent-skills write a
complete tree for a site that hosts its own copy.

Exit codes: 0 written or in sync, 1 a check found drift or a skill is invalid, 2 could not run.
Python 3.8+, standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
LEGACY_INDEX = os.path.join(ROOT, ".well-known", "skills", "index.json")
AGENT_SKILLS_DIR = os.path.join(ROOT, ".well-known", "agent-skills")
AGENT_SKILLS_SCHEMA = "https://schemas.agentskills.io/discovery/0.2.0/schema.json"
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


def collect():
    """([{name, description, files}], {"<skill>/<file>": source_path}) for every skill."""
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
    return entries, sources


def plan():
    """(legacy index.json bytes, {"<skill>/<file>": source_path})."""
    entries, sources = collect()
    index = json.dumps({"skills": entries}, indent=2, ensure_ascii=False) + "\n"
    return index.encode("utf-8"), sources


def stored_zip(members):
    """ZIP bytes for [(path, data)]: no compression, dated 1980-01-01, regular files with mode 0644, made on
    Unix. Nothing depends on the clock, the platform or the zlib build, so equal files give equal bytes."""
    local = []
    central = []
    offset = 0
    for path, data in members:
        name = path.encode("utf-8")
        flags = 0 if all(byte < 128 for byte in name) else 0x800
        crc = zlib.crc32(data) & 0xFFFFFFFF
        size = len(data)
        header = struct.pack("<IHHHHHIIIHH", 0x04034B50, 10, flags, 0, 0, 0x21, crc, size, size, len(name), 0)
        central.append(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 0x0314, 10, flags, 0, 0, 0x21, crc, size, size,
                                   len(name), 0, 0, 0, 0, 0o100644 << 16, offset) + name)
        local.append(header + name + data)
        offset += len(header) + len(name) + size
    directory = b"".join(central)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(members), len(members), len(directory), offset, 0)
    return b"".join(local) + directory + end


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def legacy_tree():
    """{relative path: bytes} for /.well-known/skills/: index.json plus every listed file."""
    index, sources = plan()
    files = {rel: read(src) for rel, src in sources.items()}
    files["index.json"] = index
    return files


def agent_skills_tree():
    """{relative path: bytes} for /.well-known/agent-skills/: index.json plus one archive per skill."""
    entries, sources = collect()
    files = {}
    skills = []
    for entry in entries:
        name = entry["name"]
        archive = stored_zip([(rel, read(sources[name + "/" + rel])) for rel in entry["files"]])
        files[name + ".zip"] = archive
        skills.append({"name": name, "type": "archive", "description": entry["description"], "url": name + ".zip",
                       "digest": "sha256:" + hashlib.sha256(archive).hexdigest()})
    index = json.dumps({"$schema": AGENT_SKILLS_SCHEMA, "skills": skills}, indent=2, ensure_ascii=False) + "\n"
    files["index.json"] = index.encode("utf-8")
    return files


def existing_files(out):
    found = set()
    for current, _dirs, names in os.walk(out):
        for name in names:
            found.add(os.path.relpath(os.path.join(current, name), out).replace(os.sep, "/"))
    return found


def check_tree(out, files):
    problems = []
    for rel, data in sorted(files.items(), key=lambda item: (item[0] != "index.json", item[0])):
        target = os.path.join(out, *rel.split("/"))
        if not os.path.isfile(target) or read(target) != data:
            problems.append(rel)
    extra = existing_files(out) - set(files) if os.path.isdir(out) else set()
    problems.extend(sorted(e + " (not in the build)" for e in extra))
    return problems


def write_tree(out, files):
    if os.path.isdir(out) and os.listdir(out) and not os.path.isfile(os.path.join(out, "index.json")):
        raise BuildError(out + " is not empty and has no index.json; refusing to replace its contents")
    os.makedirs(out, exist_ok=True)
    for rel in sorted(existing_files(out) - set(files)):
        os.remove(os.path.join(out, *rel.split("/")))
    for current, dirs, _names in os.walk(out, topdown=False):
        for d in dirs:
            path = os.path.join(current, d)
            if not os.listdir(path):
                os.rmdir(path)
    for rel, data in sorted(files.items()):
        target = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)


def write_file(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--publish", action="store_true",
                       help="Write .well-known/skills/index.json and .well-known/agent-skills/ in this repository.")
    group.add_argument("--out", help="Directory to write (served as /.well-known/skills/).")
    group.add_argument("--check", metavar="DIR", help="Compare DIR with a fresh /.well-known/skills/ build.")
    group.add_argument("--index", metavar="FILE", help="Write only the /.well-known/skills/ index.json to FILE.")
    group.add_argument("--agent-skills", metavar="DIR", help="Directory to write (served as /.well-known/agent-skills/).")
    group.add_argument("--check-agent-skills", metavar="DIR",
                       help="Compare DIR with a fresh /.well-known/agent-skills/ build.")
    args = parser.parse_args(argv)
    try:
        if args.out or args.check:
            files = legacy_tree()
        elif args.index:
            files = {"index.json": plan()[0]}
        else:
            files = agent_skills_tree()
            if args.publish:
                legacy_index = plan()[0]
    except (BuildError, OSError) as exc:
        print("build_well_known: " + str(exc), file=sys.stderr)
        return 1 if isinstance(exc, BuildError) else 2
    if args.check or args.check_agent_skills:
        target = args.check or args.check_agent_skills
        problems = check_tree(os.path.abspath(target), files)
        if problems:
            print("build_well_known: out of date: " + ", ".join(problems), file=sys.stderr)
            return 1
        print("build_well_known: " + target + " matches " + str(len(files)) + " files")
        return 0
    try:
        if args.index:
            write_file(args.index, files["index.json"])
            print("build_well_known: wrote " + args.index)
            return 0
        if args.publish:
            write_file(LEGACY_INDEX, legacy_index)
            write_tree(AGENT_SKILLS_DIR, files)
            print("build_well_known: wrote .well-known/skills/index.json and " + str(len(files) - 1)
                  + " archives with index.json to .well-known/agent-skills")
            return 0
        out = args.out or args.agent_skills
        write_tree(os.path.abspath(out), files)
    except (BuildError, OSError) as exc:
        print("build_well_known: " + str(exc), file=sys.stderr)
        return 2
    print("build_well_known: wrote " + str(len(files)) + " files to " + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
