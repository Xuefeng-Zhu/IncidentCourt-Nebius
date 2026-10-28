"""Fixture-only status metadata checks; no remote SQL, model call or real receipt."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from incidentcourt import server
from incidentcourt.workspace import source_context

class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_sample_source_label_distinguishes_nebius_from_offline_without_changing_identity(self):
        with patch.dict(os.environ, {'SAMPLE_MODE': 'true', 'INCIDENTCOURT_NEBIUS_SAMPLE': '0'}, clear=True):
            offline = source_context()
        with patch.dict(os.environ, {'SAMPLE_MODE': 'true', 'INCIDENTCOURT_NEBIUS_SAMPLE': '1'}, clear=True):
            nebius = source_context()
        self.assertEqual(offline['label'], 'Offline sample')
        self.assertEqual(nebius['label'], 'Sample telemetry + Nebius mode')
        self.assertEqual(offline['id'], nebius['id'])

    def test_local_mode_does_not_configure_a_provider(self):
        with patch.object(server, 'ROOT', self.root), patch.dict(os.environ, {
                'SAMPLE_MODE': 'false', 'INCIDENTCOURT_DATA_MODE': 'zetaris'}, clear=True), \
             patch.object(server, 'HMemStore') as memory:
            memory.return_value.status.return_value = {'state': 'working'}
            value = server.status()
            self.assertEqual(value['model']['provider'], 'local')
            self.assertFalse(value['model']['inference_enabled'])
            self.assertIsNone(value['last_verified'])


class UIAuthorizationTests(unittest.TestCase):
    def test_nebius_requires_explicit_inference_enablement(self):
        script = r"""
const assert = require('node:assert/strict');
const {canExecuteInvestigation, canStartWorkspaceInvestigation} = require('./incidentcourt/static/app.js');
const sample = {data:{mode:'sample'}, model:{provider:'nebius',inference_enabled:false}};
assert.equal(canExecuteInvestigation(sample,'nebius'),false);
assert.equal(canStartWorkspaceInvestigation(sample,'sample'),false);
const enabled = {...sample,model:{...sample.model,inference_enabled:true}};
assert.equal(canExecuteInvestigation(enabled,'nebius'),true);
assert.equal(canStartWorkspaceInvestigation(enabled,'sample'),true);
assert.equal(canExecuteInvestigation(sample,'nightshift'),false);
"""
        result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
