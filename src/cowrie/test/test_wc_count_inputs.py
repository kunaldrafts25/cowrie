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

    def test_first_file_is_not_discarded(self) -> None:
        self.file("/tmp/counts", b"one two\n")
        self.assertEqual(self.run_line(b"wc -w /tmp/counts").split(), [b"2"])

    def test_default_counts_for_pipeline(self) -> None:
        self.assertEqual(
            self.run_line(b"printf 'one two\\n' | wc").split(), [b"1", b"2", b"8"]
        )

    def test_whitespace_and_empty_input(self) -> None:
        self.assertEqual(self.run_line(b"printf 'a\\tb\\nc' | wc -w").split(), [b"3"])
        self.assertEqual(self.run_line(b"printf '' | wc -w").split(), [b"0"])

    def test_multiple_options_canonical_order(self) -> None:
        self.assertEqual(
            self.run_line(b"printf 'a b\\n' | wc -cwl").split(), [b"1", b"2", b"4"]
        )

    def test_all_files_are_counted(self) -> None:
        self.file("/tmp/first", b"a")
        self.file("/tmp/second", b"b c")
        self.assertEqual(
            self.run_line(b"wc -w /tmp/first /tmp/second").split(), [b"1", b"2"]
        )

    def test_interactive_input(self) -> None:
        self.proto.lineReceived(b"wc -w")
        self.proto.lineReceived(b"one two")
        self.proto.handle_CTRL_D()
        self.assertEqual(self.tr.value(), b"2\n" + PROMPT)

    def test_missing_file_sets_failure(self) -> None:
        output = self.run_line(b"wc -w /missing; echo rc=$?")
        self.assertIn(b"No such file", output)
        self.assertTrue(output.endswith(b"rc=1\n"), output)
