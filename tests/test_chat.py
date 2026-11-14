"""Tests for skills/empiriolabs-chat/scripts/chat.py (no network)."""

from __future__ import annotations

import base64
import io
import json
import sys
import unittest
from unittest import mock

from helpers import API, json_response
from script_case import ScriptCase

ANSWER = "Use optimistic locking."


def reply(model="omni-chat", content="  " + ANSWER + "\n", finish="stop"):
    return {"id": "chatcmpl-1", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}


CHAT = API + "/chat/completions"


class ChatTests(ScriptCase):
    skill = "empiriolabs-chat"
    script = "chat"

    def sent(self):
        return [json.loads(call["body"].decode("utf-8")) for call in self.transport.find("POST", CHAT)]

    def test_a_question_goes_to_the_default_text_model_and_its_answer_is_printed(self):
        argv = ["Which locking?", "--system", " Be brief. ", "--max-tokens", "200", "--temperature", "0.2",
                "--param", "reasoning_effort=low"]
        self.assertEqual(self.run_script([("POST", CHAT, json_response(reply()))], argv), 0, self.stderr)
        self.assertEqual(self.sent(), [{
            "model": "omni-chat",
            "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Which locking?"}],
            "stream": False, "max_tokens": 200, "temperature": 0.2, "reasoning_effort": "low"}])
        self.assertEqual(self.stdout, ANSWER + "\n")
        self.assertIn("omni-chat: 12 prompt tokens, 5 generated tokens.", self.stderr)

    def test_an_answer_in_parts_is_joined(self):
        parts = [{"type": "text", "text": "Use optimistic "}, {"type": "text", "text": "locking."}]
        self.assertEqual(self.run_script([("POST", CHAT, json_response(reply(content=parts)))], ["Which locking?"]), 0)
        self.assertEqual(self.stdout, ANSWER + "\n")

    def test_files_are_attached_under_their_names_in_a_fence_longer_than_their_backticks(self):
        notes, code = self.path("notes.md"), self.path("a.py")
        with open(notes, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("Use ```code``` here.\n")
        with open(code, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("print(1)\n")
        argv = ["Review these", "--file", notes, "--file", code]
        self.assertEqual(self.run_script([("POST", CHAT, json_response(reply()))], argv), 0, self.stderr)
        self.assertEqual(self.sent()[0]["messages"], [{"role": "user", "content": (
            "Review these\n\nFile: notes.md\n````\nUse ```code``` here.\n````\n\nFile: a.py\n```\nprint(1)\n```")}])

    def test_a_prompt_of_dash_is_read_from_standard_input(self):
        with mock.patch.object(sys, "stdin", io.StringIO("diff --git a/x b/x\n")):
            self.assertEqual(self.run_script([("POST", CHAT, json_response(reply()))], ["-"]), 0, self.stderr)
        self.assertEqual(self.sent()[0]["messages"], [{"role": "user", "content": "diff --git a/x b/x"}])

    def test_a_prompt_is_required(self):
        for argv in ([], ["   "]):
            with self.assertRaises(SystemExit) as ctx:
                self.run_script([], argv)
            self.assertEqual(ctx.exception.code, 2)

    def test_an_image_goes_to_a_model_that_reads_images(self):
        shot = self.path("shot.png")
        with open(shot, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n-not-a-real-picture-")
        argv = ["What is this?", "--image", shot, "--image", "https://example.com/b.png"]
        self.assertEqual(self.run_script([("POST", CHAT, json_response(reply("vision-chat")))], argv), 0, self.stderr)
        body = self.sent()[0]
        self.assertEqual(body["model"], "vision-chat", "the default with an image is a model that reads images")
        data_uri = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n-not-a-real-picture-").decode("ascii")
        self.assertEqual(body["messages"], [{"role": "user", "content": [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}}]}])

    def test_a_named_model_that_does_not_read_images_is_refused_before_anything_is_sent(self):
        argv = ["What is this?", "--image", "https://example.com/b.png", "--model", "chat-model"]
        self.assertEqual(self.run_script([], argv), 2)
        self.assertIn("chat-model does not read images. Run with --list-models --vision", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_a_media_model_that_lists_a_chat_endpoint_is_refused_before_anything_is_sent(self):
        self.assertEqual(self.run_script([], ["a red circle", "--model", "picture-chat"]), 2)
        self.assertIn("picture-chat is an image model, which answers with media, not text.", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_a_model_without_the_chat_endpoint_is_refused(self):
        self.assertEqual(self.run_script([], ["hello", "--model", "plain-search"]), 2)
        self.assertIn("does not support POST /v1/chat/completions", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_a_model_the_catalog_does_not_know_is_sent_as_given(self):
        routes = [("POST", CHAT, json_response(reply("private-model")))]
        self.assertEqual(self.run_script(routes, ["hello", "--model", "private-model"]), 0, self.stderr)
        self.assertEqual(self.sent()[0]["model"], "private-model")

    def test_several_models_answer_under_their_own_headings_and_one_failure_does_not_stop_the_rest(self):
        busy = json_response({"error": {"message": "The model is busy.", "code": "overloaded"}}, status=503)
        routes = [("POST", CHAT, [json_response(reply()), busy, json_response(reply("vision-chat", "Either works."))])]
        argv = ["Which locking?", "--model", "omni-chat", "--model", "chat-model", "--model", "omni-chat",
                "--model", "vision-chat"]
        self.assertEqual(self.run_script(routes, argv), 1)
        self.assertEqual([body["model"] for body in self.sent()], ["omni-chat", "chat-model", "vision-chat"],
                         "a model named twice is asked once")
        self.assertEqual(self.stdout, "## omni-chat\n\n" + ANSWER + "\n\n## chat-model\n\nNo answer: HTTP 503: "
                                      "The model is busy.\n\n## vision-chat\n\nEither works.\n")
        self.assertIn("chat-model: HTTP 503: The model is busy.", self.stderr)

    def test_an_answer_cut_off_before_it_began_says_so_and_prints_nothing(self):
        empty = reply(content="", finish="length")
        out = self.path("answer.md")
        self.assertEqual(self.run_script([("POST", CHAT, json_response(empty))], ["Think hard", "--out", out]), 1)
        self.assertEqual(self.stdout, "")
        self.assertIn("omni-chat: The model returned no text (finish reason: length). Raise --max-tokens.", self.stderr)
        with self.assertRaises(FileNotFoundError):
            open(out, encoding="utf-8")

    def test_the_answer_is_saved_with_a_summary_and_json_keeps_the_full_result(self):
        routes = [("POST", CHAT, json_response(reply()))]
        out = self.path("answers", "summary.md")
        self.assertEqual(self.run_script(routes, ["Which locking?", "--out", out]), 0, self.stderr)
        self.assertEqual(self.summary(), {"model": "omni-chat", "file": out, "characters": len(ANSWER)})
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), ANSWER + "\n")
        self.assertEqual(self.run_script(routes, ["Which locking?", "--json"]), 0, self.stderr)
        self.assertEqual(json.loads(self.stdout)["usage"]["total_tokens"], 17)
        full = self.path("full.json")
        self.assertEqual(self.run_script(routes, ["Which locking?", "--model", "omni-chat", "--model", "chat-model",
                                                  "--out", full]), 0, self.stderr)
        self.assertEqual(self.summary(), {"models": ["omni-chat", "chat-model"], "file": full,
                                          "characters": 2 * len(ANSWER)})
        with open(full, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual([answer["model"] for answer in saved["answers"]], ["omni-chat", "chat-model"])
        self.assertEqual(saved["answers"][0]["result"]["choices"][0]["finish_reason"], "stop")

    def test_a_refused_request_exits_1(self):
        error = json_response({"error": {"message": "Insufficient credits.", "code": "insufficient_credits"}},
                              status=402)
        self.assertEqual(self.run_script([("POST", CHAT, error)], ["Which locking?"]), 1)
        self.assertIn("Insufficient credits", self.stderr)
        self.assertEqual(self.stdout, "")

    def test_attached_text_has_a_size_limit_and_must_be_text(self):
        big, binary = self.path("big.txt"), self.path("blob.bin")
        with open(big, "wb") as handle:
            handle.write(b"a" * (self.mod.MAX_TEXT_BYTES + 1))
        with open(binary, "wb") as handle:
            handle.write(b"\xff\xfe\x00\x01")
        self.assertEqual(self.run_script([], ["Summarize", "--file", big]), 2)
        self.assertIn("larger than 1024 KB in total", self.stderr)
        self.assertEqual(self.run_script([], ["Summarize", "--file", binary]), 2)
        self.assertIn("is not a UTF-8 text file. Use --image for a picture.", self.stderr)
        self.assertEqual(self.run_script([], ["Summarize", "--file", self.path("missing.txt")]), 2)
        self.assertIn("File not found", self.stderr)
        self.assertEqual(self.transport.find("POST", API), [])

    def test_list_models_marks_the_default_and_vision_lists_only_the_models_that_read_images(self):
        self.assertEqual(self.run_script([], ["--list-models"]), 0)
        self.assertIn("* omni-chat", self.stdout)
        self.assertIn("  chat-model", self.stdout)
        self.assertIn("  vision-chat", self.stdout)
        for other in ("answer-engine", "picture-chat", "star-tts"):
            self.assertNotIn(other, self.stdout, "only text models that answer a chat request are listed")
        self.assertEqual(self.run_script([], ["--list-models", "--vision"]), 0)
        self.assertEqual(self.stdout.split()[0:2], ["*", "vision-chat"])
        self.assertNotIn("omni-chat", self.stdout)


if __name__ == "__main__":
    unittest.main()
