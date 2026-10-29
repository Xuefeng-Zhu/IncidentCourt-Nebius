"""Conditional InstaCloud container runner. No secrets are printed."""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def render(env, template, runtime_directory):
    origin = env.get('JUDGE_ORIGIN', '')
    parsed = urlparse(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or
        parsed.port or parsed.path or parsed.params or parsed.query or parsed.fragment or
        parsed.netloc != parsed.hostname or '.' not in parsed.hostname or
        any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in parsed.hostname.split('.'))):
        raise ValueError('JUDGE_ORIGIN must be a lowercase HTTPS hostname without a port or path')
    def integer(name, maximum):
        value = env.get(name, '')
        if not value.isdigit() or not 1 <= int(value) <= maximum:
            raise ValueError(name + ' must be explicitly configured')
        return value
    port = integer('PORT', 65535)
    if int(port) != 8080:
        raise ValueError('PORT must match the planned compute target 8080')
    values = {'@PORT@':port, '@JUDGE_HOST@':parsed.netloc,
              '@EDGE_RPS@':integer('JUDGE_EDGE_RPS', 100000),
              '@EDGE_BURST@':integer('JUDGE_EDGE_BURST', 100000),
              '@RUNTIME_DIR@':str(runtime_directory)}
    for key, value in values.items(): template = template.replace(key, value)
    if re.search(r'@[A-Z_]+@', template): raise ValueError('Unresolved nginx template')
    return template


def child_environments(env):
    allowed = ('PATH','LANG','PYTHONDONTWRITEBYTECODE','PYTHONUNBUFFERED',
        'SAMPLE_MODE','INCIDENTCOURT_NEBIUS_SAMPLE','NEBIUS_MODEL','NEBIUS_ALLOW_INFERENCE',
        'NEBIUS_API_KEY','JUDGE_ACCESS_CODE','JUDGE_ORIGIN','JUDGE_QUOTA_LEDGER','JUDGE_RECEIPT_DIR',
        'JUDGE_ACCESS_MODE','JUDGE_RUN_LIMIT_MODE','JUDGE_MAX_RUNS','JUDGE_MAX_RUNS_PER_SESSION','JUDGE_MAX_SESSIONS',
        'JUDGE_SESSION_SECONDS','JUDGE_LOGIN_ATTEMPTS','JUDGE_LOGIN_WINDOW_SECONDS')
    backend = {k:env[k] for k in allowed if k in env}
    backend['TMPDIR'] = '/tmp'
    return backend, {'PATH':'/usr/sbin:/usr/bin:/bin','LANG':'C.UTF-8'}


def create_runtime_config(env, template, parent='/tmp'):
    runtime = Path(tempfile.mkdtemp(prefix='incidentcourt-nginx-', dir=parent))
    try:
        config = render(env, template, runtime)
        path = runtime/'nginx.conf'
        fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write(config)
        return runtime, path
    except BaseException:
        shutil.rmtree(runtime, ignore_errors=True)
        raise


def main():
    # The persistent InstaCloud volume must be mounted at runtime. Refuse ephemeral fallback.
    volume = Path('/data')
    if not os.path.ismount(volume) or os.environ.get('JUDGE_QUOTA_LEDGER') != str(volume/'incidentcourt/quota.sqlite3'):
        raise ValueError('The expected persistent volume is missing or the ledger path is wrong')
    if not (volume/'incidentcourt/quota.sqlite3').is_file():
        raise ValueError('Quota ledger missing; never silently initialize or reset it')
    receipts = volume/'incidentcourt/provider-receipts'
    if (os.environ.get('JUDGE_RECEIPT_DIR') != str(receipts) or
        receipts.is_symlink() or receipts.parent.is_symlink() or not receipts.is_dir()):
        raise ValueError('The expected private durable receipt directory is required')
    template = (ROOT/'deploy/instacloud/nginx.conf.template').read_text()
    runtime, config_path = create_runtime_config(os.environ, template)
    backend = proxy = None
    try:
        # Restrict both child environments; the proxy receives no service secrets.
        backend_env, proxy_env = child_environments(os.environ)
        backend = subprocess.Popen([sys.executable, '-m', 'incidentcourt.judge_server', '--port', '8317'], cwd=ROOT, env=backend_env)
        def stop(*_):
            for child in (proxy, backend):
                if child and child.poll() is None: child.terminate()
        signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
        proxy = subprocess.Popen(['/usr/sbin/nginx', '-c', str(config_path), '-g', 'daemon off;'], env=proxy_env)
        while proxy.poll() is None and backend.poll() is None: time.sleep(.25)
        return 1
    finally:
        for child in (proxy, backend):
            if child and child.poll() is None: child.terminate()
        for child in (proxy, backend):
            if child:
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
        # Never touch another process's runtime directory. A hard crash may
        # leave this one behind until the platform cleans the ephemeral disk.
        shutil.rmtree(runtime, ignore_errors=True)


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError):
        print('InstaCloud judge startup failed; check non-secret configuration and persistent volume.', file=sys.stderr)
        raise SystemExit(1)
