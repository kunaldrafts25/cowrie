# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from cowrie.shell import fs
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

    def test_binary_pipeline(self) -> None:
        self.assertEqual(self.run_line(b"printf '\\377\\0x' | tee"), b"\xff\x00x")

    def test_unterminated_pipeline(self) -> None:
        self.assertEqual(self.run_line(b"printf abc | tee"), b"abc")

    def test_empty_pipeline(self) -> None:
        self.assertEqual(
            self.run_line(b"printf '' | tee; echo finished"), b"finished\n"
        )

    def test_file_size(self) -> None:
        self.assertEqual(
            self.run_line(b"printf '\\377\\0x' | tee /tmp/exact"), b"\xff\x00x"
        )
        self.assertEqual(self.proto.fs.getfile("/tmp/exact")[fs.A_SIZE], 3)
