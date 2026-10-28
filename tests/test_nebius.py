"""Contract tests use a fake HTTP transport and do not establish live Nebius usage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from incidentcourt.integrations import IntegrationError
from incidentcourt.nebius import NebiusClient, BASE_URL
from incidentcourt import server
from incidentcourt.workspace import Workspace, JobManager, WorkspaceError
import threading

MODEL = 'nvidia/nemotron-3-super-120b-a12b'


class Reply:
    def __init__(self, value): self.value = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return self.value


class FakeTransport:
    def __init__(self, served=MODEL, advertise=True):
        self.served, self.advertise, self.requests = served, advertise, []
    def open(self, req, timeout):
        self.requests.append(req)
        if req.full_url.endswith('/models'):
            return Reply({'data': [{'id': MODEL}] if self.advertise else []})
        return Reply({'model': self.served, 'id': 'fixture-id', 'choices': [{'message': {'content': '{"summary":"fixture"}'}}], 'usage': {'completion_tokens': 4}})


class NebiusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.transport = FakeTransport()
        self.client = NebiusClient('fixture-secret', MODEL, True, self.tmp.name, self.transport)

    def test_actual_provider_contract_and_private_receipt(self):
        result = self.client.complete([{'role':'user','content':'fixture prompt'}], 10)
        self.assertEqual([r.full_url for r in self.transport.requests], [BASE_URL+'/models', BASE_URL+'/chat/completions'])
        body = json.loads(self.transport.requests[-1].data)
        self.assertEqual(body['model'], MODEL)
        self.assertEqual(body['max_tokens'], 10)
        receipt = Path(result['call_receipt'])
        raw = receipt.read_text()
        self.assertNotIn('fixture-secret', raw)
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(raw)['provider'], 'nebius-token-factory')
        self.assertEqual(result['served_model'], MODEL)

    def test_refuses_unadvertised_model_before_dispatch_and_retains_failure(self):
        self.transport.advertise = False
        with self.assertRaises(IntegrationError) as caught:
            self.client.complete([{'role':'user','content':'test'}])
        self.assertEqual(len(self.transport.requests), 1)
        receipt = json.loads(Path(caught.exception.call_receipt).read_text())
        self.assertFalse(receipt['dispatched'])
        self.assertEqual(receipt['status'], 'failed')
        with self.assertRaisesRegex(IntegrationError, 'stopped'):
            self.client.complete([{'role':'user','content':'test'}])

    def test_mismatched_response_and_disabled_inference_fail_closed(self):
        self.transport.served = 'nvidia/different'
        with self.assertRaises(IntegrationError) as caught:
            self.client.complete([{'role':'user','content':'test'}])
        self.assertTrue(json.loads(Path(caught.exception.call_receipt).read_text())['dispatched'])
        self.client.allow_inference = False
        self.client.stopped = False
        count = len(self.transport.requests)
        with self.assertRaises(IntegrationError): self.client.complete([{'role':'user','content':'test'}])
        self.assertEqual(len(self.transport.requests), count)

    def test_sample_status_needs_explicit_mode_and_authorization(self):
        with patch.dict('os.environ', {'SAMPLE_MODE':'true', 'INCIDENTCOURT_NEBIUS_SAMPLE':'1',
                       'NEBIUS_API_KEY':'fixture-secret', 'NEBIUS_MODEL':MODEL}, clear=True), \
             patch('incidentcourt.server.HMemStore') as memory:
            memory.return_value.status.return_value = {'state':'working'}
            self.assertFalse(server.status()['model']['inference_enabled'])
            with patch.dict('os.environ', {'NEBIUS_ALLOW_INFERENCE':'1'}):
                status = server.status()
                self.assertTrue(status['model']['inference_enabled'])
                self.assertEqual(status['model']['provider'], 'nebius')

    def test_offline_cli_forces_nebius_sample_off(self):
        import run
        with patch.dict('os.environ', {'INCIDENTCOURT_NEBIUS_SAMPLE':'1', 'NEBIUS_ALLOW_INFERENCE':'1'}), \
             patch('sys.argv', ['run.py', '--sample']), \
             patch('incidentcourt.sample.ensure_sample_db'), \
             patch('incidentcourt.server.main'):
            self.assertEqual(run.main(), 0)
            import os
            self.assertEqual(os.environ['INCIDENTCOURT_NEBIUS_SAMPLE'], '0')

    def test_job_gate_rejects_implicit_or_unauthorized_hosted_sample(self):
        workspace = Workspace(Path(self.tmp.name)/'workspace.sqlite3', {'id':'fixture','mode':'sample','label':'fixture'})
        manager = JobManager(workspace, threading.Lock())
        with patch.dict('os.environ', {'NEBIUS_API_KEY':'fixture-secret','NEBIUS_MODEL':MODEL,'NEBIUS_ALLOW_INFERENCE':'1'}, clear=True):
            with self.assertRaises(WorkspaceError): manager.start('IC-001','fixture-key-001','nebius')
        with patch.dict('os.environ', {'INCIDENTCOURT_NEBIUS_SAMPLE':'1', 'NEBIUS_API_KEY':'fixture-secret','NEBIUS_MODEL':MODEL}, clear=True):
            with self.assertRaises(WorkspaceError): manager.start('IC-001','fixture-key-002','nebius')

if __name__ == '__main__': unittest.main()
