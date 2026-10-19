"""Test helpers: a fake HTTP transport, a script loader, and a small YAML reader.

Standard library only. Nothing here touches the network: every test replaces the
single `_open` function that the scripts use for HTTP.
"""

from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import json
import os
import sys
import urllib.error
import urllib.parse

sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
TEST_KEY = "sk-empiriolabs-unit-test-key-0123456789"


class FakeHeaders(dict):
    """Case-insensitive enough for urllib-style access in the scripts."""

    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self._buffer = io.BytesIO(body)
        self.headers = FakeHeaders(headers or {})

    def read(self, size=-1):
        return self._buffer.read() if size is None or size < 0 else self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def json_response(payload, status=200, gzip_body=False, headers=None):
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if gzip_body:
        body = gzip.compress(body)
        hdrs["Content-Encoding"] = "gzip"
    hdrs.update(headers or {})
    return status, body, hdrs


def bytes_response(body, content_type, status=200):
    return status, body, {"Content-Type": content_type}


class FakeTransport:
    """Routes requests to canned responses and records everything that was sent.

    routes: list of (method, matcher, responses). matcher is a URL prefix or a
    callable(url). responses is one (status, body, headers) tuple or a list that is
    consumed in order (the last entry repeats).
    """

    def __init__(self, routes):
        self.routes = [[m, matcher, list(r) if isinstance(r, list) else [r]] for m, matcher, r in routes]
        self.calls = []

    def __call__(self, req, timeout):
        url = req.full_url
        method = req.get_method()
        headers = {k.lower(): v for k, v in req.header_items()}
        self.calls.append({"method": method, "url": url, "headers": headers, "body": req.data, "timeout": timeout})
        for route in self.routes:
            route_method, matcher, responses = route
            if route_method != method:
                continue
            if callable(matcher) and not matcher(url):
                continue
            if isinstance(matcher, str) and not url.startswith(matcher):
                continue
            status, body, hdrs = responses[0] if len(responses) == 1 else responses.pop(0)
            if isinstance(status, Exception):
                raise status
            if status >= 400:
                raise urllib.error.HTTPError(url, status, "error", FakeHeaders(hdrs), io.BytesIO(body))
            return FakeResponse(status, body, hdrs)
        raise AssertionError("unexpected request: " + method + " " + url)

    def find(self, method, prefix):
        return [c for c in self.calls if c["method"] == method and c["url"].startswith(prefix)]

    def json_body(self, method, prefix):
        calls = self.find(method, prefix)
        assert calls, "no " + method + " " + prefix
        return json.loads(calls[-1]["body"].decode("utf-8"))


