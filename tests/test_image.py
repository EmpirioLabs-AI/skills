"""Tests for skills/empiriolabs-image/scripts/image.py (no network)."""

from __future__ import annotations

import base64
import os
import unittest
from unittest import mock

from helpers import API, CDN, bytes_response, json_response
from script_case import ScriptCase


class ImageTests(ScriptCase):
    skill = "empiriolabs-image"
    script = "image"

    def test_generates_with_the_default_model_and_saves(self):
        routes = [
            ("POST", API + "/images/generations", json_response(
                {"created": 1, "id": "job-1", "data": [{"url": CDN + "x/a.png", "filename": "lighthouse.png"}]})),
            ("GET", CDN, bytes_response(b"PNG", "image/png")),
        ]
        out = self.path("pics", "lighthouse.png")
        code = self.run_script(routes, ["a lighthouse", "--out", out, "--aspect-ratio", "16:9"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/images/generations")
        self.assertEqual(body["model"], "star-native-image")
        self.assertEqual(body["prompt"], "a lighthouse")
        self.assertIs(body["sync"], True)
        self.assertEqual(body["response_format"], "url")
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertEqual(body["format"], "png", "the --out extension selects the format")
        summary = self.summary()
        self.assertEqual(summary["files"], [out])
        self.assertEqual(summary["urls"], [CDN + "x/a.png"])
        with open(out, "rb") as handle:
            self.assertEqual(handle.read(), b"PNG")

    def test_falls_back_to_polling_a_job(self):
        routes = [
            ("POST", API + "/images/generations", json_response(
                {"job_id": "job-9", "status": "processing", "poll_url": "/v1/jobs/job-9"})),
            ("GET", API + "/jobs/job-9", [
                json_response({"job_id": "job-9", "status": "processing"}),
                json_response({"job_id": "job-9", "status": "completed", "result": {"data": [{"url": CDN + "b.webp"}]}}),
            ]),
            ("GET", CDN, bytes_response(b"WEBP", "image/webp")),
        ]
        code = self.run_script(routes, ["a fox", "--model", "plain-image", "--out", self.path("out") + os.sep])
        self.assertEqual(code, 0, self.stderr)
        summary = self.summary()
        self.assertEqual(summary["job_id"], "job-9")
        self.assertEqual(summary["model"], "plain-image")
        self.assertTrue(summary["files"][0].endswith(".webp"))

    def test_edit_mode_sends_local_files_inline_and_picks_an_editing_model(self):
        src = self.path("photo.png")
        with open(src, "wb") as handle:
            handle.write(b"\x89PNG-src")
        routes = [
            ("POST", API + "/images/generations", json_response({"data": [{"b64_json": base64.b64encode(b"EDITED").decode()}]})),
        ]
        out = self.path("edited.png")
        code = self.run_script(routes, ["make it night", "--image", src, "--image", "https://example.com/ref.jpg",
                                        "--out", out, "-n", "1", "--param", "seed=7"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/images/generations")
        self.assertEqual(body["model"], "edit-image")
        self.assertEqual(body["image"][0], "data:image/png;base64," + base64.b64encode(b"\x89PNG-src").decode())
        self.assertEqual(body["image"][1], "https://example.com/ref.jpg")
        self.assertEqual(body["num_images"], 1)
        self.assertEqual(body["seed"], 7)
        self.assertEqual(self.summary()["files"], [out])

    def test_no_download_prints_urls_only(self):
        routes = [("POST", API + "/images/generations", json_response({"data": [{"url": CDN + "c.png"}]}))]
        code = self.run_script(routes, ["a cat", "--no-download"])
        self.assertEqual(code, 0)
        self.assertEqual(self.summary(), {"model": "star-native-image", "files": [], "urls": [CDN + "c.png"]})

    def test_resume_a_job(self):
        routes = [
            ("GET", API + "/jobs/job-5", json_response({"job_id": "job-5", "status": "completed", "model": "plain-image",
                                                         "result": {"data": [{"url": CDN + "d.png"}]}})),
            ("GET", CDN, bytes_response(b"PNG", "image/png")),
        ]
        code = self.run_script(routes, ["--job-id", "job-5", "--out", self.path("d.png")])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.summary()["model"], "plain-image")

    def test_missing_key_fails_before_any_request(self):
        with mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": ""}):
            code = self.run_script([], ["a cat"])
        self.assertEqual(code, 1)
        self.assertIn("EMPIRIOLABS_API_KEY is not set", self.stderr)
        self.assertEqual(self.transport.calls, [])

    def test_api_error_is_reported(self):
        routes = [("POST", API + "/images/generations", json_response({"error": {"message": "Insufficient credits"}}, status=402))]
        code = self.run_script(routes, ["a cat"])
        self.assertEqual(code, 1)
        self.assertIn("Insufficient credits", self.stderr)
        self.assertIn("dashboard/billing", self.stderr)

    def test_empty_result_is_an_error(self):
        routes = [("POST", API + "/images/generations", json_response({"data": []}))]
        self.assertEqual(self.run_script(routes, ["a cat"]), 1)
        self.assertIn("without returning an image", self.stderr)

    def test_unsupported_model_is_a_usage_error(self):
        self.assertEqual(self.run_script([], ["a cat", "--model", "star-video"]), 2)
        self.assertIn("does not support", self.stderr)

    def test_list_models_needs_no_key(self):
        with mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": ""}):
            code = self.run_script([], ["--list-models"])
        self.assertEqual(code, 0)
        self.assertIn("* star-native-image", self.stdout)
        self.assertIn("plain-image", self.stdout)
        self.assertNotIn("star-video", self.stdout)

    def test_prompt_is_required(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_script([], [])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
