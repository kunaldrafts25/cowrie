# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from twisted.internet.testing import StringTransport

from backend_pool.pool_server import PoolServer
from cowrie.pool_interface.client import PoolClient


class PoolStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict(
            os.environ,
            {
                "COWRIE_BACKEND_POOL_USE_NAT": "false",
                "COWRIE_BACKEND_POOL_POOL_ONLY": "false",
                "COWRIE_PROXY_POOL": "local",
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def server(self):
        service = Mock()
        service.request_vm.return_value = (7, "192.0.2.1", "/snapshot")
        factory = SimpleNamespace(pool_service=service, initialised=False)
        protocol = PoolServer(factory)
        protocol.makeConnection(StringTransport())
        return protocol, service

    def client(self):
        protocol = PoolClient(None)
        protocol.makeConnection(StringTransport())
        parent = Mock()
        protocol.set_parent(parent)
        return protocol, parent

    def response(self) -> bytes:
        ip = b"192.0.2.1"
        snapshot = b"/snapshot"
        return (
            struct.pack("!cIIH", b"r", 0, 7, len(ip))
            + ip
            + struct.pack("!HHH", 22, 23, len(snapshot))
            + snapshot
        )

    def test_server_split_at_every_boundary(self) -> None:
        message = struct.pack("!cH", b"r", 9) + b"192.0.2.2"
        for boundary in range(1, len(message)):
            with self.subTest(boundary=boundary):
                protocol, service = self.server()
                protocol.dataReceived(message[:boundary])
                service.request_vm.assert_not_called()
                protocol.dataReceived(message[boundary:])
                service.request_vm.assert_called_once_with("192.0.2.2")

    def test_server_coalesced_requests(self) -> None:
        protocol, service = self.server()
        protocol.dataReceived(
            struct.pack("!cII?", b"i", 2, 600, True)
            + struct.pack("!cI", b"f", 7)
            + struct.pack("!cI", b"u", 8)
        )
        service.set_configs.assert_called_once_with(2, 600, True)
        service.free_vm.assert_called_once_with(7)
        service.reuse_vm.assert_called_once_with(8)
        self.assertEqual(protocol.transport.value(), struct.pack("!cI", b"i", 0))

    def test_server_bytewise_requests(self) -> None:
        protocol, service = self.server()
        for byte in struct.pack("!cI", b"f", 7) + struct.pack("!cI", b"u", 8):
            protocol.dataReceived(bytes([byte]))
        service.free_vm.assert_called_once_with(7)
        service.reuse_vm.assert_called_once_with(8)

    def test_server_unknown_opcode_disconnects(self) -> None:
        protocol, _ = self.server()
        protocol.dataReceived(b"?")
        self.assertTrue(protocol.transport.disconnecting)

    def test_client_split_at_every_boundary(self) -> None:
        message = self.response()
        for boundary in range(1, len(message)):
            with self.subTest(boundary=boundary):
                protocol, parent = self.client()
                protocol.dataReceived(message[:boundary])
                parent.received_pool_data.assert_not_called()
                self.assertIsNone(protocol.vm_id)
                protocol.dataReceived(message[boundary:])
                parent.received_pool_data.assert_called_once_with(
                    b"r", 0, b"192.0.2.1", b"/snapshot", 22, 23
                )
                self.assertEqual(protocol.vm_id, 7)

    def test_client_coalesced_responses(self) -> None:
        protocol, parent = self.client()
        protocol.dataReceived(struct.pack("!cI", b"i", 0) + self.response())
        parent.initialisation_response.assert_called_once_with(0)
        parent.received_pool_data.assert_called_once()

    def test_client_bytewise_responses(self) -> None:
        protocol, parent = self.client()
        for byte in struct.pack("!cI", b"i", 0) + self.response():
            protocol.dataReceived(bytes([byte]))
        parent.initialisation_response.assert_called_once_with(0)
        parent.received_pool_data.assert_called_once()

    def test_client_split_error_response(self) -> None:
        protocol, parent = self.client()
        message = struct.pack("!cI", b"r", 1)
        protocol.dataReceived(message[:2])
        parent.loseConnection.assert_not_called()
        protocol.dataReceived(message[2:])
        parent.loseConnection.assert_called_once()
        parent.received_pool_data.assert_not_called()

    def test_empty_reads_are_noops(self) -> None:
        server, _ = self.server()
        client, _ = self.client()
        server.dataReceived(b"")
        client.dataReceived(b"")

    def test_client_unknown_opcode_disconnects(self) -> None:
        protocol, _ = self.client()
        protocol.dataReceived(b"?" + bytes(4))
        self.assertTrue(protocol.transport.disconnecting)

    def test_initialisation_split_at_every_boundary(self) -> None:
        message = struct.pack("!cII?", b"i", 2, 600, True)
        for boundary in range(1, len(message)):
            with self.subTest(boundary=boundary):
                protocol, service = self.server()
                protocol.dataReceived(message[:boundary])
                service.set_configs.assert_not_called()
                protocol.dataReceived(message[boundary:])
                service.set_configs.assert_called_once_with(2, 600, True)

    def test_disconnect_discards_incomplete_messages(self) -> None:
        for protocol, _ in (self.server(), self.client()):
            protocol.dataReceived(b"r")
            protocol.connectionLost(None)
            self.assertEqual(protocol._buffer, b"")
            protocol.dataReceived(b"ignored")
            self.assertEqual(protocol._buffer, b"")
