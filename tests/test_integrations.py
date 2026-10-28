"""Local H-MEM contract tests."""
import json
import tempfile
import threading
import unittest
import os
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from incidentcourt.integrations import HMemStore, IntegrationError

class MemoryTest(unittest.TestCase):
    def test_real_engine_persistence_recall_exclusion_and_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = HMemStore(directory)
            finding = "Redis latency and server errors require trace checks before a database diagnosis."
            a = memory.remember_verified("INC-001", finding, ["trace-1", "metric-2"], ["redis"], "reviewed-evidence")
            result = HMemStore(directory).retrieve(finding, "INC-002")
            self.assertEqual(result["memories"][0]["memory"]["id"], a["id"])
            self.assertIn(finding, result["context"])
            self.assertEqual(result["trace"]["engine"], "Meterless H-MEM reference")
            self.assertEqual(memory.retrieve(finding, "INC-001")["memories"], [])
            self.assertEqual(memory.status()["ledger"], {"create": 1, "read": 1})
            self.assertEqual(memory.audit()[0]["newState"]["provenance"]["refs"], ["INC-001:trace-1", "INC-001:metric-2"])
    def test_holdout_and_unverified_findings_cannot_enter_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = HMemStore(directory)
            with self.assertRaises(ValueError):
                memory.remember_verified("INC-099", "An unsupported finding", ["trace-1"], [], "reviewer", split="holdout")
            with self.assertRaises(ValueError):
                memory.remember_verified("INC-001", "An unsupported finding", [], [], "reviewer")
            with self.assertRaises(ValueError):
                memory.remember_verified("INC-001", "An unsupported finding", ["trace-1"], [], "")
    def test_explicit_service_scope_is_applied_before_official_ranker(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = HMemStore(directory)
            finding = "resource latency incident baseline dependency checkout cpu mean increased"
            memory.remember_verified("IC-001", finding, ["metric-1"], ["checkout"], "reviewer")
            excluded = memory.retrieve(finding, "IC-002", services=("currency",))
            self.assertEqual(excluded["memories"], [])
            self.assertEqual(excluded["trace"]["eligibleCount"], 0)
            recalled = memory.retrieve(finding, "IC-002", services=("checkout",))
            self.assertEqual(len(recalled["memories"]), 1)
            self.assertEqual(recalled["trace"]["eligibleServiceScope"], ["checkout"])

    def test_duplicate_findings_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = HMemStore(directory)
            for _ in range(2):
                memory.remember_verified("INC-001", "Redis service latency changed.", ["metric-1"], ["redis"], "reviewer")
            self.assertEqual(memory.status()["memories"], 1)


if __name__ == '__main__': unittest.main()
