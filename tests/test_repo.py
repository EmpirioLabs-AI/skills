"""Repository checks: skill format, env declarations, manifests, vendored copies, and text rules."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import unittest

from helpers import ROOT, SKILLS, read_frontmatter

SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Hermes Agent reads required environment variables from this top-level key (secure prompt on
# load, passthrough into sandboxes). It is the one key outside the Agent Skills field list.
EXTENSION_FIELDS = {"required_environment_variables"}
KEY_ENV = "EMPIRIOLABS_API_KEY"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MANIFESTS = ["plugin.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"]


def skill_names():
    return sorted(n for n in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, n, "SKILL.md")))


def load_json(rel):
    with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as handle:
        return json.load(handle)


def text_files():
    for current, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith((".md", ".py", ".json", ".txt", ".yml", ".yaml")) or name in ("LICENSE", ".gitignore"):
                yield os.path.join(current, name)


class SkillFormatTests(unittest.TestCase):
    def test_every_skill_follows_the_agent_skills_rules(self):
        names = skill_names()
        self.assertEqual(names, ["empiriolabs-image", "empiriolabs-models", "empiriolabs-speech",
                                 "empiriolabs-transcribe", "empiriolabs-video"])
        for name in names:
            fm, raw, body = read_frontmatter(os.path.join(SKILLS, name, "SKILL.md"))
            with self.subTest(skill=name):
                self.assertEqual(fm["name"], name, "name must match the folder")
                self.assertRegex(name, NAME_RE)
                self.assertLessEqual(len(name), 64)
                self.assertTrue(0 < len(fm["description"]) <= 1024)
                self.assertIn("Use when", fm["description"], "descriptions say when to use the skill")
                self.assertLessEqual(len(fm["compatibility"]), 500)
                self.assertEqual(fm["license"], "MIT-0")
                self.assertLessEqual(set(fm) - SPEC_FIELDS, EXTENSION_FIELDS)
                self.assertNotRegex(raw, r":\s*\[", "block-style YAML only (strict parsers reject flow style)")
                self.assertNotRegex(raw, r":\s*\{", "block-style YAML only (strict parsers reject flow style)")
                self.assertLess(len(body.splitlines()), 500, "keep SKILL.md under 500 lines")
                for ref in re.findall(r"scripts/[\w.-]+\.py", body):
                    self.assertTrue(os.path.isfile(os.path.join(SKILLS, name, ref)), name + " references " + ref)

    def test_env_declarations_match_what_the_scripts_use(self):
        for name in skill_names():
            folder = os.path.join(SKILLS, name)
            uses_key = os.path.isfile(os.path.join(folder, "scripts", "empiriolabs_api.py"))
            fm, _raw, _body = read_frontmatter(os.path.join(folder, "SKILL.md"))
            claw = fm["metadata"]["openclaw"]
            bins = claw["requires"]["anyBins"]
            with self.subTest(skill=name):
                self.assertEqual(bins, ["python3", "python"])
                if uses_key:
                    self.assertEqual(claw["primaryEnv"], KEY_ENV)
                    self.assertEqual(claw["requires"]["env"], [KEY_ENV])
                    self.assertEqual([(v["name"], v["required"]) for v in claw["envVars"]], [(KEY_ENV, True)])
                    self.assertEqual([v["name"] for v in fm["required_environment_variables"]], [KEY_ENV])
                    self.assertIn(KEY_ENV, fm["compatibility"])
                else:
                    self.assertNotIn("env", claw["requires"])
                    self.assertNotIn("required_environment_variables", fm)
                    for current, _dirs, files in os.walk(folder):
                        for fname in files:
                            if fname.endswith(".py"):
                                with open(os.path.join(current, fname), encoding="utf-8") as handle:
                                    self.assertNotIn(KEY_ENV, handle.read(), name + " must not read a key it does not declare")

    def test_skill_markdown_never_interpolates_a_secret_into_a_command(self):
        pattern = re.compile(r"(curl|wget)\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
        for name in skill_names():
            with open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8") as handle:
                self.assertIsNone(pattern.search(handle.read()), name)

    def test_vendored_clients_match_the_shared_source(self):
        result = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "sync_shared.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ManifestTests(unittest.TestCase):
    def test_manifests_agree(self):
        manifests = {rel: load_json(rel) for rel in MANIFESTS}
        for field in ("name", "version", "description", "license", "repository", "homepage", "keywords"):
            values = {json.dumps(m.get(field)) for m in manifests.values()}
            self.assertEqual(len(values), 1, field + " differs between " + ", ".join(MANIFESTS))
        self.assertEqual(manifests["plugin.json"]["name"], "empiriolabs")
        self.assertEqual(manifests["plugin.json"]["license"], "MIT-0")
        portable = manifests["plugin.json"]
        self.assertEqual(portable["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertLessEqual(set(portable), {"$schema", "name", "version", "description", "author", "homepage",
                                             "repository", "license", "keywords", "extensions"})
        interface = portable["extensions"]["com.openai"]["interface"]
        self.assertLessEqual(len(interface["displayName"]), 30)
        self.assertLessEqual(len(interface["shortDescription"]), 30)
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all(len(p) <= 128 for p in interface["defaultPrompt"]))
        for rel in (interface["logo"], interface["composerIcon"], manifests[".claude-plugin/plugin.json"]["icon"],
                    manifests[".cursor-plugin/plugin.json"]["logo"]):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel.lstrip("./"))), rel)

    def test_marketplaces_point_at_this_plugin(self):
        name = load_json("plugin.json")["name"]
        claude = load_json(".claude-plugin/marketplace.json")
        self.assertEqual([(p["name"], p["source"]) for p in claude["plugins"]], [(name, "./")])
        self.assertTrue(claude["owner"]["name"])
        codex = load_json(".agents/plugins/marketplace.json")
        self.assertEqual(codex["name"], claude["name"])
        entry = codex["plugins"][0]
        self.assertEqual((entry["name"], entry["source"]["path"]), (name, "./"))
        self.assertTrue(entry["policy"]["installation"] and entry["policy"]["authentication"] and entry["category"])

    def test_skills_sh_groupings_cover_every_skill_once(self):
        groups = load_json("skills.sh.json")["groupings"]
        listed = [s for g in groups for s in g["skills"]]
        self.assertEqual(sorted(listed), skill_names())
        self.assertEqual(len(listed), len(set(listed)))


class TextTests(unittest.TestCase):
    def test_files_are_ascii_without_em_dashes(self):
        for path in text_files():
            with open(path, "rb") as handle:
                data = handle.read()
            rel = os.path.relpath(path, ROOT)
            with self.subTest(file=rel):
                self.assertNotIn(b"\xe2\x80\x94", data, "no em dashes (U+2014)")
                self.assertTrue(all(b < 128 for b in data), rel + " has non-ASCII characters")
                self.assertNotIn(b"\r\n", data, rel + " must use LF line endings")

    def test_python_files_parse_as_python_3_8(self):
        for path in text_files():
            if path.endswith(".py"):
                with open(path, encoding="utf-8") as handle:
                    ast.parse(handle.read(), filename=path, feature_version=(3, 8))

    def test_scripts_use_only_the_standard_library(self):
        allowed = set(getattr(sys, "stdlib_module_names", ())) | {"empiriolabs_api", "__future__"}
        if not getattr(sys, "stdlib_module_names", None):
            self.skipTest("needs Python 3.10+ to list standard library modules")
        for name in skill_names():
            scripts = os.path.join(SKILLS, name, "scripts")
            for fname in os.listdir(scripts):
                if not fname.endswith(".py"):
                    continue
                with open(os.path.join(scripts, fname), encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        mods = [node.module]
                    for mod in mods:
                        self.assertIn(mod.split(".")[0], allowed, name + "/" + fname + " imports " + mod)

    def test_readme_covers_every_skill_and_client(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        for name in skill_names():
            self.assertIn(name, readme)
        for needle in ("npx skills add EmpirioLabs-AI/skills", "clawhub install", "hermes skills install",
                       "/plugin marketplace add EmpirioLabs-AI/skills", "codex plugin marketplace add",
                       "MIT-0", "https://docs.empiriolabs.ai", "https://empiriolabs.ai"):
            self.assertIn(needle, readme)

    def test_scripts_print_help(self):
        for name in skill_names():
            scripts = os.path.join(SKILLS, name, "scripts")
            for fname in os.listdir(scripts):
                if fname.endswith(".py") and fname != "empiriolabs_api.py":
                    result = subprocess.run([sys.executable, "-B", os.path.join(scripts, fname), "--help"],
                                            capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                    self.assertEqual(result.returncode, 0, fname + result.stderr)
                    self.assertIn("usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
