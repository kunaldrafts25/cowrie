# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from cowrie.shell.protocol import HoneyPotInteractiveProtocol
from cowrie.test.fake_server import FakeAvatar, FakeServer
from cowrie.test.fake_transport import FakeTransport

os.environ["COWRIE_HONEYPOT_DATA_PATH"] = "data"
os.environ["COWRIE_SHELL_FILESYSTEM"] = "src/cowrie/data/fs.pickle"
PROMPT = b"root@unitTest:~# "


class RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files = tempfile.TemporaryDirectory()
        self.addCleanup(self.files.cleanup)
        self.proto = HoneyPotInteractiveProtocol(FakeAvatar(FakeServer()))
        self.tr = FakeTransport("", "31337")
        self.proto.makeConnection(self.tr)
        self.addCleanup(self.proto.connectionLost)
        self.tr.clear()

    def run_line(self, line: bytes) -> bytes:
        self.tr.clear()
        self.proto.lineReceived(line)
        result = self.tr.value()
        self.assertTrue(result.endswith(PROMPT), result)
        return result[: -len(PROMPT)]

    def file(self, path: str, data: bytes) -> None:
        backing = Path(self.files.name) / str(
            len(list(Path(self.files.name).iterdir()))
        )
        backing.write_bytes(data)
        self.proto.fs.mkfile(path, 0, 0, len(data), stat.S_IFREG | 0o644)
        self.proto.fs.update_realfile(self.proto.fs.getfile(path), str(backing))

    def test_invalid_operands(self) -> None:
        for arg in (b"broken", b"unknown=1", b"count=nope", b"count=-1", b"bs=0"):
            with self.subTest(arg=arg):
                output = self.run_line(b"printf abc | dd " + arg + b"; echo rc=$?")
                self.assertIn(b"dd:", output)
                self.assertTrue(output.endswith(b"rc=1\n"), output)

    def test_piped_count(self) -> None:
        self.assertEqual(
            self.run_line(b"printf abcdef | dd bs=2 count=2 2>/dev/null"), b"abcd"
        )

    def test_zero_count(self) -> None:
        self.assertEqual(self.run_line(b"printf abc | dd count=0 2>/dev/null"), b"")

    def test_file_overrides_pipeline(self) -> None:
        self.file("/tmp/source", b"FILE")
        self.assertEqual(
            self.run_line(b"printf PIPE | dd if=/tmp/source 2>/dev/null"), b"FILE"
        )

    def test_equals_in_filename(self) -> None:
        self.file("/tmp/a=b", b"data")
        self.assertEqual(self.run_line(b"dd if=/tmp/a=b 2>/dev/null"), b"data")

    def test_bare_pipeline(self) -> None:
        self.assertEqual(self.run_line(b"printf abc | dd 2>/dev/null"), b"abc")
