"""Contract tests use a fake HTTP transport and do not establish live Nebius usage."""
import json
import os
import subprocess
import sys
import tempfile
import time
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

    def test_durable_receipt_is_written_before_dispatch_and_survives_interruption(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        class InterruptedTransport(FakeTransport):
            def open(transport, request, timeout):
                if request.full_url.endswith('/models'):
                    return super().open(request, timeout)
                files = list(directory.glob('*.json'))
                self.assertEqual(len(files), 1)
                pending = json.loads(files[0].read_text())
                self.assertEqual(pending['status'], 'unknown')
                self.assertTrue(pending['dispatched'])
                self.assertNotIn('fixture-secret', files[0].read_text())
                raise SystemExit('simulated process interruption')
        client = NebiusClient('fixture-secret', MODEL, True, directory, InterruptedTransport(),
                              durable_receipts=True, max_receipts=3)
        with self.assertRaises(SystemExit):
            client.complete([{'role':'user','content':'fixture-secret'}], 10)
        receipt = next(directory.glob('*.json'))
        self.assertEqual(json.loads(receipt.read_text())['status'], 'unknown')
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_durable_success_and_failure_are_retained_and_capped(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        client = NebiusClient('fixture-secret', MODEL, True, directory, FakeTransport(),
                              durable_receipts=True, max_receipts=1)
        result = client.complete([{'role':'user','content':'fixture-secret'}], 10)
        receipt = Path(result['call_receipt'])
        self.assertEqual(json.loads(receipt.read_text())['status'], 'completed')
        self.assertNotIn('fixture-secret', receipt.read_text())
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        transport = FakeTransport()
        second = NebiusClient('fixture-secret', MODEL, True, directory, transport,
                              durable_receipts=True, max_receipts=1)
        with self.assertRaises(IntegrationError):
            second.complete([{'role':'user','content':'another'}], 10)
        self.assertEqual(len(transport.requests), 1)  # model discovery only; no dispatch
        self.assertEqual(len(list(directory.glob('*.json'))), 1)

    def test_explicit_no_fixed_receipt_count_retains_records_and_fails_closed_on_full_disk(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            NebiusClient('fixture-secret', MODEL, True, directory, FakeTransport(), durable_receipts=True)
        for _ in range(4):
            client = NebiusClient('fixture-secret', MODEL, True, directory, FakeTransport(),
                                  durable_receipts=True, unlimited_receipts=True)
            client.complete([{'role':'user','content':'fixture'}], 10)
        self.assertEqual(len(list(directory.glob('*.json'))), 4)
        transport = FakeTransport()
        client = NebiusClient('fixture-secret', MODEL, True, directory, transport,
                              durable_receipts=True, unlimited_receipts=True)
        with patch('incidentcourt.nebius.os.open', side_effect=OSError('simulated full disk')):
            with self.assertRaises(IntegrationError):
                client.complete([{'role':'user','content':'fixture'}], 10)
        self.assertEqual(len(transport.requests), 1)  # metadata discovery, no completion dispatch
        self.assertEqual(len(list(directory.glob('*.json'))), 4)

    def test_killed_process_leaves_a_durable_unknown_record(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        marker = Path(self.tmp.name)/'dispatch-entered'
        script = '''
import json, sys, time
from pathlib import Path
from incidentcourt.nebius import NebiusClient
model = "nvidia/nemotron-3-super-120b-a12b"
class Reply:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return json.dumps({"data":[{"id":model}]}).encode()
class Transport:
    def open(self, request, timeout):
        if request.full_url.endswith("/models"): return Reply()
        Path(sys.argv[2]).write_text("entered")
        time.sleep(60)
NebiusClient("fixture-secret", model, True, sys.argv[1], Transport(), durable_receipts=True, max_receipts=1).complete([{"role":"user","content":"fixture"}], 10)
'''
        env = {'PATH':os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE':'1'}
        process = subprocess.Popen([sys.executable, '-c', script, str(directory), str(marker)],
                                   cwd=Path(__file__).resolve().parents[1], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(marker.exists(), 'fake provider was not reached')
            process.kill()
            process.wait(timeout=5)
            receipt = json.loads(next(directory.glob('*.json')).read_text())
            self.assertEqual(receipt['status'], 'unknown')
            self.assertTrue(receipt['dispatched'])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_durable_receipt_failure_prevents_dispatch(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        transport = FakeTransport()
        client = NebiusClient('fixture-secret', MODEL, True, directory, transport,
                              durable_receipts=True, max_receipts=3)
        with patch.object(client, '_durable_save', side_effect=IntegrationError('fixture disk failure')):
            with self.assertRaises(IntegrationError):
                client.complete([{'role':'user','content':'test'}], 10)
        self.assertEqual(len(transport.requests), 1)

    def test_durable_timeout_remains_unknown(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        class TimedOutTransport(FakeTransport):
            def open(self, request, timeout):
                if request.full_url.endswith('/models'):
                    return super().open(request, timeout)
                raise TimeoutError()
        client = NebiusClient('fixture-secret', MODEL, True, directory, TimedOutTransport(),
                              durable_receipts=True, max_receipts=3)
        with self.assertRaises(IntegrationError):
            client.complete([{'role':'user','content':'test'}], 10)
        receipt = json.loads(next(directory.glob('*.json')).read_text())
        self.assertEqual(receipt['status'], 'unknown')
        self.assertTrue(receipt['dispatched'])

    def test_failed_receipt_update_preserves_unknown_record(self):
        directory = Path(self.tmp.name)/'persistent-receipts'
        directory.mkdir(mode=0o700)
        client = NebiusClient('fixture-secret', MODEL, True, directory, FakeTransport(),
                              durable_receipts=True, max_receipts=3)
        original = client._durable_save
        def save(call_id, call, *, initial):
            if not initial:
                raise IntegrationError('fixture update failure')
            return original(call_id, call, initial=initial)
        with patch.object(client, '_durable_save', side_effect=save):
            with self.assertRaises(IntegrationError):
                client.complete([{'role':'user','content':'test'}], 10)
        receipt = json.loads(next(directory.glob('*.json')).read_text())
        self.assertEqual(receipt['status'], 'unknown')

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
