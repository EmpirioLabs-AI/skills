"""Tests for skills/empiriolabs-models/scripts/models.py (no network)."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from helpers import TEST_KEY, CatalogTransport, captured, load_script


class ModelsTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_script("empiriolabs-models", "models")
        patcher = mock.patch.object(self.mod.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_models(self, argv):
        self.transport = CatalogTransport([])
        with mock.patch.object(self.mod, "_open", self.transport), mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": TEST_KEY}):
            with captured() as (out, err):
                code = self.mod.main(argv)
        self.stdout, self.stderr = out.getvalue(), err.getvalue()
        for call in self.transport.calls:
            self.assertNotIn("authorization", call["headers"], "the catalog is public; never send a key")
        return code

    def ids(self):
        return [line.split()[1] if line.startswith("*") else line.split()[0]
                for line in self.stdout.splitlines() if line.strip()]

    def test_filter_by_category_and_alias(self):
        self.assertEqual(self.run_models(["--category", "video"]), 0)
        self.assertEqual(self.ids(), ["star-video", "other-video"])
        self.assertEqual(self.run_models(["--category", "tts"]), 0)
        self.assertEqual(self.ids(), ["star-tts", "plain-tts"])

    def test_filter_by_endpoint_feature_search_featured(self):
        self.run_models(["--endpoint", "audio/transcriptions"])
        self.assertEqual(self.ids(), ["star-stt", "other-stt"])
        self.run_models(["--feature", "image_editing"])
        self.assertEqual(self.ids(), ["edit-image"])
        self.run_models(["--search", "native image"])
        self.assertEqual(self.ids(), ["star-native-image"])
        self.run_models(["--category", "image", "--featured", "--limit", "2"])
        self.assertEqual(self.ids(), ["star-image", "star-native-image"])
        self.assertIn("2 of 3 matching models", self.stderr)

    def test_json_output(self):
        self.assertEqual(self.run_models(["--category", "transcription", "--json"]), 0)
        rows = json.loads(self.stdout)
        self.assertEqual([r["id"] for r in rows], ["star-stt", "other-stt"])
        self.assertEqual(rows[0]["prices"], ["Standard: $0.01 per unit"])
        self.assertEqual(rows[0]["docs"], "https://docs.empiriolabs.ai/models/star-stt")

    def test_show_one_model(self):
        self.assertEqual(self.run_models(["--show", "star-tts"]), 0)
        self.assertIn("Star Tts (star-tts)", self.stdout)
        self.assertIn("output_format", self.stdout)
        self.assertIn("options MP3, WAV, OGG", self.stdout)
        self.assertIn("up to 50", self.stdout)
        self.assertIn("Docs: https://docs.empiriolabs.ai/models/star-tts", self.stdout)
        self.assertEqual(self.run_models(["--show", "star-tts", "--json"]), 0)
        self.assertEqual(json.loads(self.stdout)["id"], "star-tts")

    def test_show_unknown_model(self):
        self.assertEqual(self.run_models(["--show", "does-not-exist"]), 1)
        self.assertIn("no model with id", self.stderr)

    def test_categories(self):
        self.assertEqual(self.run_models(["--categories", "--json"]), 0)
        rows = {r["slug"]: r["models"] for r in json.loads(self.stdout)}
        self.assertEqual(rows["image"], 4)
        self.assertEqual(rows["transcription"], 2)


if __name__ == "__main__":
    unittest.main()
