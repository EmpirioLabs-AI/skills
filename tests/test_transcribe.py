"""Tests for skills/empiriolabs-transcribe/scripts/transcribe.py (no network)."""

from __future__ import annotations

import json
import os
import unittest

from helpers import API, json_response
from script_case import ScriptCase

ACCEPTED = json_response({"job_id": "stt-1", "status": "processing", "poll_url": "/v1/jobs/stt-1"}, status=202)
RESULT = {"text": "The ocean is calm today.", "language": "en", "duration": 4.3,
          "segments": [{"start": 0.0, "end": 4.3, "text": "The ocean is calm today."}]}
DONE = json_response({"job_id": "stt-1", "status": "completed", "model": "star-stt", "result": RESULT})


class TranscribeTests(ScriptCase):
    skill = "empiriolabs-transcribe"
    script = "transcribe"

    def test_url_source_prints_the_transcript(self):
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED),
                  ("GET", API + "/jobs/stt-1", [json_response({"job_id": "stt-1", "status": "processing"}), DONE])]
        code = self.run_script(routes, ["https://example.com/ocean.wav", "--language", "en", "--diarize",
                                        "--param", "smart_format=true"])
        self.assertEqual(code, 0, self.stderr)
        self.assertEqual(self.stdout.strip(), "The ocean is calm today.")
        body = self.transport.json_body("POST", API + "/audio/transcriptions")
        self.assertEqual(body, {"model": "star-stt", "file_url": "https://example.com/ocean.wav", "language": "en",
                                "diarize": True, "smart_format": True})

    def test_local_file_is_uploaded_as_multipart(self):
        audio = self.path("memo.wav")
        with open(audio, "wb") as handle:
            handle.write(b"RIFFxxxxWAVE")
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED), ("GET", API + "/jobs/stt-1", DONE)]
        out = self.path("notes", "memo.txt")
        code = self.run_script(routes, [audio, "--model", "other-stt", "--out", out])
        self.assertEqual(code, 0, self.stderr)
        call = self.transport.find("POST", API + "/audio/transcriptions")[0]
        self.assertTrue(call["headers"]["content-type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="model"\r\n\r\nother-stt', call["body"])
        self.assertIn(b'name="file"; filename="memo.wav"', call["body"])
        self.assertIn(b"RIFFxxxxWAVE", call["body"])
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "The ocean is calm today.\n")
        summary = self.summary()
        self.assertEqual(summary["file"], out)
        self.assertEqual(summary["characters"], len("The ocean is calm today."))
        self.assertEqual(summary["language"], "en")

    def test_json_out_saves_the_full_result(self):
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED), ("GET", API + "/jobs/stt-1", DONE)]
        out = self.path("full.json")
        self.assertEqual(self.run_script(routes, ["https://example.com/a.mp3", "--out", out]), 0, self.stderr)
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), RESULT)

    def test_json_flag_prints_the_full_result(self):
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED), ("GET", API + "/jobs/stt-1", DONE)]
        self.assertEqual(self.run_script(routes, ["https://example.com/a.mp3", "--json"]), 0)
        self.assertEqual(json.loads(self.stdout), RESULT)

    def test_out_directory_gets_a_generated_name(self):
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED), ("GET", API + "/jobs/stt-1", DONE)]
        folder = self.path("transcripts") + os.sep
        self.assertEqual(self.run_script(routes, ["https://example.com/a.mp3", "--out", folder]), 0, self.stderr)
        saved = self.summary()["file"]
        self.assertTrue(os.path.basename(saved).startswith("transcript-") and saved.endswith(".txt"), saved)

    def test_no_wait_and_resume(self):
        code = self.run_script([("POST", API + "/audio/transcriptions", ACCEPTED)],
                               ["https://example.com/long.mp3", "--no-wait"])
        self.assertEqual(code, 0)
        self.assertEqual(self.summary()["job_id"], "stt-1")
        code = self.run_script([("GET", API + "/jobs/stt-1", DONE)], ["--job-id", "stt-1"])
        self.assertEqual(code, 0)
        self.assertEqual(self.stdout.strip(), "The ocean is calm today.")

    def test_segments_only_result(self):
        done = json_response({"job_id": "stt-1", "status": "completed",
                              "result": {"segments": [{"text": " Hello "}, {"text": "world."}]}})
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED), ("GET", API + "/jobs/stt-1", done)]
        self.assertEqual(self.run_script(routes, ["https://example.com/a.mp3"]), 0)
        self.assertEqual(self.stdout.strip(), "Hello world.")

    def test_failed_job(self):
        failed = json_response({"job_id": "stt-1", "status": "failed",
                                "error": {"message": "The audio file could not be read.", "code": 400}})
        routes = [("POST", API + "/audio/transcriptions", ACCEPTED), ("GET", API + "/jobs/stt-1", failed)]
        self.assertEqual(self.run_script(routes, ["https://example.com/broken.mp3"]), 1)
        self.assertIn("could not be read", self.stderr)

    def test_missing_local_file(self):
        self.assertEqual(self.run_script([], [self.path("nope.wav")]), 2)
        self.assertIn("File not found", self.stderr)

    def test_list_models(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* star-stt", self.stdout)


if __name__ == "__main__":
    unittest.main()
