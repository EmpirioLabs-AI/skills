"""Tests for skills/empiriolabs-search/scripts/search.py (no network)."""

from __future__ import annotations

import json
import unittest

from helpers import API, json_response
from script_case import ScriptCase

RESULTS = {"object": "search", "model": "plain-search", "query": "python release",
           "results": [{"title": "Python downloads", "url": "https://example.com/downloads",
                        "content": "The   newest release\nis listed first."},
                       {"title": "", "url": "https://example.com/news", "text": "x" * 400}],
           "usage": {"cost_usd": 0.01}}
ANSWERED = {"object": "search", "model": "answer-engine", "query": "who maintains it",
            "answer": "A foundation maintains it [1].",
            "results": [{"title": "Governance", "url": "https://example.com/governance"}]}
REPORT = {"object": "search", "model": "deep-research", "query": "batteries",
          "answer": "# Report\n\nSolid-state cells are improving [1].",
          "results": [{"title": "Lab note", "url": "https://example.com/lab", "content": None},
                      {"title": "Review", "url": "https://example.com/review", "content": None}]}


class SearchTests(ScriptCase):
    skill = "empiriolabs-search"
    script = "search"

    def test_a_search_uses_a_search_only_model_and_prints_numbered_results(self):
        routes = [("POST", API + "/search", json_response(RESULTS))]
        self.assertEqual(self.run_script(routes, ["python release", "--param", "num_results=2"]), 0, self.stderr)
        body = self.transport.json_body("POST", API + "/search")
        self.assertEqual(body, {"model": "plain-search", "query": "python release", "num_results": 2})
        lines = self.stdout.splitlines()
        self.assertEqual(lines[0:3], ["1. Python downloads", "   https://example.com/downloads",
                                      "   The newest release is listed first."])
        self.assertEqual(lines[3:5], ["2. https://example.com/news", "   https://example.com/news"])
        self.assertEqual(lines[5], "   " + "x" * 320 + "...")

    def test_an_answer_comes_with_its_sources(self):
        routes = [("POST", API + "/answer", json_response(ANSWERED))]
        self.assertEqual(self.run_script(routes, ["who maintains it", "--answer"]), 0, self.stderr)
        self.assertEqual(self.transport.json_body("POST", API + "/answer"),
                         {"model": "answer-engine", "query": "who maintains it"})
        self.assertEqual(self.stdout, "A foundation maintains it [1].\n\nSources:\n1. Governance\n"
                                      "   https://example.com/governance\n")

    def test_a_research_report_is_saved_with_a_summary(self):
        routes = [("POST", API + "/research", json_response(REPORT))]
        out = self.path("reports", "batteries.md")
        self.assertEqual(self.run_script(routes, ["batteries", "--research", "--out", out]), 0, self.stderr)
        self.assertEqual(self.transport.json_body("POST", API + "/research"),
                         {"model": "deep-research", "query": "batteries", "stream": False})
        self.assertEqual(self.summary(), {"model": "deep-research", "file": out, "sources": 2,
                                          "characters": len("# Report\n\nSolid-state cells are improving [1].")})
        with open(out, encoding="utf-8") as handle:
            saved = handle.read()
        self.assertTrue(saved.startswith("# Report\n\nSolid-state cells are improving [1].\n\nSources:\n1. Lab note\n"))
        self.assertIn("several minutes", self.stderr)

    def test_json_prints_the_full_result_and_a_json_path_saves_it(self):
        routes = [("POST", API + "/search", json_response(RESULTS))]
        self.assertEqual(self.run_script(routes, ["python release", "--json"]), 0, self.stderr)
        self.assertEqual(json.loads(self.stdout)["results"][0]["url"], "https://example.com/downloads")
        out = self.path("results.json")
        self.assertEqual(self.run_script(routes, ["python release", "--out", out]), 0, self.stderr)
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["model"], "plain-search")

    def test_a_named_model_is_used_as_given(self):
        routes = [("POST", API + "/search", json_response(RESULTS))]
        self.assertEqual(self.run_script(routes, ["python release", "--model", "answer-engine"]), 0, self.stderr)
        self.assertEqual(self.transport.json_body("POST", API + "/search")["model"], "answer-engine")

    def test_a_model_of_another_mode_is_refused(self):
        self.assertEqual(self.run_script([], ["batteries", "--research", "--model", "plain-search"]), 2)
        self.assertIn("does not support POST /v1/research", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_a_refused_request_exits_1(self):
        error = json_response({"error": {"message": "Insufficient credits.", "code": "insufficient_credits"}},
                              status=402)
        self.assertEqual(self.run_script([("POST", API + "/search", error)], ["python release"]), 1)
        self.assertIn("Insufficient credits", self.stderr)

    def test_list_models_marks_the_default_of_each_mode(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* plain-search", self.stdout)
        self.assertIn("  answer-engine", self.stdout)
        self.assertEqual(self.run_script([], ["--list-models", "--research"]), 0)
        self.assertIn("* deep-research", self.stdout)
        self.assertNotIn("plain-search", self.stdout)


if __name__ == "__main__":
    unittest.main()
