"""Tests for skills/empiriolabs-3d/scripts/model3d.py (no network)."""

from __future__ import annotations

import itertools
import unittest
from unittest import mock

from helpers import API, CDN, bytes_response, json_response
from script_case import ScriptCase

ACCEPTED = json_response({"job_id": "obj-1", "status": "processing", "poll_url": "/v1/jobs/obj-1"}, status=202)
DONE = json_response({"job_id": "obj-1", "status": "completed", "model": "star-3d",
                      "result": {"data": [{"url": CDN + "obj-1/model.glb", "content_type": "model/gltf-binary"}]}})


class Model3dTests(ScriptCase):
    skill = "empiriolabs-3d"
    script = "model3d"

    def test_picture_url_submits_waits_and_downloads(self):
        routes = [
            ("POST", API + "/3d/generations", ACCEPTED),
            ("GET", API + "/jobs/obj-1", [json_response({"job_id": "obj-1", "status": "processing"}), DONE]),
            ("GET", CDN, bytes_response(b"glTFDATA", "model/gltf-binary")),
        ]
        out = self.path("models", "chair.glb")
        code = self.run_script(routes, ["--image", "https://example.com/chair.png", "--resolution", "512",
                                        "--param", "seed=7", "--out", out])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/3d/generations")
        self.assertEqual(body, {"model": "star-3d", "image": "https://example.com/chair.png", "resolution": "512",
                                "seed": 7})
        summary = self.summary()
        self.assertEqual((summary["model"], summary["job_id"], summary["files"]), ("star-3d", "obj-1", [out]))
        self.assertEqual(summary["urls"], [CDN + "obj-1/model.glb"])
        with open(out, "rb") as handle:
            self.assertEqual(handle.read(), b"glTFDATA")

    def test_local_picture_is_sent_with_the_request(self):
        picture = self.path("chair.png")
        with open(picture, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\nfake")
        routes = [("POST", API + "/3d/generations", ACCEPTED)]
        self.assertEqual(self.run_script(routes, ["--image", picture, "--no-wait"]), 0, self.stderr)
        body = self.transport.json_body("POST", API + "/3d/generations")
        self.assertTrue(body["image"].startswith("data:image/png;base64,"), body["image"][:40])
        self.assertEqual(self.summary(), {"model": "star-3d", "job_id": "obj-1", "status": "processing"})
        self.assertEqual(self.transport.find("GET", API + "/jobs/"), [])

    def test_a_description_is_refused_by_a_model_that_only_takes_a_picture(self):
        self.assertEqual(self.run_script([], ["a wooden chair"]), 2)
        self.assertIn("takes no description", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_a_model_that_takes_text_gets_the_description_and_the_file_format(self):
        routes = [("POST", API + "/3d/generations", ACCEPTED)]
        code = self.run_script(routes, ["a wooden chair", "--model", "text-3d", "--out", self.path("chair.obj"),
                                        "--no-wait"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/3d/generations")
        self.assertEqual(body, {"model": "text-3d", "prompt": "a wooden chair", "file_format": "obj"})

    def test_a_model_that_requires_a_picture_refuses_a_description_alone(self):
        self.assertEqual(self.run_script([], ["a chair", "--model", "photo-3d"]), 2)
        self.assertIn("needs a picture", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_missing_picture_file_is_a_usage_error(self):
        self.assertEqual(self.run_script([], ["--image", self.path("nope.png")]), 2)
        self.assertIn("Input not found", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_resume_with_job_id(self):
        routes = [("GET", API + "/jobs/obj-1", DONE), ("GET", CDN, bytes_response(b"glTF", "model/gltf-binary"))]
        code = self.run_script(routes, ["--job-id", "obj-1", "--out", self.path("m.glb")])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.summary()["model"], "star-3d")

    def test_timeout_exits_3_with_a_resume_hint(self):
        routes = [
            ("POST", API + "/3d/generations", ACCEPTED),
            ("GET", API + "/jobs/obj-1", json_response({"job_id": "obj-1", "status": "processing"})),
        ]
        clock = itertools.count(0, 50)
        with mock.patch.object(self.api.time, "monotonic", side_effect=lambda: next(clock)):
            code = self.run_script(routes, ["--image", "https://example.com/chair.png", "--timeout", "120"])
        self.assertEqual(code, 3)
        self.assertIn("--job-id obj-1", self.stderr)

    def test_failed_job(self):
        routes = [
            ("POST", API + "/3d/generations", ACCEPTED),
            ("GET", API + "/jobs/obj-1", json_response({"job_id": "obj-1", "status": "failed",
                                                         "error": {"message": "the picture shows no object"}})),
        ]
        self.assertEqual(self.run_script(routes, ["--image", "https://example.com/blank.png"]), 1)
        self.assertIn("the picture shows no object", self.stderr)

    def test_list_models(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* star-3d", self.stdout)
        self.assertIn("text-3d", self.stdout)


if __name__ == "__main__":
    unittest.main()
