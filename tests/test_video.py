"""Tests for skills/empiriolabs-video/scripts/video.py (no network)."""

from __future__ import annotations

import itertools
import unittest
from unittest import mock

from helpers import API, CDN, bytes_response, json_response
from script_case import ScriptCase

ACCEPTED = json_response({"job_id": "vid-1", "status": "processing", "poll_url": "/v1/jobs/vid-1"}, status=202)
DONE = json_response({"job_id": "vid-1", "status": "completed", "model": "star-video",
                      "result": {"data": [{"url": CDN + "vid-1/video.mp4"}]}})


class VideoTests(ScriptCase):
    skill = "empiriolabs-video"
    script = "video"

    def test_submits_waits_and_downloads(self):
        routes = [
            ("POST", API + "/videos/generations", ACCEPTED),
            ("GET", API + "/jobs/vid-1", [json_response({"job_id": "vid-1", "status": "queued"}),
                                          json_response({"job_id": "vid-1", "status": "processing", "progress": 0.3}),
                                          DONE]),
            ("GET", CDN, bytes_response(b"MP4DATA", "video/mp4")),
        ]
        out = self.path("clips", "boat.mp4")
        code = self.run_script(routes, ["a paper boat", "--out", out, "--duration", "5", "--resolution", "480p",
                                        "--aspect-ratio", "16:9", "--no-audio",
                                        "--image", "https://example.com/start.png"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/videos/generations")
        self.assertEqual(body, {"model": "star-video", "prompt": "a paper boat", "image": "https://example.com/start.png",
                                "duration": 5, "resolution": "480p", "aspect_ratio": "16:9", "generate_audio": False})
        summary = self.summary()
        self.assertEqual(summary["job_id"], "vid-1")
        self.assertEqual(summary["files"], [out])
        with open(out, "rb") as handle:
            self.assertEqual(handle.read(), b"MP4DATA")
        self.assertIn("processing (30%)", self.stderr)

    def test_several_images_are_sent_as_references(self):
        routes = [("POST", API + "/videos/generations", ACCEPTED)]
        code = self.run_script(routes, ["two subjects", "--image", "https://e.com/a.png", "--image", "https://e.com/b.png",
                                        "--no-wait"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/videos/generations")
        self.assertEqual(body["images"], ["https://e.com/a.png", "https://e.com/b.png"])
        self.assertNotIn("image", body)

    def test_no_wait_prints_the_job_and_stops(self):
        routes = [("POST", API + "/videos/generations", ACCEPTED)]
        code = self.run_script(routes, ["a city", "--model", "other-video", "--no-wait", "--out", "my clips/city.mp4"])
        self.assertEqual(code, 0)
        self.assertEqual(self.summary(), {"model": "other-video", "job_id": "vid-1", "status": "processing"})
        self.assertEqual(self.transport.find("GET", API + "/jobs/"), [])
        self.assertIn('--job-id vid-1 --out "my clips/city.mp4"', self.stderr)

    def test_resume_with_job_id(self):
        routes = [("GET", API + "/jobs/vid-1", DONE), ("GET", CDN, bytes_response(b"MP4", "video/mp4"))]
        code = self.run_script(routes, ["--job-id", "vid-1", "--out", self.path("v.mp4")])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.summary()["model"], "star-video")

    def test_timeout_exits_3_with_a_resume_hint(self):
        routes = [
            ("POST", API + "/videos/generations", ACCEPTED),
            ("GET", API + "/jobs/vid-1", json_response({"job_id": "vid-1", "status": "processing"})),
        ]
        clock = itertools.count(0, 50)
        with mock.patch.object(self.api.time, "monotonic", side_effect=lambda: next(clock)):
            code = self.run_script(routes, ["slow", "--timeout", "120"])
        self.assertEqual(code, 3)
        self.assertIn("Job vid-1 is still processing", self.stderr)
        self.assertIn("--job-id vid-1", self.stderr)

    def test_failed_job(self):
        routes = [
            ("POST", API + "/videos/generations", ACCEPTED),
            ("GET", API + "/jobs/vid-1", json_response({"job_id": "vid-1", "status": "failed",
                                                         "error": {"message": "duration not supported", "code": 400}})),
        ]
        self.assertEqual(self.run_script(routes, ["x", "--duration", "99"]), 1)
        self.assertIn("duration not supported", self.stderr)

    def test_local_image_path_is_refused(self):
        self.assertEqual(self.run_script([], ["x", "--image", "./still.png"]), 2)
        self.assertIn("public https URL", self.stderr)
        self.assertEqual(self.transport.calls, [])

    def test_list_models(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* star-video", self.stdout)
        self.assertIn("other-video", self.stdout)


if __name__ == "__main__":
    unittest.main()
