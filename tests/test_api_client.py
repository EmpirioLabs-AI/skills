"""Unit tests for shared/empiriolabs_api.py with a fake HTTP transport."""

from __future__ import annotations

import base64
import itertools
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from helpers import (API, CDN, TEST_KEY, CatalogTransport, FakeTransport, bytes_response, captured, catalog,
                     json_response, load_shared)

api = load_shared()


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": TEST_KEY})
        self.env.start()
        self.sleep = mock.patch.object(api.time, "sleep")
        self.sleep.start()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.env.stop()
        self.sleep.stop()
        self.tmp.cleanup()

    def use(self, transport):
        patcher = mock.patch.object(api, "_open", transport)
        patcher.start()
        self.addCleanup(patcher.stop)
        return transport


class RequestTests(ClientTestCase):
    def test_bearer_key_only_goes_to_the_api_host(self):
        t = self.use(FakeTransport([
            ("GET", API + "/jobs/j1", json_response({"status": "completed"})),
            ("GET", CDN, bytes_response(b"PNG", "image/png")),
        ]))
        api.get_json("/jobs/j1")
        path = api.download(CDN + "a.png", lambda ext: os.path.join(self.tmp.name, "a" + ext))
        self.assertEqual(t.calls[0]["headers"]["authorization"], "Bearer " + TEST_KEY)
        self.assertNotIn("authorization", t.calls[1]["headers"])
        self.assertTrue(path.endswith("a.png"))

    def test_public_catalog_needs_no_key(self):
        with mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": ""}):
            t = self.use(CatalogTransport([]))
            models = api.list_models()
        self.assertEqual(len(models), len(catalog()["data"]))
        self.assertNotIn("authorization", t.calls[0]["headers"])

    def test_gzip_body_is_decoded(self):
        self.use(FakeTransport([("GET", API + "/x", json_response({"ok": True}, gzip_body=True))]))
        self.assertEqual(api.get_json("/x"), {"ok": True})

    def test_get_retries_server_errors(self):
        t = self.use(FakeTransport([("GET", API + "/x", [
            json_response({"error": {"message": "busy"}}, status=503),
            json_response({"ok": True}),
        ])]))
        self.assertEqual(api.get_json("/x"), {"ok": True})
        self.assertEqual(len(t.calls), 2)

    def test_post_is_not_retried_on_server_error(self):
        t = self.use(FakeTransport([("POST", API + "/x", json_response({"error": {"message": "boom"}}, status=500))]))
        with self.assertRaises(api.ApiError) as ctx:
            api.post_json("/x", {"a": 1})
        self.assertEqual(len(t.calls), 1)
        self.assertIn("HTTP 500: boom", ctx.exception.message)

    def test_post_retries_rate_limit(self):
        t = self.use(FakeTransport([("POST", API + "/x", [
            json_response({"error": {"message": "slow down"}}, status=429, headers={"Retry-After": "1"}),
            json_response({"ok": True}),
        ])]))
        self.assertEqual(api.post_json("/x", {}).json(), {"ok": True})
        self.assertEqual(len(t.calls), 2)

    def test_network_error_on_post_warns_about_duplicates(self):
        self.use(FakeTransport([("POST", API + "/x", (urllib.error.URLError("reset"), b"", {}))]))
        with self.assertRaises(api.ApiError) as ctx:
            api.post_json("/x", {})
        self.assertIn("may still have been processed", ctx.exception.message)

    def test_error_envelopes_and_hints(self):
        cases = [
            (401, {"error": {"message": "Invalid API key", "type": "invalid_api_key"}}, "Invalid API key", "dashboard/api-keys"),
            (402, {"error": {"message": "Insufficient credits"}}, "Insufficient credits", "dashboard/billing"),
            (400, {"detail": "prompt is required"}, "prompt is required", None),
            (422, {"detail": [{"msg": "field required"}]}, "field required", None),
        ]
        for status, payload, text, hint in cases:
            self.use(FakeTransport([("POST", API + "/x", json_response(payload, status=status))]))
            with self.assertRaises(api.ApiError) as ctx:
                api.post_json("/x", {})
            self.assertIn(text, ctx.exception.message)
            self.assertEqual(ctx.exception.status, status)
            if hint:
                self.assertIn(hint, ctx.exception.message)

    def test_key_is_redacted_from_echoed_errors(self):
        self.use(FakeTransport([("POST", API + "/x", json_response(
            {"error": {"message": "bad key " + TEST_KEY + " and sk-empiriolabs-otherkey123"}}, status=401))]))
        with self.assertRaises(api.ApiError) as ctx:
            api.post_json("/x", {})
        self.assertNotIn(TEST_KEY, ctx.exception.message)
        self.assertNotIn("otherkey123", ctx.exception.message)

    def test_missing_key_is_reported_without_network(self):
        t = self.use(FakeTransport([]))
        with mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": ""}):
            with self.assertRaises(api.ApiError) as ctx:
                api.post_json("/x", {})
        self.assertIn("EMPIRIOLABS_API_KEY is not set", ctx.exception.message)
        self.assertEqual(t.calls, [])


