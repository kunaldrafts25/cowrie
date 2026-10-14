# SPDX-FileCopyrightText: 2026 Kunal Singh
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import unittest
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from twisted.internet import defer, task, threads
from twisted.python.failure import Failure

from backend_pool import pool_service
from backend_pool.pool_service import PoolService
from cowrie.core.config import CowrieConfig


class PoolSchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = task.Clock()
        self.workers: list = []
        self.pool = PoolService.__new__(PoolService)
        self.pool.qemu = Mock()
        self.pool.nat_service = Mock()
        self.pool.guests = []
        self.pool.guest_id = 0
        self.pool.guest_lock = Lock()
        self.pool.loop_sleep_time = 5
        self.pool.loop_next_call = None
        self.pool._pool_running = False
        self.pool._pool_generation = 0
        self.pool._producer_inflight = False
        self.pool.local_pool = True
        self.pool.pool_only = False
        self.pool.use_nat = False
        self.pool.max_vm = 0
        self.pool.vm_unused_timeout = 600
        self.libvirt = SimpleNamespace(libvirtError=RuntimeError)
        logger = patch.object(PoolService, "_log")
        self.logger = logger.start()
        self.addCleanup(logger.stop)
        for override in (
            patch.object(pool_service, "reactor", self.clock),
            patch.object(
                threads, "deferToThread", side_effect=self.submit
            ),
            patch.object(CowrieConfig, "getint", return_value=-1),
            patch.dict("sys.modules", {"libvirt": self.libvirt}),
        ):
            override.start()
            self.addCleanup(override.stop)

    def submit(self, function):
        result = defer.Deferred()
        self.workers.append((function, result))
        return result

    def test_every_iteration_uses_worker_and_waits_for_previous_completion(
        self,
    ) -> None:
        self.pool.start_pool()
        self.assertEqual(len(self.workers), 1)
        self.clock.advance(20)
        self.assertEqual(len(self.workers), 1)
        self.workers[0][1].callback(None)
        self.clock.advance(4)
        self.assertEqual(len(self.workers), 1)
        self.clock.advance(1)
        self.assertEqual(len(self.workers), 2)
        self.assertEqual(self.workers[1][0], self.pool.producer_loop)
        self.workers[1][1].callback(None)
        self.clock.advance(5)
        self.assertEqual(len(self.workers), 3)

    def test_stop_cancels_pending_iteration(self) -> None:
        self.pool.start_pool()
        self.workers[0][1].callback(None)
        self.pool.stop_pool()
        self.clock.advance(10)
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_worker_finishing_after_stop_does_not_restart_pool(self) -> None:
        self.pool.start_pool()
        self.pool.stop_pool()
        self.workers[0][1].callback(None)
        self.clock.advance(10)
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_worker_failure_is_logged_and_next_iteration_is_scheduled(self) -> None:
        self.pool.start_pool()
        self.workers[0][1].errback(Failure(RuntimeError("probe failed")))
        self.logger.failure.assert_called_once()
        self.clock.advance(5)
        self.assertEqual(len(self.workers), 2)

    def test_restart_waits_for_inflight_worker_and_discards_old_schedule(self) -> None:
        self.pool.start_pool()
        self.pool.restart_pool()
        self.assertEqual(len(self.workers), 1)
        self.workers[0][1].callback(None)
        self.clock.advance(0)
        self.assertEqual(len(self.workers), 2)
        self.workers[1][1].callback(None)
        self.clock.advance(5)
        self.assertEqual(len(self.workers), 3)

    def test_worker_body_does_not_schedule_reactor_callbacks(self) -> None:
        with patch.object(self.pool, "has_connectivity", return_value=False):
            self.pool.producer_loop()
        self.assertEqual(self.clock.getDelayedCalls(), [])
