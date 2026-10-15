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

    def test_out_of_order(self) -> None:
        self.assertEqual(self.run_line(b"echo a:b:c | cut -d: -f3,1"), b"a:c\n")

    def test_overlapping(self) -> None:
        self.assertEqual(
            self.run_line(b"echo a:b:c:d | cut -d: -f1-3,2-"), b"a:b:c:d\n"
        )

    def test_duplicate(self) -> None:
        self.assertEqual(self.run_line(b"echo a:b:c | cut -d: -f2,2"), b"b\n")

    def test_invalid_ranges(self) -> None:
        for spec in (b"0", b"0-2", b"2-0", b"3-1", b"-", b"1,,2"):
            with self.subTest(spec=spec):
                output = self.run_line(
                    b"echo a:b:c | cut -d: -f" + spec + b"; echo rc=$?"
                )
                self.assertIn(b"cut: invalid field value", output)
                self.assertTrue(output.endswith(b"rc=1\n"), output)