class CatalogTests(ClientTestCase):
    def test_default_prefers_featured_then_native(self):
        models = catalog()["data"]
        self.assertEqual(api.pick_default(models, "POST /v1/images/generations", "image")["id"], "star-native-image")
        self.assertEqual(api.pick_default(models, "POST /v1/images/generations", "image", "image_editing")["id"], "edit-image")
        self.assertEqual(api.pick_default(models, "POST /v1/audio/speech", "audio")["id"], "star-tts")

    def test_no_candidate_raises(self):
        with self.assertRaises(api.ApiError):
            api.pick_default(catalog()["data"], "POST /v1/3d/generations")

    def test_resolve_explicit_model(self):
        self.use(CatalogTransport([]))
        model_id, entry = api.resolve_model("plain-image", "POST /v1/images/generations")
        self.assertEqual((model_id, entry["id"]), ("plain-image", "plain-image"))
        with self.assertRaises(api.ApiError) as ctx:
            api.resolve_model("star-video", "POST /v1/images/generations")
        self.assertEqual(ctx.exception.exit_code, api.EXIT_USAGE)
        with captured() as (_out, err):
            model_id, entry = api.resolve_model("brand-new-model", "POST /v1/images/generations")
        self.assertEqual((model_id, entry), ("brand-new-model", None))
        self.assertIn("not in the public catalog", err.getvalue())

    def test_format_from_path(self):
        entry = [m for m in catalog()["data"] if m["id"] == "star-native-image"][0]
        self.assertEqual(api.format_from_path(entry, "out/cat.png"), ("format", "png"))
        self.assertEqual(api.format_from_path(entry, "out/cat.jpg"), ("format", "jpeg"))
        self.assertIsNone(api.format_from_path(entry, "out/cat.gif"))
        self.assertIsNone(api.format_from_path(entry, None))
        tts = [m for m in catalog()["data"] if m["id"] == "star-tts"][0]
        self.assertEqual(api.format_from_path(tts, "a.mp3", names=("output_format",)), ("output_format", "MP3"))

    def test_price_summary(self):
        entry = {"pricing_rows": [{"label": "A", "value": "$1", "spec": "per image"},
                                  {"label": "B", "value": "$2", "spec": "per image"},
                                  {"label": "C", "value": "$3", "spec": "per image"},
                                  {"label": "D", "value": "$4", "spec": "per image"}]}
        self.assertEqual(api.price_summary(entry), "A: $1 per image; B: $2 per image; C: $3 per image; +1 more")


class JobTests(ClientTestCase):
    def test_wait_until_completed(self):
        self.use(FakeTransport([("GET", API + "/jobs/j1", [
            json_response({"job_id": "j1", "status": "queued"}),
            json_response({"job_id": "j1", "status": "processing", "progress": 0.5}),
            json_response({"job_id": "j1", "status": "completed", "result": {"data": [{"url": CDN + "v.mp4"}]}}),
        ])]))
        with captured() as (_out, err):
            job = api.wait_for_job("j1", timeout=60)
        self.assertEqual(api.media_items(job), [{"url": CDN + "v.mp4"}])
        self.assertIn("processing (50%)", err.getvalue())

    def test_failed_job_raises_its_message(self):
        self.use(FakeTransport([("GET", API + "/jobs/j2", json_response(
            {"job_id": "j2", "status": "failed", "error": {"message": "prompt rejected", "type": "invalid_request_error", "code": 400}}))]))
        with captured():
            with self.assertRaises(api.ApiError) as ctx:
                api.wait_for_job("j2", timeout=60)
        self.assertIn("prompt rejected", ctx.exception.message)

    def test_timeout_keeps_the_job_id(self):
        self.use(FakeTransport([("GET", API + "/jobs/j3", json_response({"job_id": "j3", "status": "processing"}))]))
        clock = itertools.count(0, 100)
        with mock.patch.object(api.time, "monotonic", side_effect=lambda: next(clock)):
            with captured():
                with self.assertRaises(api.JobTimeout) as ctx:
                    api.wait_for_job("j3", timeout=250)
        self.assertEqual(ctx.exception.job_id, "j3")
        self.assertEqual(ctx.exception.exit_code, api.EXIT_TIMEOUT)

    def test_media_item_shapes(self):
        self.assertEqual(api.media_items({"data": [{"url": "https://x/a.png", "filename": "a.png"}]}),
                         [{"url": "https://x/a.png", "filename": "a.png"}])
        self.assertEqual(api.media_items({"result": {"data": [{"b64_json": "QUJD"}]}}), [{"b64_json": "QUJD"}])
        self.assertEqual(api.media_items({"audio_url": "https://x/a.mp3"}), [{"url": "https://x/a.mp3"}])
        self.assertEqual(api.media_items({"result": {"video_url": "https://x/v.mp4"}}), [{"url": "https://x/v.mp4"}])
        self.assertEqual(api.media_items({"job_id": "j", "status": "processing"}), [])
        self.assertEqual(api.job_id_of({"job_id": "j", "status": "processing"}), "j")
        self.assertIsNone(api.job_id_of({"id": "img_1", "data": []}))


