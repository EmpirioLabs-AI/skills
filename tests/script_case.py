"""Base class for script tests: loads a skill script and fakes its HTTP transport."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from helpers import TEST_KEY, CatalogTransport, captured, load_script


class ScriptCase(unittest.TestCase):
    skill = None
    script = None

    def setUp(self):
        self.mod = load_script(self.skill, self.script)
        self.api = self.mod.api
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (mock.patch.dict(os.environ, {"EMPIRIOLABS_API_KEY": TEST_KEY}),
                        mock.patch.object(self.api.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def path(self, *parts):
        return os.path.join(self.tmp.name, *parts)

    def run_script(self, routes, argv):
        transport = CatalogTransport(routes)
        with mock.patch.object(self.api, "_open", transport):
            with captured() as (out, err):
                code = self.mod.main(argv)
        self.transport = transport
        self.stdout = out.getvalue()
        self.stderr = err.getvalue()
        self.assertNotIn(TEST_KEY, self.stdout + self.stderr, "the API key must never be printed")
        return code

    def summary(self):
        return json.loads(self.stdout)
