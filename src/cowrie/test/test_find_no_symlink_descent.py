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

    def link(self, path: str, target: str) -> None:
        self.proto.fs._ensure_private_fs()
        self.proto.fs.get_path("/tmp").append(
            [path, fs.T_LINK, 0, 0, 0, 0o777, 0, [], target, None]
        )

    def test_directory_link_not_descended(self) -> None:
        self.proto.fs.mkdir("/tmp/tree", 0, 0, 4096, stat.S_IFDIR | 0o755)
        self.file("/tmp/tree/file", b"data")
        self.link("dirlink", "/tmp/tree")
        self.assertEqual(self.run_line(b"find /tmp/dirlink"), b"/tmp/dirlink\n")

    def test_dangling_link_is_reported(self) -> None:
        self.link("dangling", "/missing")
        self.assertEqual(self.run_line(b"find /tmp/dangling"), b"/tmp/dangling\n")

    def test_link_does_not_match_target_type(self) -> None:
        self.link("dirlink", "/tmp")
        self.assertEqual(self.run_line(b"find /tmp/dirlink -type d"), b"")
        self.file("/tmp/source", b"data")
        self.link("filelink", "/tmp/source")
        self.assertEqual(self.run_line(b"find /tmp/filelink -type f"), b"")

    def test_regular_directory_still_descended(self) -> None:
        self.proto.fs.mkdir("/tmp/tree", 0, 0, 4096, stat.S_IFDIR | 0o755)
        self.file("/tmp/tree/file", b"data")
        self.assertEqual(
            set(self.run_line(b"find /tmp/tree").splitlines()),
            {b"/tmp/tree", b"/tmp/tree/file"},
        )
