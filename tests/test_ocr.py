"""Tests for skills/empiriolabs-ocr/scripts/ocr.py (no network)."""

from __future__ import annotations

import json
import unittest

from helpers import API, json_response
from script_case import ScriptCase

PAGES = {"model": "star-ocr", "pages": [{"index": 0, "markdown": "# Title\n\nFirst page."},
                                        {"index": 1, "markdown": "Second page."}],
         "usage": {"pages": 2}}
ACCEPTED = json_response({"job_id": "doc-1", "status": "processing", "poll_url": "/v1/jobs/doc-1"}, status=202)
DONE = json_response({"job_id": "doc-1", "status": "completed", "model": "star-ocr", "result": PAGES})


class OcrTests(ScriptCase):
    skill = "empiriolabs-ocr"
    script = "ocr"

    def test_a_pdf_by_url_prints_its_markdown(self):
        routes = [("POST", API + "/ocr", json_response(PAGES))]
        code = self.run_script(routes, ["https://example.com/paper.pdf", "--pages", "0-1", "--table-format", "html"])
        self.assertEqual(code, 0, self.stderr)
        body = self.transport.json_body("POST", API + "/ocr")
        self.assertEqual(body, {"model": "star-ocr",
                                "document": {"type": "document_url", "document_url": "https://example.com/paper.pdf"},
                                "pages": "0-1", "table_format": "html"})
        self.assertEqual(self.stdout, "# Title\n\nFirst page.\n\nSecond page.\n")

    def test_a_local_image_is_sent_with_the_request_and_saved_as_markdown(self):
        scan = self.path("scan.png")
        with open(scan, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\nfake")
        out = self.path("out", "scan.md")
        routes = [("POST", API + "/ocr", json_response(PAGES))]
        self.assertEqual(self.run_script(routes, [scan, "--out", out]), 0, self.stderr)
        document = self.transport.json_body("POST", API + "/ocr")["document"]
        self.assertEqual(document["type"], "image_url")
        self.assertTrue(document["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(self.summary(), {"model": "star-ocr", "job_id": None, "file": out, "pages": 2,
                                          "characters": len("# Title\n\nFirst page.\n\nSecond page.")})
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# Title\n\nFirst page.\n\nSecond page.\n")

    def test_a_local_pdf_is_a_document(self):
        pdf = self.path("invoice.pdf")
        with open(pdf, "wb") as handle:
            handle.write(b"%PDF-1.4 fake")
        routes = [("POST", API + "/ocr", json_response(PAGES))]
        self.assertEqual(self.run_script(routes, [pdf]), 0, self.stderr)
        document = self.transport.json_body("POST", API + "/ocr")["document"]
        self.assertEqual(document["type"], "document_url")
        self.assertTrue(document["document_url"].startswith("data:application/pdf;base64,"))

    def test_a_file_without_a_known_extension_needs_its_type(self):
        blob = self.path("upload.bin")
        with open(blob, "wb") as handle:
            handle.write(b"%PDF-1.4 fake")
        self.assertEqual(self.run_script([], [blob]), 2)
        self.assertIn("--type pdf or --type image", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])
        routes = [("POST", API + "/ocr", json_response(PAGES))]
        self.assertEqual(self.run_script(routes, [blob, "--type", "pdf"]), 0, self.stderr)
        self.assertEqual(self.transport.json_body("POST", API + "/ocr")["document"]["type"], "document_url")

    def test_a_long_document_is_waited_for_as_a_job(self):
        routes = [
            ("POST", API + "/ocr", ACCEPTED),
            ("GET", API + "/jobs/doc-1", [json_response({"job_id": "doc-1", "status": "processing"}), DONE]),
        ]
        out = self.path("long.md")
        self.assertEqual(self.run_script(routes, ["https://example.com/long.pdf", "--out", out]), 0, self.stderr)
        summary = self.summary()
        self.assertEqual((summary["job_id"], summary["pages"]), ("doc-1", 2))

    def test_json_prints_the_full_result(self):
        routes = [("POST", API + "/ocr", json_response(PAGES))]
        self.assertEqual(self.run_script(routes, ["https://example.com/paper.pdf", "--json"]), 0, self.stderr)
        self.assertEqual(json.loads(self.stdout)["pages"][1]["markdown"], "Second page.")

    def test_resume_with_job_id(self):
        routes = [("GET", API + "/jobs/doc-1", DONE)]
        self.assertEqual(self.run_script(routes, ["--job-id", "doc-1"]), 0, self.stderr)
        self.assertIn("Second page.", self.stdout)

    def test_missing_file(self):
        self.assertEqual(self.run_script([], [self.path("nope.pdf")]), 2)
        self.assertIn("Input not found", self.stderr)

    def test_list_models(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* star-ocr", self.stdout)


if __name__ == "__main__":
    unittest.main()
