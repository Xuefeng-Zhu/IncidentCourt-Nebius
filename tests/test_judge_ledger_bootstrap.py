"""Provider-free production-ledger bootstrap tests; no cloud calls."""
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from incidentcourt.quota import Quota
from deploy.instacloud import bootstrap, bootstrap_guard, bootstrap_health

ROOT = Path(__file__).resolve().parents[1]

class JudgeBootstrapTests(unittest.TestCase):
    def test_bootstrap_requires_same_uid_no_credentials_and_mounted_volume(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            with patch('os.path.ismount', return_value=False), self.assertRaises(ValueError):
                bootstrap.initialize_new_volume(folder)
            with patch('os.path.ismount', return_value=True), patch('os.geteuid', return_value=0), self.assertRaises(ValueError):
                bootstrap.initialize_new_volume(folder)
            with patch('os.path.ismount', return_value=True), patch('os.geteuid', return_value=10002), self.assertRaises(ValueError):
                bootstrap.initialize_new_volume(folder)
            with patch('os.path.ismount', return_value=True), patch('os.geteuid', return_value=10001), \
                 patch.dict(os.environ, {'NEBIUS_API_KEY':'fixture'}), self.assertRaises(ValueError):
                bootstrap.initialize_new_volume(folder)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_first_initialization_is_private_exclusive_and_durable(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), \
             patch('os.path.ismount', return_value=True), patch('os.geteuid', return_value=10001):
            target = bootstrap.initialize_new_volume(folder)
            ledger = target/'quota.sqlite3'; receipts = target/'provider-receipts'
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(receipts.stat().st_mode & 0o777, 0o700)
            self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(ledger) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],0)
            snapshot = ledger.read_bytes()
            with self.assertRaises(FileExistsError): bootstrap.initialize_new_volume(folder)
            self.assertEqual(ledger.read_bytes(), snapshot)

    def test_health_never_initializes_and_only_exposes_health(self):
        with patch('os.path.ismount', return_value=True), patch.object(Quota, 'initialize') as initialize:
            httpd = ThreadingHTTPServer(('127.0.0.1',0), bootstrap_health.Handler)
            thread = threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
            def request(method,path):
                conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=5)
                conn.request(method,path); response=conn.getresponse(); body=response.read(); status=response.status
                conn.close(); return status, body
            try:
                status,body=request('GET','/health')
                self.assertEqual((status,json.loads(body)['mode']),(200,'judge-ledger-bootstrap-only'))
                self.assertTrue(json.loads(body)['volume_mounted'])
                self.assertEqual(json.loads(body)['provider_calls'],0)
                self.assertEqual(request('GET','/')[0],404)
                self.assertEqual(request('GET','/fixture/status')[0],404)
                self.assertEqual(request('POST','/health')[0],501)
                initialize.assert_not_called()
            finally:
                httpd.shutdown(); httpd.server_close(); thread.join()

    def test_health_refuses_credentials_before_opening_listener(self):
        for name in ('NEBIUS_API_KEY','NEBIUS_MODEL','JUDGE_ACCESS_CODE'):
            with self.subTest(name=name), patch.dict(os.environ, {name:'','PORT':'8080','JUDGE_BOOTSTRAP_HEALTH':'1'}, clear=True), \
                 patch.object(bootstrap_health,'DualStackServer') as server:
                with self.assertRaises(ValueError): bootstrap_health.main()
                server.assert_not_called()

    def test_network_guard_blocks_outgoing_socket_calls(self):
        script = '''
import socket
from deploy.instacloud.bootstrap_guard import block_outbound
block_outbound()
for fn in (lambda: socket.create_connection(("example.invalid", 443)), lambda: socket.socket().connect(("127.0.0.1", 1))):
    try: fn()
    except OSError: pass
    else: raise SystemExit(1)
'''
        env={'PATH':os.environ.get('PATH',''),'PYTHONDONTWRITEBYTECODE':'1'}
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr.decode())

if __name__=='__main__': unittest.main()
