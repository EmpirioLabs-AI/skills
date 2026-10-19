"""Tests for skills/empiriolabs-speech/scripts/speech.py (no network)."""

from __future__ import annotations

import base64
import os
import unittest

from helpers import API, CDN, bytes_response, json_response, url_query
from script_case import ScriptCase


class SpeechTests(ScriptCase):
    skill = "empiriolabs-speech"
    script = "speech"

    def test_audio_bytes_response_is_saved_and_format_follows_out(self):
        routes = [("POST", API + "/audio/speech", bytes_response(b"ID3audio", "audio/mpeg"))]
        out = self.path("audio", "welcome.mp3")
        code = self.run_script(routes, ["Welcome back.", "--out", out, "--voice", "Mark"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/audio/speech")
        self.assertEqual(body, {"model": "star-tts", "input": "Welcome back.", "voice": "Mark", "output_format": "MP3"})
        self.assertEqual(self.summary(), {"model": "star-tts", "files": [out], "urls": [], "voice": "Mark"})
        with open(out, "rb") as handle:
            self.assertEqual(handle.read(), b"ID3audio")

    def test_json_url_response_is_downloaded(self):
        routes = [
            ("POST", API + "/audio/speech", json_response({"data": [{"url": CDN + "s.wav"}], "usage": {}})),
            ("GET", CDN, bytes_response(b"RIFF", "audio/wav")),
        ]
        code = self.run_script(routes, ["Hello", "--model", "plain-tts", "--out", self.path("speech") + os.sep,
                                        "--format", "wav", "--speed", "1.2", "--language", "en-US"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/audio/speech")
        self.assertEqual(body["output_format"], "wav")
        self.assertEqual(body["speed"], 1.2)
        self.assertEqual(body["language"], "en-US")
        summary = self.summary()
        self.assertEqual(summary["urls"], [CDN + "s.wav"])
        self.assertTrue(summary["files"][0].endswith(".wav"))

    def test_base64_and_job_responses(self):
        routes = [
            ("POST", API + "/audio/speech", json_response({"job_id": "tts-1", "status": "queued"})),
            ("GET", API + "/jobs/tts-1", json_response({"job_id": "tts-1", "status": "completed", "result": {
                "data": [{"b64_json": base64.b64encode(b"OggS").decode(), "content_type": "audio/ogg"}]}})),
        ]
        out = self.path("long.ogg")
        code = self.run_script(routes, ["Long text", "--out", out])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.summary()["files"], [out])
        self.assertEqual(self.transport.json_body("POST", API + "/audio/speech")["output_format"], "OGG")

    def test_text_file_and_length_limit(self):
        path = self.path("script.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x" * 60)
        code = self.run_script([], ["--text-file", path])
        self.assertEqual(code, 2)
        self.assertIn("accepts up to 50 characters", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_list_voices_from_the_api(self):
        routes = [("GET", API + "/voices", json_response({"data": [
            {"id": "Sarah", "name": "Sarah", "gender": "female", "language": "en-US"},
            {"id": "Mark", "name": "Mark", "gender": "male", "language": "en-US"}]}))]
        code = self.run_script(routes, ["--list-voices", "--language", "en-US"])
        self.assertEqual(code, 0, self.stderr)
        self.assertIn("Sarah", self.stdout)
        call = self.transport.find("GET", API + "/voices")[0]
        self.assertEqual(url_query(call["url"]), {"model": "star-tts", "language": "en-US"})

    def test_list_voices_from_the_catalog_when_no_voice_endpoint(self):
        code = self.run_script([], ["--list-voices", "--model", "plain-tts"])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.stdout.split(), ["Ana", "Ben"])

    def test_list_models_excludes_non_audio_models(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* star-tts", self.stdout)
        self.assertNotIn("omni-chat", self.stdout)

    def test_error_from_service(self):
        routes = [("POST", API + "/audio/speech", json_response({"error": {"message": "Unknown voice"}}, status=400))]
        self.assertEqual(self.run_script(routes, ["Hi", "--voice", "Nobody"]), 1)
        self.assertIn("Unknown voice", self.stderr)


if __name__ == "__main__":
    unittest.main()
