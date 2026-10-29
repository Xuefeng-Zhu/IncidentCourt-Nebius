"""Offline rendering and fail-closed startup tests, no platform resources."""
import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.prepare_container_sample import prepare

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('instacloud_start', ROOT/'deploy/instacloud/start.py')
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)
bootstrap_spec = importlib.util.spec_from_file_location('instacloud_bootstrap', ROOT/'deploy/instacloud/bootstrap.py')
bootstrap = importlib.util.module_from_spec(bootstrap_spec)
bootstrap_spec.loader.exec_module(bootstrap)
TEMPLATE = (ROOT/'deploy/instacloud/nginx.conf.template').read_text()

class InstaCloudPreparationTests(unittest.TestCase):
    def test_render_restricts_origin_port_and_rate_settings(self):
        env = {'JUDGE_ORIGIN':'https://judge.example.com','PORT':'8080','JUDGE_EDGE_RPS':'7','JUDGE_EDGE_BURST':'3'}
        value = startup.render(env, TEMPLATE, Path('/tmp/test-private-runtime'))
        self.assertIn('listen [::]:8080 ipv6only=off;', value)
        self.assertIn('proxy_set_header Host judge.example.com;', value)
        self.assertIn('proxy_set_header Host $http_host;', value)
        self.assertIn('rate=7r/s', value)
        self.assertNotIn('@', value)
        for invalid in ['http://judge.example.com', 'https://evil.example/x', 'https://bad..example',
                        'https://user@judge.example.com', 'https://judge.example.com:443', 'https://bad.example;inject']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                startup.render({**env, 'JUDGE_ORIGIN':invalid}, TEMPLATE, Path('/tmp/test-private-runtime'))
        for field, invalid in [('PORT','8317'), ('PORT','1234'), ('JUDGE_EDGE_RPS','0'), ('JUDGE_EDGE_BURST','5;')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                startup.render({**env,field:invalid},TEMPLATE, Path('/tmp/test-private-runtime'))

    def test_restart_uses_a_private_directory_without_deleting_other_instances(self):
        env = {'JUDGE_ORIGIN':'https://judge.example.com','PORT':'8080','JUDGE_EDGE_RPS':'7','JUDGE_EDGE_BURST':'3'}
        with tempfile.TemporaryDirectory() as parent:
            first, first_config = startup.create_runtime_config(env, TEMPLATE, parent)
            second, second_config = startup.create_runtime_config(env, TEMPLATE, parent)
            self.assertNotEqual(first, second)
            self.assertEqual(first.stat().st_mode & 0o777, 0o700)
            self.assertEqual(first_config.stat().st_mode & 0o777, 0o600)
            self.assertIn(str(first), first_config.read_text())
            self.assertIn(str(second), second_config.read_text())
            # A prior process may have crashed and left its directory behind.
            import shutil
            shutil.rmtree(second)
            self.assertTrue(first_config.exists())
            with self.assertRaises(ValueError):
                startup.create_runtime_config({**env, 'PORT':'9999'}, TEMPLATE, parent)
            self.assertEqual(list(Path(parent).iterdir()), [first])

    def test_proxy_environment_excludes_credentials_and_other_secrets(self):
        env = {'NEBIUS_API_KEY':'fixture-token','JUDGE_ACCESS_CODE':'fixture-code',
               'UNRELATED_SECRET':'fixture-private','TMPDIR':'/data','SAMPLE_MODE':'true'}
        backend, proxy = startup.child_environments(env)
        self.assertEqual(backend['TMPDIR'], '/tmp')
        self.assertNotIn('UNRELATED_SECRET', backend)
        self.assertNotIn('NEBIUS_API_KEY', proxy)
        self.assertNotIn('JUDGE_ACCESS_CODE', proxy)
        self.assertNotIn('UNRELATED_SECRET', proxy)

    def test_public_sample_is_readable_for_unprivileged_container_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            database = prepare(Path(directory)/'public-sample.sqlite3')
            self.assertEqual(database.stat().st_mode & 0o777, 0o444)
            connection = sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)
            try:
                self.assertGreater(connection.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 0)
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM incidents")
            finally:
                connection.close()

    def test_missing_mount_fails_before_starting_processes(self):
        with patch('os.path.ismount', return_value=False), patch('subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError, 'volume'):
                startup.main()
            process.assert_not_called()

    def test_missing_receipt_path_fails_before_starting_processes(self):
        with patch('os.path.ismount', return_value=True), patch.object(Path, 'is_file', return_value=True), \
             patch.dict(os.environ, {'JUDGE_QUOTA_LEDGER':'/data/incidentcourt/quota.sqlite3'}, clear=True), \
             patch('subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError, 'receipt'):
                startup.main()
            process.assert_not_called()

    def test_bootstrap_is_exclusive_private_and_non_serving(self):
        with tempfile.TemporaryDirectory() as volume, patch('os.path.ismount', return_value=True), \
             patch('os.geteuid', return_value=10001), patch.dict(os.environ, {}, clear=True), \
             patch('subprocess.Popen') as process:
            target = bootstrap.initialize_new_volume(volume)
            ledger = target/'quota.sqlite3'
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual((target/'provider-receipts').stat().st_mode & 0o777, 0o700)
            self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)
            connection = sqlite3.connect(ledger)
            try:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
            finally:
                connection.close()
            before = ledger.read_bytes()
            with self.assertRaises(FileExistsError):
                bootstrap.initialize_new_volume(volume)
            self.assertEqual(ledger.read_bytes(), before)
            process.assert_not_called()

    def test_bootstrap_refuses_missing_mount_root_or_credentials(self):
        with tempfile.TemporaryDirectory() as volume, patch.dict(os.environ, {}, clear=True):
            with patch('os.path.ismount', return_value=False):
                with self.assertRaises(ValueError): bootstrap.initialize_new_volume(volume)
            with patch('os.path.ismount', return_value=True), patch('os.geteuid', return_value=0):
                with self.assertRaises(ValueError): bootstrap.initialize_new_volume(volume)
            with patch('os.path.ismount', return_value=True), patch('os.geteuid', return_value=10001), \
                 patch.dict(os.environ, {'NEBIUS_API_KEY':'fixture-secret'}):
                with self.assertRaises(ValueError): bootstrap.initialize_new_volume(volume)
            self.assertEqual(list(Path(volume).iterdir()), [])

if __name__ == '__main__': unittest.main()
