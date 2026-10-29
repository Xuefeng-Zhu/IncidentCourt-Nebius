"""Local-only judge HTTP tests. No live provider or billable request."""
import http.client
import json
import os
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from http.server import ThreadingHTTPServer

from incidentcourt.judge_server import JudgeState, JudgeHandler, MODEL, Quota, read_credential, load_credentials, valid_access_code, run_limits
from incidentcourt.nebius import NebiusClient
from incidentcourt.sample import ensure_sample_db
from incidentcourt.config import ROOT

ENV = {'SAMPLE_MODE':'true', 'INCIDENTCOURT_NEBIUS_SAMPLE':'1', 'NEBIUS_MODEL':MODEL, 'NEBIUS_ALLOW_INFERENCE':'1'}
CODE = secrets.token_urlsafe(32)

class FakeReply:
    def __init__(self, value): self.body = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, maximum): return self.body

class FakeTransport:
    def __init__(self): self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        if request.full_url.endswith('/models'):
            return FakeReply({'data':[{'id':MODEL}]})
        message = json.loads(request.data)['messages'][1]['content']
        value = json.loads(message)
        if 'services' in value:
            body = {'service':value['services'][0], 'reason':'Fixture observation', 'evidence_ids':[value['evidence'][0]['id']]}
        else:
            body = {'summary':'Fixture explanation', 'evidence_ids':[value['evidence'][0]['id']]}
        return FakeReply({'model':MODEL, 'id':'PRIVATE_REQUEST', 'choices':[{'message':{'content':json.dumps(body)}}], 'usage':{'completion_tokens':10}})

class JudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_sample_db(ROOT/'data/sample.sqlite3')

    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=False); self.env.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), JudgeHandler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.clients = []
        self.receipt_directory = Path(self.tmp.name)/'persistent-receipts'
        self.receipt_directory.mkdir(mode=0o700)
        def client(*args, **kwargs):
            transport = FakeTransport(); self.clients.append(transport)
            kwargs['opener'] = transport
            return NebiusClient(*args, **kwargs)
        self.provider_patch = patch('incidentcourt.judge_server.NebiusClient', side_effect=client)
        self.provider_patch.start()
        Quota.initialize(Path(self.tmp.name)/'quota.sqlite3')
        self.state = JudgeState(self.origin, CODE, Path(self.tmp.name)/'quota.sqlite3', 2, 1, 5, 600, 20, 60,
                                provider_token='fixture-secret', provider_receipt_directory=self.receipt_directory)
        self.server.judge = self.state
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        for session in list(self.state.sessions.values()):
            for thread in list(session['manager'].threads.values()): thread.join(25)
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.state.close(); self.tmp.cleanup(); self.provider_patch.stop(); self.env.stop()

    def request(self, method, path, body=None, cookie=None, origin=True, host=None, form=False):
        headers = {'Host':host or self.state.host}
        if origin: headers['Origin'] = self.origin
        if cookie: headers['Cookie'] = cookie
        if body is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
            body = urlencode(body) if form else json.dumps(body)
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        conn.request(method, path, body, headers)
        reply = conn.getresponse(); data = reply.read(); cookie_header = reply.getheader('Set-Cookie'); status = reply.status; conn.close()
        return status, data, cookie_header

    def login(self):
        status, _, cookie = self.request('POST','/login',{'code':CODE},form=True)
        self.assertEqual(status, 303); self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Strict', cookie)
        return cookie.split(';')[0]

    def test_access_code_format_requires_canonical_32_byte_encoding(self):
        self.assertTrue(valid_access_code(CODE))
        for code in ('short-password', 'A'*32, 'A'*42+'!', 'A'*42+'B', None):
            self.assertFalse(valid_access_code(code))
        with self.assertRaisesRegex(ValueError, 'securely generated random bytes'):
            JudgeState(self.origin, 'easy-to-guess-password'*3, Path(self.tmp.name)/'unused.sqlite3', 2, 1, 5, 600, 20, 60)

    def test_run_limits_require_explicit_unlimited_opt_in(self):
        with self.assertRaises(ValueError): run_limits({})
        self.assertEqual(run_limits({'JUDGE_MAX_RUNS':'4','JUDGE_MAX_RUNS_PER_SESSION':'2'}), (4,2))
        self.assertEqual(run_limits({'JUDGE_RUN_LIMIT_MODE':'unlimited'}), (None,None))
        with self.assertRaises(ValueError): run_limits({'JUDGE_RUN_LIMIT_MODE':'unlimited','JUDGE_MAX_RUNS':'4'})
        with self.assertRaises(ValueError): run_limits({'JUDGE_RUN_LIMIT_MODE':'unrecognized'})

    def test_unlimited_reservations_remain_durable_and_fail_closed(self):
        self.state.quota.close()
        path = Path(self.tmp.name)/'quota.sqlite3'
        quota = Quota(path, None, None)
        for _ in range(6): self.assertTrue(quota.reserve('same-session'))
        quota.close()
        quota = Quota(path, None, None)
        self.assertTrue(quota.reserve('same-session'))
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            quota.reserve('same-session')
        quota.close()
        with self.assertRaises(ValueError): Quota(path, None, 1)

    def test_unlimited_mode_runs_multiple_investigations_and_retains_receipts(self):
        self.state.quota.close()
        self.state.quota = Quota(Path(self.tmp.name)/'quota.sqlite3', None, None)
        self.state.max_provider_receipts = None
        cookie = self.login()
        for index in range(3):
            status, body, _ = self.request('POST','/api/investigations',
                {'incident_id':'IC-001','idempotency_key':f'unlimited-test-key-{index:04d}'},cookie)
            self.assertEqual(status, 202, body)
            identity = json.loads(body)['id']
            for _ in range(300):
                _, body, _ = self.request('GET','/api/investigations/'+identity,cookie=cookie)
                result = json.loads(body)
                if result['state'] not in ('queued','running'): break
                time.sleep(.05)
            self.assertEqual(result['state'], 'completed', result)
        self.assertEqual(len(self.clients),3)
        self.assertEqual(len(list(self.receipt_directory.glob('*.json'))),9)

    def test_shared_proxy_bad_attempts_do_not_block_valid_judge(self):
        for _ in range(self.state.login_attempts + 5):
            self.assertEqual(self.request('POST','/login',{'code':'invalid'},form=True)[0],403)
        self.assertEqual(len(self.state.attempts['127.0.0.1']), self.state.login_attempts)
        cookie = self.login()
        self.assertEqual(self.request('GET','/api/cases',cookie=cookie)[0],200)
        self.assertEqual(self.clients, [])

    def test_concurrent_bad_attempts_do_not_block_valid_judge(self):
        results = []
        def invalid(): results.append(self.state.authenticate('127.0.0.1', 'incorrect'))
        threads = [threading.Thread(target=invalid) for _ in range(40)]
        for thread in threads: thread.start()
        token = self.state.authenticate('127.0.0.1', CODE)
        for thread in threads: thread.join()
        self.assertIsNotNone(token)
        self.assertEqual(results, [None]*40)
        self.assertLessEqual(len(self.state.attempts['127.0.0.1']), self.state.login_attempts)
        self.assertEqual(self.clients, [])

    def test_valid_code_cannot_exceed_session_capacity(self):
        for _ in range(self.state.max_sessions):
            self.assertIsNotNone(self.state.authenticate('127.0.0.1', CODE))
        self.assertIsNone(self.state.authenticate('127.0.0.1', CODE))
        self.assertEqual(len(self.state.sessions), self.state.max_sessions)
        self.assertEqual(self.clients, [])

    def test_restart_requires_fresh_login_preserves_quota_and_never_replays_run(self):
        cookie = self.login()
        status, body, _ = self.request('POST', '/api/investigations',
            {'incident_id':'IC-001', 'idempotency_key':'restart-fixture-key-0001'}, cookie)
        self.assertEqual(status, 202, body)
        identity = json.loads(body)['id']
        token = cookie.split('=', 1)[1]
        thread = self.state.sessions[token]['manager'].threads.get(identity)
        if thread: thread.join(25)
        status, body, _ = self.request('GET', '/api/investigations/' + identity, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['state'], 'completed')
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(len(self.clients[0].requests), 6)
        ledger = Path(self.tmp.name) / 'quota.sqlite3'
        with sqlite3.connect(ledger) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 1)

        self.state.close()
        self.state = JudgeState(self.origin, CODE, ledger, 2, 1, 5, 600, 20, 60,
                                provider_token='fixture-secret', provider_receipt_directory=self.receipt_directory)
        self.server.judge = self.state
        self.assertEqual(self.request('GET', '/api/investigations/' + identity, cookie=cookie)[0], 401)
        self.assertEqual(self.request('POST', '/api/investigations',
            {'incident_id':'IC-001', 'idempotency_key':'restart-fixture-key-0001'}, cookie)[0], 401)
        status, page, _ = self.request('GET', '/', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b'earlier results may no longer be available', page)
        self.assertIn(b'will not restart automatically', page)
        new_cookie = self.login()
        self.assertEqual(self.request('GET', '/api/investigations/' + identity, cookie=new_cookie)[0], 404)
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(len(self.clients[0].requests), 6)
        with sqlite3.connect(ledger) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 1)

    def test_isolation_origin_quota_and_fixture_provider(self):
        self.assertEqual(self.request('GET','/api/cases')[0], 401)
        self.assertEqual(self.request('GET','/',host='evil.example')[0], 403)
        self.assertEqual(self.request('POST','/login',{'code':CODE},origin=False,form=True)[0],403)
        a, b = self.login(), self.login()
        self.assertEqual(self.request('POST','/api/investigations/import',{},a)[0],403)
        self.assertEqual(self.request('POST','/api/connections/check',{},a)[0],403)
        self.assertEqual(self.request('POST','/api/investigations',{'incident_id':'IC-001','idempotency_key':'fixture-request-0001'},a,origin=False)[0],403)
        status, body, _ = self.request('POST','/api/investigations',{'incident_id':'IC-001','idempotency_key':'fixture-request-0001'},a)
        self.assertEqual(status, 202, body); identity = json.loads(body)['id']
        self.assertEqual(self.request('GET','/api/investigations/'+identity,cookie=b)[0],404)
        for _ in range(300):
            _, body, _ = self.request('GET','/api/investigations/'+identity,cookie=a)
            result = json.loads(body)
            if result['state'] not in ('queued','running'): break
            time.sleep(.1)
        self.assertEqual(result['state'], 'completed', result)
        self.assertEqual(len(self.clients[0].requests), 6)
        self.assertNotIn(b'provider-receipts', body); self.assertNotIn(b'PRIVATE_REQUEST', body); self.assertNotIn(b'fixture-secret', body)
        self.assertEqual(self.request('POST','/api/investigations',{'incident_id':'IC-001','idempotency_key':'fixture-request-0001'},a)[0],202)
        self.assertEqual(self.request('POST','/api/investigations',{'incident_id':'IC-001','idempotency_key':'fixture-request-0002'},a)[0],429)
        self.assertEqual(self.request('POST','/api/investigations/'+identity+'/review',{'note':'x'},a)[0],403)
        self.assertEqual(self.request('GET','/api/investigations',cookie=b)[1], b'{"investigations": []}')
        dirs = [s['directory'] for s in self.state.sessions.values()]
        self.assertEqual(len(set(dirs)),2)
        self.assertTrue((dirs[0]/'memory').exists())
        self.assertTrue((dirs[0]/'artifacts/runs').exists())
        receipts = list(self.receipt_directory.glob('*.json'))
        self.assertEqual(len(receipts), 3)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in receipts))
        self.assertTrue(all('fixture-secret' not in p.read_text() for p in receipts))
        self.assertFalse((dirs[1]/'provider-receipts').exists())
        self.assertFalse((dirs[1]/'artifacts').exists())
        token = a.split('=',1)[1]
        self.state.sessions[token]['expires'] = time.monotonic() - 1
        self.state.cleanup()
        self.assertFalse(dirs[0].exists())
        self.assertTrue(all(path.exists() for path in receipts))

    def test_systemd_credential_files_are_bounded_and_private_to_process(self):
        credential = Path(self.tmp.name)/'judge_access_code'
        credential.write_text('fixture-only-access-code\n')
        self.assertEqual(read_credential(self.tmp.name, 'judge_access_code'), 'fixture-only-access-code')
        credential.write_text('fixture\nunexpected')
        with self.assertRaises(ValueError): read_credential(self.tmp.name, 'judge_access_code')
        credential.write_text('x'*4097)
        with self.assertRaises(ValueError): read_credential(self.tmp.name, 'judge_access_code')
        with self.assertRaises(ValueError): read_credential(self.tmp.name, 'missing')

    def test_replaced_receipt_directory_fails_closed_without_provider_calls(self):
        cookie = self.login()
        old = Path(self.tmp.name)/'prior-receipts'
        self.receipt_directory.rename(old)
        self.receipt_directory.mkdir(mode=0o700)
        status, _, _ = self.request('POST','/api/investigations',
            {'incident_id':'IC-001','idempotency_key':'fixture-request-0001'},cookie)
        self.assertEqual(status, 503)
        self.assertTrue(all(not client.requests for client in self.clients))

    def test_environment_credentials_are_removed_before_child_processes(self):
        env = {'JUDGE_ACCESS_CODE':'fixture-code','NEBIUS_API_KEY':'fixture-token','OTHER':'kept'}
        self.assertEqual(load_credentials(env), ('fixture-code','fixture-token'))
        self.assertEqual(env, {'OTHER':'kept'})
        folder = Path(self.tmp.name)
        (folder/'judge_access_code').write_text('file-code')
        (folder/'nebius_api_key').write_text('file-token')
        env = {'CREDENTIALS_DIRECTORY':str(folder),'JUDGE_ACCESS_CODE':'unused','NEBIUS_API_KEY':'unused'}
        self.assertEqual(load_credentials(env), ('file-code','file-token'))
        self.assertEqual(env, {'CREDENTIALS_DIRECTORY':str(folder)})

    def test_concurrent_reservations_and_expired_session_cleanup(self):
        successes = []
        def reserve(index): successes.append(self.state.quota.reserve('caller-%s' % index))
        threads = [threading.Thread(target=reserve, args=(i,)) for i in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(successes), 2)
        cookie = self.login()
        token = cookie.split('=',1)[1]
        session = self.state.sessions[token]
        directory = session['directory']
        session['expires'] = time.monotonic() - 1
        self.state.cleanup()
        self.assertFalse(directory.exists())
        self.assertEqual(self.request('GET','/api/cases',cookie=cookie)[0],401)

    def test_ledger_restarts_and_requires_exclusive_ownership(self):
        self.assertTrue(self.state.quota.reserve('other'))
        with self.assertRaises(ValueError): Quota(Path(self.tmp.name)/'quota.sqlite3',2,1)
        self.state.quota.close()
        quota = Quota(Path(self.tmp.name)/'quota.sqlite3',2,1)
        self.assertFalse(quota.reserve('other'))
        self.assertTrue(quota.reserve('last'))
        self.assertFalse(quota.reserve('new'))
        ledger = Path(self.tmp.name, 'quota.sqlite3')
        ledger.unlink()
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            quota.reserve('another')
        quota.close()
        with self.assertRaisesRegex(ValueError, 'missing'):
            Quota(Path(self.tmp.name)/'quota.sqlite3',2,1)

if __name__ == '__main__': unittest.main()
