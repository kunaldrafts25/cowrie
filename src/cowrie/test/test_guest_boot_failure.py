# SPDX-FileCopyrightText: 2026 Kunal Singh
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend_pool import util
from backend_pool.libvirt import backend_service, guest_handler, snapshot_handler
from backend_pool.pool_service import PoolService
from cowrie.core.config import CowrieConfig


class FakeLibvirtError(Exception):
    pass


class GuestBootFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        libvirt = SimpleNamespace(libvirtError=FakeLibvirtError)
        override = patch.dict("sys.modules", {"libvirt": libvirt})
        override.start()
        self.addCleanup(override.stop)

    def test_domain_creation_failure_is_recoverable(self) -> None:
        connection = Mock()
        connection.createXML.return_value = None
        with (
            patch.object(CowrieConfig, "get", return_value="image"),
            patch.object(CowrieConfig, "getint", return_value=128),
            patch.object(os.path, "isfile", return_value=True),
            patch.object(guest_handler, "_log"),
            patch.object(os, "remove") as remove,
            patch.object(
                util,
                "read_pool_config",
                return_value="<domain/>",
            ),
            patch.object(
                snapshot_handler,
                "create_disk_snapshot",
                return_value=True,
            ),
        ):
            with self.assertRaises(guest_handler.QemuGuestError):
                guest_handler.create_guest(connection, "00:11:22:33:44:55", "test")
            remove.assert_called_once()

    def make_service(self):
        service = backend_service.LibvirtBackendService.__new__(
            backend_service.LibvirtBackendService
        )
        service.ready = True
        service.conn = Mock()
        override = patch.object(
            service, "get_mac_ip", return_value=("00:11:22:33:44:55", "192.0.2.1")
        )
        override.start()
        self.addCleanup(override.stop)
        return service

    def test_backend_skips_recoverable_guest_and_libvirt_errors(self) -> None:
        for failure in (guest_handler.QemuGuestError(), FakeLibvirtError()):
            with self.subTest(failure=type(failure).__name__):
                service = self.make_service()
                with (
                    patch.object(guest_handler, "create_guest", side_effect=failure),
                    patch.object(backend_service.LibvirtBackendService, "_log"),
                ):
                    self.assertIsNone(service.create_guest(lambda _: True))

    def test_backend_returns_successful_guest(self) -> None:
        service = self.make_service()
        domain = Mock()
        with patch.object(
            guest_handler, "create_guest", return_value=(domain, "snapshot")
        ):
            self.assertEqual(
                service.create_guest(lambda _: True), (domain, "snapshot", "192.0.2.1")
            )

    def test_backend_does_not_hide_unexpected_programming_error(self) -> None:
        service = self.make_service()
        with patch.object(
            guest_handler, "create_guest", side_effect=ValueError("unexpected")
        ):
            with self.assertRaises(ValueError):
                service.create_guest(lambda _: True)

    def test_unready_backend_does_not_create_guest(self) -> None:
        service = self.make_service()
        service.ready = False
        with patch.object(guest_handler, "create_guest") as create:
            self.assertIsNone(service.create_guest(lambda _: True))
        create.assert_not_called()

    def test_pool_retries_failed_creation_on_next_iteration(self) -> None:
        pool = PoolService.__new__(PoolService)
        pool.guests = []
        pool.guest_id = 0
        pool.max_vm = 1
        domain = Mock()
        pool.qemu = Mock()
        pool.qemu.create_guest.side_effect = [None, (domain, "snapshot", "192.0.2.1")]
        pool._PoolService__producer_create_guests()  # type: ignore[attr-defined]
        self.assertEqual(pool.guests, [])
        pool._PoolService__producer_create_guests()  # type: ignore[attr-defined]
        self.assertEqual(len(pool.guests), 1)
        self.assertIs(pool.guests[0].domain, domain)
