"""Hosted browser guard tests using fixture data only.

These tests do not contact Zetaris, Nightshift, or NVIDIA and cannot establish
anything about an account's billing or free-credit balance.
"""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from incidentcourt.hosted_guard import HostedNightshiftClient, HostedRunPolicy
from incidentcourt.integrations import IntegrationError, NightshiftClient
from incidentcourt import server
from incidentcourt.workspace import JobManager, Workspace, WorkspaceError
from tests.test_live_verification import provider_call

MODEL = 'nvidia/nemotron-3.5-lightning-30b-a3b'
ENV = {'NIGHTSHIFT_ALLOW_INFERENCE': '1', 'NIGHTSHIFT_HOSTED_ONLY': '1'}


def fixture_client(**changes):
    values = dict(configured=True, allow_inference=True, hosted_only=True,
                  enable_thinking=False, model=MODEL)
    values.update(changes)
    return SimpleNamespace(**values)


def fixture_policy():
    with patch.dict(os.environ, ENV, clear=True):
        return HostedRunPolicy.from_env(fixture_client())


class SyntheticAdapter:
    """Writes synthetic receipts in a temporary directory; never performs I/O to a provider."""
    def __init__(self, mutate=None, failure=None, mutate_result=None):
        self.count = 0
        self.mutate, self.failure, self.mutate_result = mutate, failure, mutate_result
        self.requests = []
        self.model = MODEL
        self.configured = self.allow_inference = self.hosted_only = True
        self.enable_thinking = False
        self.output_token_limit = None

    def complete(self, messages, max_tokens=1200):
        self.count += 1
        self.requests.append(max_tokens)
        if self.failure:
            raise IntegrationError('synthetic adapter failure')
        call = provider_call(self.count)
        call['request'].update(model=MODEL, max_tokens=max_tokens,
                               messages=deepcopy(messages),
                               chat_template_kwargs={'enable_thinking': self.enable_thinking})
        proof = call['response']
        proof['served_model'] = MODEL
        receipt = proof['runtime_receipt']
        receipt.update(requested_model=MODEL, routed_model=MODEL)
        receipt['winning_route']['model'] = MODEL
        receipt['privacy']['path'] = 'cloud-ok'
        if self.mutate:
            self.mutate(call, self.count)
        self.receipt_directory.mkdir(parents=True, exist_ok=True)
        path = self.receipt_directory / f'fixture-call-{self.count}.json'
        path.write_text(json.dumps(call))
        result = {**deepcopy(proof), 'provider': 'nightshift', 'requested_model': MODEL,
                  'call_id': call['call_id'], 'call_receipt': str(path),
                  'live_inference_verified': True}
        if self.mutate_result:
            self.mutate_result(result, self.count)
        return result


