"""Tests for scripts/build_well_known.py."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

from helpers import ROOT, captured


def load_builder():
    spec = importlib.util.spec_from_file_location("build_well_known", os.path.join(ROOT, "scripts", "build_well_known.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WellKnownTests(unittest.TestCase):
    def setUp(self):
        self.builder = load_builder()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, ".well-known", "skills")

    def build(self, *argv):
        with captured() as (out, err):
            code = self.builder.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_index_lists_every_skill_with_its_files(self):
        code, _out, err = self.build("--out", self.out)
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.out, "index.json"), encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertEqual(set(index), {"skills"}, "legacy format: no $schema key")
        names = [s["name"] for s in index["skills"]]
        self.assertEqual(names, sorted(os.listdir(os.path.join(ROOT, "skills"))))
        for entry in index["skills"]:
            self.assertEqual(entry["files"][0], "SKILL.md")
            self.assertTrue(entry["description"])
            for rel in entry["files"]:
                self.assertFalse(rel.startswith(".") or "__pycache__" in rel)
                served = os.path.join(self.out, entry["name"], *rel.split("/"))
                source = os.path.join(ROOT, "skills", entry["name"], *rel.split("/"))
                with open(served, "rb") as a, open(source, "rb") as b:
                    self.assertEqual(a.read(), b.read())
        image = [s for s in index["skills"] if s["name"] == "empiriolabs-image"][0]
        self.assertEqual(image["files"], ["SKILL.md", "scripts/empiriolabs_api.py", "scripts/image.py"])

    def test_check_detects_drift_and_rewrite_removes_stale_files(self):
        self.assertEqual(self.build("--out", self.out)[0], 0)
        self.assertEqual(self.build("--check", self.out)[0], 0)
        stale = os.path.join(self.out, "retired-skill", "SKILL.md")
        os.makedirs(os.path.dirname(stale))
        with open(stale, "w") as handle:
            handle.write("old")
        code, _out, err = self.build("--check", self.out)
        self.assertEqual(code, 1)
        self.assertIn("retired-skill/SKILL.md", err)
        self.assertEqual(self.build("--out", self.out)[0], 0)
        self.assertFalse(os.path.exists(os.path.dirname(stale)))
        self.assertEqual(self.build("--check", self.out)[0], 0)

    def test_refuses_to_overwrite_an_unrelated_directory(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "keep.txt"), "w") as handle:
            handle.write("not ours")
        code, _out, err = self.build("--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("refusing", err)
        self.assertTrue(os.path.exists(os.path.join(self.out, "keep.txt")))

    def test_frontmatter_reader(self):
        fields = self.builder.frontmatter_fields(os.path.join(ROOT, "skills", "empiriolabs-video", "SKILL.md"))
        self.assertEqual(fields["name"], "empiriolabs-video")
        self.assertTrue(fields["description"].startswith("Generate short videos"))

    def test_committed_index_matches_a_fresh_build(self):
        # empiriolabs.ai serves this committed file at /.well-known/skills/index.json.
        committed = os.path.join(ROOT, ".well-known", "skills", "index.json")
        fresh = os.path.join(self.tmp.name, "index.json")
        self.assertEqual(self.build("--index", fresh)[0], 0)
        with open(committed, "rb") as a, open(fresh, "rb") as b:
            self.assertEqual(a.read(), b.read(),
                             "run: python scripts/build_well_known.py --index .well-known/skills/index.json")


if __name__ == "__main__":
    unittest.main()
