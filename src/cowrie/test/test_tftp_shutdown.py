# SPDX-FileCopyrightText: 2026 Kunal Singh
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from twisted.internet.task import Clock

from cowrie.commands.tftp import TFTPClient
from cowrie.core.artifact import Artifact


class TftpShutdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = patch.object(Artifact, "artifactDir", self.directory.name)
        override.start()
        self.addCleanup(override.stop)
        self.artifact = Artifact("interrupted-transfer")
        self.addCleanup(self.artifact.close)
        self.client = TFTPClient("192.0.2.1", 69, "sample", self.artifact)

    def test_shutdown_removes_empty_artifact(self) -> None:
        temporary = self.artifact.tempFilename
        self.client.stopProtocol()
        self.assertTrue(self.artifact.closed)
        self.assertFalse(os.path.exists(temporary))
        self.assertFalse(self.client.deferred.called)

    def test_shutdown_preserves_partial_bytes_under_content_hash(self) -> None:
        content = b"partial transfer"
        self.artifact.write(content)
        temporary = self.artifact.tempFilename
        self.client.stopProtocol()
        expected = Path(self.directory.name) / hashlib.sha256(content).hexdigest()
        self.assertFalse(os.path.exists(temporary))
        self.assertEqual(expected.read_bytes(), content)
        self.assertEqual(self.artifact.shasumFilename, str(expected))

    def test_shutdown_cancels_timeout_and_is_idempotent(self) -> None:
        clock = Clock()
        self.client.timeout_call = clock.callLater(5, self.fail, "stale timeout")
        self.client.stopProtocol()
        self.client.stopProtocol()
        clock.advance(10)
        self.assertEqual(clock.getDelayedCalls(), [])
        self.assertTrue(self.artifact.closed)

    def test_completed_transfer_uses_existing_completion_cleanup(self) -> None:
        self.client.deferred.callback(None)
        with patch.object(self.artifact, "close") as close:
            self.client.stopProtocol()
        close.assert_not_called()

    def test_shutdown_does_not_invoke_transfer_callbacks(self) -> None:
        callbacks = Mock()
        self.client.deferred.addBoth(callbacks)
        self.client.stopProtocol()
        callbacks.assert_not_called()
        self.assertTrue(self.artifact.closed)