class HostedPolicyTests(unittest.TestCase):
    def test_hosted_opt_in_and_nvidia_model_are_required_without_a_one_run_permit(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(HostedRunPolicy.from_env(fixture_client()).approved_route, MODEL)
            for change in ({'configured': False}, {'allow_inference': False}, {'hosted_only': False},
                           {'model': 'webllm/local'}, {'model': 'meterless/auto'}, {'model': 'openai/model'}):
                with self.subTest(change=change), self.assertRaises((IntegrationError, ValueError)):
                    HostedRunPolicy.from_env(fixture_client(**change))

    def test_real_runtime_policy_needs_no_auxiliary_no_local_attestation(self):
        client = NightshiftClient(token='fixture-token', model=MODEL, allow_inference=True,
                                  hosted_only=True, enable_thinking=False)
        with patch.object(client, '_request') as request, patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(HostedRunPolicy.from_env(client).approved_route, MODEL)
            request.assert_not_called()


class HostedClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def client(self, adapter=None):
        adapter = adapter or SyntheticAdapter()
        return adapter, HostedNightshiftClient(adapter, fixture_policy(), 'a' * 20, output_root=self.root)

    def test_more_than_three_calls_and_full_requested_output_reach_adapter(self):
        adapter, guarded = self.client()
        for _ in range(5):
            result = guarded.complete([{'role': 'user', 'content': 'Fixture input.'}], max_tokens=1200)
            self.assertEqual(result['served_model'], MODEL)
        self.assertEqual(adapter.count, 5)
        self.assertEqual(adapter.requests, [1200] * 5)
        self.assertEqual(len(list(adapter.receipt_directory.glob('*.json'))), 5)

    def test_bad_or_missing_cost_stops_later_dispatch(self):
        for amount in (None, 0.01, True, '0'):
            with self.subTest(amount=amount), tempfile.TemporaryDirectory() as directory:
                adapter = SyntheticAdapter(lambda call, _: call['response']['runtime_receipt']['cost'].update(actual_usd=amount))
                guarded = HostedNightshiftClient(adapter, fixture_policy(), 'b' * 20, output_root=Path(directory))
                for _ in range(2):
                    with self.assertRaises((IntegrationError, ValueError)):
                        guarded.complete([{'role': 'user', 'content': 'Fixture input.'}])
                self.assertEqual(adapter.count, 1)
                self.assertEqual(len(list(adapter.receipt_directory.glob('*.json'))), 1)

    def test_returned_receipt_must_match_saved_receipt(self):
        adapter = SyntheticAdapter(mutate_result=lambda result, _:
                                   result['runtime_receipt']['cost'].update(actual_usd=0.01))
        adapter, guarded = self.client(adapter)
        with self.assertRaises(IntegrationError):
            guarded.complete([{'role': 'user', 'content': 'Fixture input.'}])
        self.assertEqual(adapter.count, 1)

    def test_attempt_is_recorded_before_adapter_dispatch(self):
        class JournalCheckingAdapter(SyntheticAdapter):
            def complete(self, messages, max_tokens=1200):
                journal = json.loads((self.receipt_directory.parent / 'journal.json').read_text())
                if journal['gateway_generation_attempts'] != self.count + 1:
                    raise AssertionError('Attempt was not journaled before provider dispatch')
                return super().complete(messages, max_tokens=max_tokens)
        adapter, guarded = self.client(JournalCheckingAdapter())
        for _ in range(5):
            guarded.complete([{'role': 'user', 'content': 'Fixture input.'}])
        self.assertEqual(adapter.count, 5)

    def test_cached_wrong_route_and_missing_proof_are_sticky_failures(self):
        mutations = [
            lambda c, _: c['response']['runtime_receipt'].update(from_cache=True),
            lambda c, _: c['response']['runtime_receipt']['winning_route'].update(provider='webllm'),
            lambda c, _: c['response'].update(served_model='nvidia/another-model'),
            lambda c, _: c['response']['runtime_receipt'].pop('schema'),
            lambda c, _: c['response']['runtime_receipt'].pop('privacy'),
            lambda c, _: c['response']['runtime_receipt']['privacy'].update(path='local-only'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                adapter = SyntheticAdapter(mutate)
                guarded = HostedNightshiftClient(adapter, fixture_policy(), 'c' * 20, output_root=Path(directory))
                for _ in range(2):
                    with self.assertRaises((IntegrationError, ValueError)):
                        guarded.complete([{'role': 'user', 'content': 'Fixture input.'}])
                self.assertEqual(adapter.count, 1)

    def test_ambiguous_adapter_exception_is_not_retried(self):
        adapter, guarded = self.client(SyntheticAdapter(failure=True))
        for _ in range(2):
            with self.assertRaises((IntegrationError, ValueError)):
                guarded.complete([{'role': 'user', 'content': 'Fixture input.'}])
        self.assertEqual(adapter.count, 1)

    def test_changed_configuration_stops_dispatch(self):
        adapter, guarded = self.client()
        guarded.complete([{'role': 'user', 'content': 'First fixture call.'}])
        adapter.model = 'webllm/local'
        with self.assertRaises(IntegrationError):
            guarded.complete([{'role': 'user', 'content': 'Must not dispatch.'}])
        self.assertEqual(adapter.count, 1)

    def test_reused_receipt_cannot_be_accepted_as_a_new_response(self):
        def duplicate(call, number):
            if number > 1:
                call['response']['runtime_receipt']['receipt_id'] = 'fixture-receipt-1'
        adapter, guarded = self.client(SyntheticAdapter(duplicate))
        guarded.complete([{'role': 'user', 'content': 'First fixture call.'}])
        with self.assertRaises(IntegrationError):
            guarded.complete([{'role': 'user', 'content': 'Second fixture call.'}])
        with self.assertRaises(IntegrationError):
            guarded.complete([{'role': 'user', 'content': 'Must not dispatch.'}])
        self.assertEqual(adapter.count, 2)

    def test_lower_adapter_token_limit_is_valid_but_overrun_is_rejected(self):
        class LowerCapAdapter(SyntheticAdapter):
            def complete(self, messages, max_tokens=1200):
                return super().complete(messages, max_tokens=min(max_tokens, 200))
        adapter, guarded = self.client(LowerCapAdapter())
        guarded.complete([{'role': 'user', 'content': 'Fixture input.'}], max_tokens=1200)
        saved = json.loads(next(adapter.receipt_directory.glob('*.json')).read_text())
        self.assertEqual(saved['request']['max_tokens'], 200)
        with tempfile.TemporaryDirectory() as directory:
            class OverrunAdapter(SyntheticAdapter):
                def complete(self, messages, max_tokens=1200):
                    return super().complete(messages, max_tokens=max_tokens + 1)
            overrun = OverrunAdapter()
            blocked = HostedNightshiftClient(overrun, fixture_policy(), 'd' * 20, output_root=Path(directory))
            with self.assertRaises(IntegrationError):
                blocked.complete([{'role': 'user', 'content': 'Fixture input.'}], max_tokens=1200)
            with self.assertRaises(IntegrationError):
                blocked.complete([{'role': 'user', 'content': 'Must not dispatch.'}])
            self.assertEqual(overrun.count, 1)


class WorkspaceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = Workspace(self.root / 'workspace.sqlite3',
                                   {'id': 'zetaris-fixture', 'mode': 'zetaris', 'label': 'Fixture'})
        self.workspace.cache_cases([{'id': 'IC-003', 'title': 'Fixture'},
                                    {'id': 'IC-001', 'title': 'Other fixture'}])

    def test_no_attestation_is_needed_for_pinned_hosted_job_reservation(self):
        client = NightshiftClient(token='fixture-token', model=MODEL, allow_inference=True,
                                  hosted_only=True, enable_thinking=False)
        runner = Mock()
        lock = threading.Lock()
        manager = JobManager(self.workspace, lock, runner=runner)
        with patch.dict(os.environ, ENV, clear=True), patch.object(NightshiftClient, 'from_env', return_value=client), \
             patch.object(client, '_request') as request, patch('incidentcourt.hosted_guard.PROJECT_ROOT', self.root), \
             patch('incidentcourt.workspace.threading.Thread.start') as start:
            identity = manager.start('IC-003', 'fixture-unattested-0001', 'nightshift')
            start.assert_called_once()
            request.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(self.workspace.investigation(identity)['state'], 'queued')
        lock.release()

    def test_repeated_runs_and_distinct_incidents_have_no_single_use_permit(self):
        first = self.workspace.reserve('IC-003', 'fixture-key-initial-01')
        self.workspace.failed(first)
        reopened = Workspace(self.root / 'workspace.sqlite3', self.workspace.context)
        second = reopened.reserve('IC-001', 'fixture-key-second-01')
        third = reopened.reserve('IC-003', 'fixture-key-third-001')
        self.assertEqual({x['id'] for x in reopened.investigations()}, {first, second, third})

    def test_setup_failure_marks_failed_and_releases_execution_lock(self):
        failures = [('guard construction', 'incidentcourt.hosted_guard.HostedNightshiftClient', OSError('fixture failure')),
                    ('thread start', 'incidentcourt.workspace.threading.Thread.start', RuntimeError('fixture failure'))]
        for label, target, failure in failures:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace = Workspace(root / 'workspace.sqlite3', self.workspace.context)
                workspace.cache_cases([{'id': 'IC-003', 'title': 'Fixture case'}])
                lock, runner, adapter = threading.Lock(), Mock(), SyntheticAdapter()
                manager = JobManager(workspace, lock, runner=runner)
                with patch.dict(os.environ, ENV, clear=True), \
                     patch('incidentcourt.integrations.NightshiftClient.from_env', return_value=adapter), \
                     patch('incidentcourt.hosted_guard.PROJECT_ROOT', root), patch(target, side_effect=failure):
                    with self.assertRaises((OSError, RuntimeError)):
                        manager.start('IC-003', 'fixture-setup-failure-01', 'nightshift')
                self.assertEqual([entry['state'] for entry in workspace.investigations()], ['failed'])
                self.assertIsNone(manager.active_id)
                self.assertEqual(manager.threads, {})
                self.assertFalse(lock.locked())
                runner.assert_not_called()
                self.assertEqual(adapter.count, 0)


class LegacyRouteTests(unittest.TestCase):
    def test_legacy_hosted_routes_cannot_bypass_hosted_only_guard(self):
        for path in ('/run', '/api/investigate'):
            with self.subTest(path=path), patch.object(server, 'investigate') as investigate:
                handler = object.__new__(server.Handler)
                body = json.dumps({'incident_id': 'IC-003', 'model': 'nightshift'}).encode()
                handler.server = SimpleNamespace(server_port=8317)
                handler.headers = {'Host': '127.0.0.1:8317', 'Content-Type': 'application/json',
                                   'Content-Length': str(len(body))}
                handler.rfile, handler.path, handler.reply = BytesIO(body), path, Mock()
                with patch.dict(os.environ, ENV, clear=True):
                    handler.do_POST()
                investigate.assert_not_called()
                self.assertGreaterEqual(handler.reply.call_args.args[1], 400)


class HostedStatusTests(unittest.TestCase):
    def test_status_offers_pinned_hosted_route_without_auxiliary_attestation(self):
        client = NightshiftClient(token='fixture-token', model=MODEL, allow_inference=True,
                                  hosted_only=True, enable_thinking=False)
        env = {**ENV, 'INCIDENTCOURT_DATA_MODE': 'zetaris', 'SAMPLE_MODE': 'false'}
        with patch.dict(os.environ, env, clear=True), patch.object(NightshiftClient, 'from_env', return_value=client), \
             patch.object(client, '_request') as request, patch.object(server, 'HMemStore') as memory:
            memory.return_value.status.return_value = {'state': 'working'}
            result = server.status()
            request.assert_not_called()
        self.assertTrue(result['model']['inference_enabled'])
        self.assertFalse(result['model']['auxiliary_models_verified'])
        self.assertIn('auxiliary', result['model']['detail'].lower())
        self.assertFalse(result['integration_ready'])

    def test_hosted_status_does_not_require_incident_or_nonce(self):
        env = {**ENV, 'INCIDENTCOURT_DATA_MODE': 'zetaris', 'SAMPLE_MODE': 'false'}
        client = fixture_client()
        client.status = Mock(return_value={'state': 'configured_unverified', 'requested_model': MODEL,
                                           'inference_enabled': True, 'hosted_only': True})
        with patch.dict(os.environ, env, clear=True), patch.object(NightshiftClient, 'from_env', return_value=client), \
             patch.object(server, 'HMemStore') as memory:
            memory.return_value.status.return_value = {'state': 'working'}
            self.assertTrue(server.status()['model']['inference_enabled'])


class WorkspaceRunButtonTests(unittest.TestCase):
    def test_workspace_ui_no_longer_restricts_runs_to_an_incident(self):
        script = r"""
const assert = require('node:assert/strict');
const {canStartWorkspaceInvestigation: canStart} = require('./incidentcourt/static/app.js');
const ready = {model: {inference_enabled: true, hosted_only: true}};
assert.equal(canStart(null, 'sample'), true);
assert.equal(canStart({}, 'sample'), true);
assert.equal(canStart(null, 'zetaris'), false);
assert.equal(canStart({}, 'zetaris'), false);
assert.equal(canStart(ready, 'zetaris', 'IC-003'), true);
assert.equal(canStart(ready, 'zetaris', 'IC-001'), true);
assert.equal(canStart(ready, 'zetaris'), true);
assert.equal(canStart(ready, 'local'), false);
assert.equal(canStart(ready, undefined), false);
assert.equal(canStart({model: {...ready.model, inference_enabled: false}}, 'zetaris'), false);
assert.equal(canStart({model: {...ready.model, hosted_only: false}}, 'zetaris'), false);
"""
        result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