def load_script(skill, script):
    """Import skills/<skill>/scripts/<script>.py with its own copy of the API client."""
    folder = os.path.join(SKILLS, skill, "scripts")
    sys.modules.pop("empiriolabs_api", None)
    name = "skill_" + skill.replace("-", "_") + "_" + script
    spec = importlib.util.spec_from_file_location(name, os.path.join(folder, script + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules.pop("empiriolabs_api", None)
    return module


def load_shared():
    spec = importlib.util.spec_from_file_location("shared_empiriolabs_api", os.path.join(ROOT, "shared", "empiriolabs_api.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def captured():
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        yield out, err
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def url_query(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# ---------------------------------------------------------------------------
# Catalog fixtures
# ---------------------------------------------------------------------------

def model(model_id, endpoint, category, featured=False, native=False, features=None, params=None, rows=None):
    return {
        "id": model_id,
        "display_name": model_id.replace("-", " ").title(),
        "category": category,
        "status": "available",
        "is_featured": featured,
        "native_inference": native,
        "features": features or [],
        "supported_endpoints": [endpoint] if isinstance(endpoint, str) else endpoint,
        "supported_parameters": params or [],
        "pricing_rows": rows if rows is not None else [{"label": "Standard", "value": "$0.01", "spec": "per unit"}],
        "api_url": "https://docs.empiriolabs.ai/models/" + model_id,
        "chat_url": "https://platform.empiriolabs.ai/dashboard/playground?model=" + model_id,
        "description": "Test model " + model_id,
        "aliases": [],
    }


IMG = "POST /v1/images/generations"
VID = "POST /v1/videos/generations"
TTS = "POST /v1/audio/speech"
STT = "POST /v1/audio/transcriptions"


def catalog():
    return {
        "object": "list",
        "categories": [
            {"name": "Image Generation", "slug": "image", "order": 2},
            {"name": "Video Generation", "slug": "video", "order": 3},
            {"name": "Audio Generation", "slug": "audio", "order": 4},
            {"name": "Transcription", "slug": "transcription", "order": 5},
            {"name": "Text Generation", "slug": "text", "order": 1},
        ],
        "data": [
            model("plain-image", IMG, "image"),
            model("star-image", IMG, "image", featured=True,
                  params=[{"name": "format", "type": "enum", "options": ["webp", "png", "jpg"]}]),
            model("star-native-image", IMG, "image", featured=True, native=True,
                  params=[{"name": "format", "type": "enum", "options": ["webp", "png", "jpeg"]}]),
            model("edit-image", IMG, "image", featured=True, features=["image_editing"]),
            model("star-video", VID, "video", featured=True, native=True),
            model("other-video", VID, "video"),
            model("omni-chat", [TTS, "POST /v1/chat/completions"], "text", featured=True, native=True),
            model("star-tts", [TTS, "GET /v1/voices"], "audio", featured=True,
                  params=[{"name": "input", "type": "string", "required": True, "max": 50},
                          {"name": "output_format", "type": "enum", "options": ["MP3", "WAV", "OGG"]},
                          {"name": "voice", "type": "enum", "options": ["Sarah", "Mark"]}]),
            model("plain-tts", TTS, "audio",
                  params=[{"name": "voice", "type": "enum", "options": ["Ana", "Ben"]}]),
            model("star-stt", STT, "transcription", featured=True, native=True),
            model("other-stt", STT, "transcription"),
            model("chat-model", "POST /v1/chat/completions", "text", featured=True,
                  features=["reasoning", "function_calling"], rows=[]),
        ],
    }


def catalog_entry(model_id):
    for entry in catalog()["data"]:
        if entry["id"] == model_id:
            return entry
    return None


API = "https://api.empiriolabs.ai/v1"
CDN = "https://media.example.com/outputs/"


class CatalogTransport(FakeTransport):
    """FakeTransport that also answers catalog reads from the fixture."""

    def __call__(self, req, timeout):
        url = req.full_url
        path = urllib.parse.urlsplit(url).path
        if req.get_method() == "GET" and path == "/v1/models":
            self.calls.append({"method": "GET", "url": url, "headers": {k.lower(): v for k, v in req.header_items()},
                               "body": None, "timeout": timeout})
            status, body, hdrs = json_response(catalog(), gzip_body=True)
            return FakeResponse(status, body, hdrs)
        if req.get_method() == "GET" and path.startswith("/v1/models/"):
            self.calls.append({"method": "GET", "url": url, "headers": {k.lower(): v for k, v in req.header_items()},
                               "body": None, "timeout": timeout})
            entry = catalog_entry(urllib.parse.unquote(path[len("/v1/models/"):]))
            if entry is None:
                raise urllib.error.HTTPError(url, 404, "not found", FakeHeaders({}),
                                             io.BytesIO(b'{"error":{"code":"model_not_found","message":"Model not found."}}'))
            status, body, hdrs = json_response(entry)
            return FakeResponse(status, body, hdrs)
        return super().__call__(req, timeout)


# ---------------------------------------------------------------------------
# Minimal YAML reader for SKILL.md frontmatter (block style only)
# ---------------------------------------------------------------------------

def _scalar(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    return text


def _parse_block(lines, start, indent):
    """Parse lines[start:] at the given indent. Returns (value, next_index)."""
    if start >= len(lines):
        return None, start
    first = lines[start]
    if first[1].startswith("- "):
        items = []
        i = start
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            content = lines[i][1][2:]
            if ":" in content and not content.startswith(("\"", "'")) and ": " in content + " ":
                key, _, rest = content.partition(":")
                item = {key.strip(): _scalar(rest)} if rest.strip() else {key.strip(): None}
                i += 1
                while i < len(lines) and lines[i][0] > indent:
                    sub_indent = lines[i][0]
                    key2, _, rest2 = lines[i][1].partition(":")
                    if rest2.strip():
                        item[key2.strip()] = _scalar(rest2)
                        i += 1
                    else:
                        value, i = _parse_block(lines, i + 1, lines[i + 1][0] if i + 1 < len(lines) else sub_indent + 2)
                        item[key2.strip()] = value
                items.append(item)
            else:
                items.append(_scalar(content))
                i += 1
        return items, i
    mapping = {}
    i = start
    while i < len(lines) and lines[i][0] == indent:
        key, _, rest = lines[i][1].partition(":")
        if rest.strip():
            mapping[key.strip()] = _scalar(rest)
            i += 1
        else:
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1][0])
            elif i + 1 < len(lines) and lines[i + 1][0] == indent and lines[i + 1][1].startswith("- "):
                value, i = _parse_block(lines, i + 1, indent)
            else:
                value, i = None, i + 1
            mapping[key.strip()] = value
    return mapping, i


def read_frontmatter(path):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert text.startswith("---\n"), path + " must start with frontmatter"
    end = text.index("\n---\n", 4)
    raw = text[4:end]
    lines = []
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip(" ")
        lines.append((len(line) - len(stripped), stripped))
    value, _ = _parse_block(lines, 0, 0)
    return value, raw, text[end + 5:]