class FileTests(ClientTestCase):
    def test_target_paths(self):
        d = self.tmp.name + os.sep
        self.assertEqual(api.target_path(d, "image-x", ".png", 1, 1), os.path.join(self.tmp.name, "image-x.png"))
        self.assertEqual(api.target_path(d, "image-x", ".png", 2, 3), os.path.join(self.tmp.name, "image-x-2.png"))
        self.assertEqual(api.target_path(d, "x", ".webp", 1, 1, name_hint="a lighthouse.webp"),
                         os.path.join(self.tmp.name, "a-lighthouse.webp"))
        f = os.path.join(self.tmp.name, "cat.png")
        self.assertEqual(api.target_path(f, "s", ".png", 1, 1), f)
        self.assertEqual(api.target_path(f, "s", ".png", 2, 2), os.path.join(self.tmp.name, "cat-2.png"))
        with captured() as (_out, err):
            self.assertEqual(api.target_path(f, "s", ".webp", 1, 1), os.path.join(self.tmp.name, "cat.webp"))
        self.assertIn(".webp", err.getvalue())
        self.assertEqual(api.target_path(os.path.join(self.tmp.name, "clip"), "s", ".mp4", 1, 1),
                         os.path.join(self.tmp.name, "clip.mp4"))

    def test_existing_files_are_not_overwritten(self):
        f = os.path.join(self.tmp.name, "cat.png")
        open(f, "wb").close()
        self.assertEqual(api.target_path(f, "s", ".png", 1, 1), os.path.join(self.tmp.name, "cat-2.png"))
        self.assertEqual(api.target_path(f, "s", ".png", 1, 1, overwrite=True), f)

    def test_save_items_handles_url_and_base64(self):
        self.use(FakeTransport([("GET", CDN, bytes_response(b"WEBPDATA", "image/webp"))]))
        out = os.path.join(self.tmp.name, "imgs") + os.sep
        paths = api.save_items([{"url": CDN + "one.webp"}, {"b64_json": base64.b64encode(b"PNGDATA").decode(),
                                                            "content_type": "image/png"}], out, "image-t")
        self.assertEqual([os.path.basename(p) for p in paths], ["image-t-1.webp", "image-t-2.png"])
        with open(paths[1], "rb") as handle:
            self.assertEqual(handle.read(), b"PNGDATA")
        self.assertFalse([n for n in os.listdir(out) if n.endswith(".part")])

    def test_inline_file(self):
        path = os.path.join(self.tmp.name, "pic.png")
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG")
        self.assertEqual(api.inline_file(path), "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode())
        self.assertEqual(api.inline_file("https://x/y.png"), "https://x/y.png")
        with self.assertRaises(api.ApiError):
            api.inline_file(os.path.join(self.tmp.name, "missing.png"))
        with self.assertRaises(api.ApiError):
            api.inline_file(path, max_bytes=2)

    def test_parse_params(self):
        self.assertEqual(api.parse_params(["seed=42", "flag=true", "name=hello", "list=[1,2]", "empty="]),
                         {"seed": 42, "flag": True, "name": "hello", "list": [1, 2], "empty": ""})
        with self.assertRaises(api.ApiError):
            api.parse_params(["novalue"])

    def test_multipart_encoding(self):
        body, ctype = api.encode_multipart([("model", "m1")], [("file", 'a"b.wav', "audio/wav", b"RIFF")])
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="model"\r\n\r\nm1\r\n', body)
        self.assertIn(b'filename="a_b.wav"', body)
        self.assertTrue(body.endswith(("--" + boundary + "--\r\n").encode()))

    def test_resume_hint_quotes_paths(self):
        self.assertEqual(api.resume_hint("video.py", "j1", "my clips/a.mp4"),
                         'Resume later with: python3 scripts/video.py --job-id j1 --out "my clips/a.mp4"')


if __name__ == "__main__":
    unittest.main()
