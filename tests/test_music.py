"""Tests for skills/empiriolabs-music/scripts/music.py (no network)."""

from __future__ import annotations

import unittest

from helpers import API, CDN, bytes_response, json_response
from script_case import ScriptCase

ACCEPTED = json_response({"job_id": "aud-1", "status": "processing", "poll_url": "/v1/jobs/aud-1"}, status=202)
DONE = json_response({"job_id": "aud-1", "status": "completed", "model": "star-music",
                      "result": {"data": [{"url": CDN + "aud-1/track.mp3", "content_type": "audio/mpeg"}]}})


class MusicTests(ScriptCase):
    skill = "empiriolabs-music"
    script = "music"

    def test_submits_waits_and_downloads_with_the_models_own_parameter_names(self):
        routes = [
            ("POST", API + "/audio/generations", ACCEPTED),
            ("GET", API + "/jobs/aud-1", [json_response({"job_id": "aud-1", "status": "processing"}), DONE]),
            ("GET", CDN, bytes_response(b"ID3track", "audio/mpeg")),
        ]
        out = self.path("audio", "track.mp3")
        code = self.run_script(routes, ["a calm piano melody", "--duration", "10", "--out", out])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/audio/generations")
        self.assertEqual(body, {"model": "star-music", "prompt": "a calm piano melody", "audio_duration": 10,
                                "format": "mp3"})
        summary = self.summary()
        self.assertEqual((summary["model"], summary["job_id"], summary["files"]), ("star-music", "aud-1", [out]))
        with open(out, "rb") as handle:
            self.assertEqual(handle.read(), b"ID3track")

    def test_another_model_gets_its_own_duration_and_format_parameters(self):
        routes = [("POST", API + "/audio/generations", ACCEPTED)]
        code = self.run_script(routes, ["footsteps on gravel", "--model", "sfx-sound", "--duration", "2.5",
                                        "--out", self.path("steps.wav"), "--param", "seed=3", "--no-wait"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/audio/generations")
        self.assertEqual(body, {"model": "sfx-sound", "prompt": "footsteps on gravel", "duration": 2.5,
                                "output_format": "wav", "seed": 3})
        self.assertEqual(self.summary(), {"model": "sfx-sound", "job_id": "aud-1", "status": "processing"})

    def test_lyrics_are_read_from_a_file(self):
        lyrics = self.path("lyrics.txt")
        with open(lyrics, "w", encoding="utf-8") as handle:
            handle.write("Rain on the roof\nAll night long\n")
        routes = [("POST", API + "/audio/generations", ACCEPTED)]
        self.assertEqual(self.run_script(routes, ["a folk song", "--lyrics-file", lyrics, "--no-wait"]), 0, self.stderr)
        body = self.transport.json_body("POST", API + "/audio/generations")
        self.assertEqual(body["lyrics"], "Rain on the roof\nAll night long")

    def test_lyrics_are_refused_by_a_model_that_takes_none(self):
        code = self.run_script([], ["a door closing", "--model", "sfx-sound", "--lyrics", "la la"])
        self.assertEqual(code, 2)
        self.assertIn("does not take lyrics", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_a_result_that_arrives_at_once_is_saved(self):
        routes = [
            ("POST", API + "/audio/generations", json_response({"data": [{"url": CDN + "now.wav"}], "usage": {}})),
            ("GET", CDN, bytes_response(b"RIFFwave", "audio/wav")),
        ]
        out = self.path("now.wav")
        self.assertEqual(self.run_script(routes, ["a short chime", "--out", out]), 0, self.stderr)
        self.assertEqual(self.summary()["files"], [out])
        self.assertEqual(self.transport.find("GET", API + "/jobs/"), [])

    def test_resume_with_job_id(self):
        routes = [("GET", API + "/jobs/aud-1", DONE), ("GET", CDN, bytes_response(b"ID3", "audio/mpeg"))]
        code = self.run_script(routes, ["--job-id", "aud-1", "--out", self.path("t.mp3")])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.summary()["model"], "star-music")

    def test_failed_job(self):
        routes = [
            ("POST", API + "/audio/generations", ACCEPTED),
            ("GET", API + "/jobs/aud-1", json_response({"job_id": "aud-1", "status": "failed",
                                                         "error": {"message": "duration not supported"}})),
        ]
        self.assertEqual(self.run_script(routes, ["x", "--duration", "999"]), 1)
        self.assertIn("duration not supported", self.stderr)

    def test_list_models(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* star-music", self.stdout)
        self.assertIn("sfx-sound", self.stdout)
        self.assertNotIn("star-tts", self.stdout)


if __name__ == "__main__":
    unittest.main()
