"""Locally prepared judge gateway. This is not a production-ready deployment."""
import argparse
import base64
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from http import cookies
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .server import Handler
from .workspace import Workspace, WorkspaceError, JobManager, source_context
from .store import Store
from .integrations import HMemStore
from .investigate import investigate
from .nebius import NebiusClient
from .quota import Quota

MODEL = 'nvidia/nemotron-3-super-120b-a12b'


def valid_access_code(code):
    """Accept the canonical URL-safe encoding of 32 bytes, not a password.

    Format checking cannot prove randomness: operators must generate the bytes
    with a cryptographically secure random generator and keep the code private.
    """
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code):
        return False
    try:
        raw = base64.urlsafe_b64decode(code + '=')
        return len(raw) == 32 and base64.urlsafe_b64encode(raw).decode().rstrip('=') == code
    except (ValueError, TypeError):
        return False


def positive(name):
    value = os.environ.get(name, '')
    if not value.isdigit() or not 0 < int(value) <= 1_000_000:
        raise ValueError(f'{name} must be an explicitly configured positive integer')
    return int(value)


def run_limits(env):
    """Require an explicit opt-in to omit both fixed run-count limits."""
    mode = env.get('JUDGE_RUN_LIMIT_MODE', 'bounded')
    if mode == 'unlimited':
        if env.get('JUDGE_MAX_RUNS') or env.get('JUDGE_MAX_RUNS_PER_SESSION'):
            raise ValueError('Do not combine unlimited mode with fixed run-count limits')
        return None, None
    if mode != 'bounded':
        raise ValueError('Unknown run limit mode')
    def read(name):
        value = env.get(name, '')
        if not value.isdigit() or not 0 < int(value) <= 1_000_000:
            raise ValueError(f'{name} must be an explicitly configured positive integer')
        return int(value)
    return read('JUDGE_MAX_RUNS'), read('JUDGE_MAX_RUNS_PER_SESSION')


def read_credential(directory, name):
    # systemd LoadCredential files are readable only by the service account and root.
    try:
        with (Path(directory) / name).open('rb') as credential:
            raw = credential.read(4097)
        if not 0 < len(raw) <= 4096:
            raise ValueError()
        value = raw.decode('utf-8').rstrip('\r\n')
        if not value or any(ch in value for ch in ('\r', '\n', '\x00')):
            raise ValueError()
        return value
    except (OSError, UnicodeError, ValueError):
        raise ValueError('A required service credential is missing or invalid') from None


def access_mode(env):
    mode = env.get('JUDGE_ACCESS_MODE', 'code')
    if mode not in ('code', 'public'):
        raise ValueError('Invalid judge access mode')
    return mode


def load_credentials(env, mode='code'):
    directory = env.get('CREDENTIALS_DIRECTORY')
    code = env.pop('JUDGE_ACCESS_CODE', None)
    token = env.pop('NEBIUS_API_KEY', None)
    if mode not in ('code', 'public'):
        raise ValueError('Invalid judge access mode')
    if directory:
        return (read_credential(directory, 'judge_access_code') if mode == 'code' else None,
                read_credential(directory, 'nebius_api_key'))
    if mode == 'code' and not code:
        raise ValueError('A judge access credential is required')
    return (code if mode == 'code' else None), token or ''


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in ('call_receipt', 'provider_request_id')}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


class GuardedClient:
    def __init__(self, client):
        self.client = client
        self.configured, self.allow_inference = client.configured, client.allow_inference
        self.calls = 0

    def complete(self, messages, max_tokens=1200):
        limits = (600, 600, 1200)
        if self.calls >= len(limits) or max_tokens != limits[self.calls]:
            raise ValueError('Judge provider call limit exceeded')
        self.calls += 1
        return self.client.complete(messages, max_tokens)


class JudgeState:
    def __init__(self, origin, code, ledger, maximum, per_session, max_sessions, lifetime, login_attempts, login_window, client_factory=None, runner=None, provider_token=None, provider_receipt_directory=None, access_mode='code'):
        parsed = urlparse(origin)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.params or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost'))):
            raise ValueError('Origin must be HTTPS, or HTTP on localhost for testing')
        if access_mode not in ('code', 'public'):
            raise ValueError('Invalid judge access mode')
        if access_mode == 'code' and not valid_access_code(code):
            raise ValueError('Judge access code must be a URL-safe encoding of 32 securely generated random bytes')
        if os.environ.get('SAMPLE_MODE') != 'true' or os.environ.get('INCIDENTCOURT_NEBIUS_SAMPLE') != '1':
            raise ValueError('Judge mode requires explicitly enabled sample telemetry and Nebius mode')
        if os.environ.get('NEBIUS_MODEL') != MODEL or os.environ.get('NEBIUS_ALLOW_INFERENCE') != '1':
            raise ValueError('Judge mode requires the pinned model and explicit inference enablement')
        token = provider_token if provider_token is not None else os.environ.get('NEBIUS_API_KEY', '')
        if not client_factory and not token:
            raise ValueError('A server-side Nebius key is required')
        if not client_factory and (not provider_receipt_directory or not Path(provider_receipt_directory).is_absolute()):
            raise ValueError('A private durable provider receipt directory is required')
        if not client_factory and (Path(provider_receipt_directory).is_symlink() or not Path(provider_receipt_directory).is_dir()):
            raise ValueError('The private durable provider receipt directory must already exist')
        self.provider_token = token
        self.provider_receipt_directory = Path(provider_receipt_directory) if provider_receipt_directory else None
        self.provider_receipt_identity = None
        if self.provider_receipt_directory:
            receipt_stat = self.provider_receipt_directory.stat()
            self.provider_receipt_identity = (receipt_stat.st_dev, receipt_stat.st_ino)
        self.max_provider_receipts = 3 * maximum if maximum is not None else None
        self.origin, self.host, self.secure = origin, parsed.netloc, parsed.scheme == 'https'
        self.code, self.access_mode = code, access_mode
        self.quota = Quota(ledger, maximum, per_session)
        self.max_sessions, self.lifetime = max_sessions, lifetime
        self.login_attempts, self.login_window = login_attempts, login_window
        self.client_factory = client_factory
        self.runner = runner
        self.root = Path(tempfile.mkdtemp(prefix='incidentcourt-judge-'))
        os.chmod(self.root, 0o700)
        self.lock, self.run_lock = threading.RLock(), threading.Lock()
        self.sessions, self.attempts = {}, {}
        self.stop_cleanup = threading.Event()
        self.janitor = threading.Thread(target=self._clean_loop, daemon=True)
        self.janitor.start()

    def _clean_loop(self):
        while not self.stop_cleanup.wait(min(30, self.lifetime)):
            self.cleanup()

    def cleanup(self):
        with self.lock:
            now = time.monotonic()
            for token, session in list(self.sessions.items()):
                if session['expires'] <= now and not session['manager'].active_id:
                    shutil.rmtree(session['directory'], ignore_errors=True)
                    del self.sessions[token]
            for address, attempts in list(self.attempts.items()):
                attempts[:] = [t for t in attempts if t > now - self.login_window]
                if not attempts:
                    del self.attempts[address]

    def authenticate(self, address, supplied):
        with self.lock:
            self.cleanup()
            if self.access_mode != 'code':
                return None
            # A proxy can make all visitors share one address. Compare before
            # consulting the bucket so invalid traffic cannot lock out a judge
            # holding the correct high-entropy code. The bucket does not bound
            # code guesses; trusted ingress is needed for per-client throttling.
            valid = isinstance(supplied, str) and hmac.compare_digest(supplied.encode(), self.code.encode())
            if valid:
                if len(self.sessions) >= self.max_sessions:
                    return None
            else:
                attempts = self.attempts.setdefault(address, [])
                if len(attempts) < self.login_attempts:
                    attempts.append(time.monotonic())
                return None
            return self._new_session()

    def open_public_session(self):
        with self.lock:
            self.cleanup()
            if self.access_mode != 'public' or len(self.sessions) >= self.max_sessions:
                return None
            return self._new_session()

    def _new_session(self):
        token = secrets.token_urlsafe(32)
        directory = self.root / secrets.token_hex(16)
        directory.mkdir(mode=0o700)
        try:
            workspace = Workspace(directory / 'workspace.sqlite3', source_context())
            workspace.cache_cases(Store().incidents())
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        def run(iid, **kwargs):
            kwargs['memory'] = HMemStore(directory / 'memory')
            kwargs['output_root'] = directory
            return (self.runner or investigate)(iid, **kwargs)
        def client():
            if self.client_factory:
                return GuardedClient(self.client_factory(directory))
            return GuardedClient(NebiusClient(self.provider_token, MODEL, True, self.provider_receipt_directory,
                                              durable_receipts=True, max_receipts=self.max_provider_receipts,
                                              expected_receipt_identity=self.provider_receipt_identity,
                                              unlimited_receipts=self.max_provider_receipts is None))
        manager = JobManager(workspace, self.run_lock, runner=run, client_factory=client)
        self.sessions[token] = {'workspace': workspace, 'manager': manager, 'directory': directory,
                                'expires': time.monotonic() + self.lifetime}
        return token

    def session(self, token):
        with self.lock:
            self.cleanup()
            session = self.sessions.get(token)
            return session if session and session['expires'] > time.monotonic() else None

    def start(self, token, session, incident, key):
        with self.lock:
            # Validate before reserving; replay of a request is not charged twice.
            previous = session['workspace'].previous_request(key) if isinstance(key, str) else None
            if previous:
                if session['workspace'].investigation(previous)['incident_id'] != incident:
                    raise WorkspaceError('Request key already used.', 409)
                return previous
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
                raise WorkspaceError('A valid request key is required.')
            session['workspace'].case(incident)
            if self.run_lock.locked():
                raise WorkspaceError('An investigation is already running.', 409)
            if not self.quota.reserve(token):
                raise WorkspaceError('The judge demo usage limit has been reached.', 429)
            return session['manager'].start(incident, key, 'nebius')

    def close(self):
        # Call only after request and worker threads have stopped.
        if self.run_lock.locked():
            raise RuntimeError('Cannot clean active judge investigations')
        self.stop_cleanup.set()
        self.janitor.join()
        self.quota.close()
        shutil.rmtree(self.root, ignore_errors=True)


class JudgeHandler(Handler):
    def allowed_host(self):
        return self.headers.get('Host', '') == self.server.judge.host

    def token(self):
        try:
            jar = cookies.SimpleCookie(self.headers.get('Cookie', ''))
            return jar['judge'].value if 'judge' in jar else ''
        except cookies.CookieError:
            return ''

    def reply(self, value, code=200):
        return super().reply(clean(value), code)

    def do_GET(self):
        if not self.allowed_host(): return self.reply({'error': 'Invalid host.'}, 403)
        path = urlparse(self.path).path
        # Dedicated health probe: never creates a session or dispatches inference.
        if path == '/_internal_ready': return self.reply({'ready': True})
        session = self.server.judge.session(self.token())
        if not session:
            if path != '/': return self.reply({'error': 'Sign in required.'}, 401)
            if self.server.judge.access_mode == 'public':
                body = b'<!doctype html><html lang="en"><meta charset="utf-8"><title>IncidentCourt demo</title><h1>IncidentCourt demo</h1><p>Sessions are temporary. If the service restarted or your session expired, earlier results may no longer be available. A previous investigation may already have used provider credits. It will not restart automatically.</p><form method="post" action="/session"><input type="hidden" name="start" value="1"><button>Open demo</button></form></html>'
            else:
                body = b'<!doctype html><html lang="en"><meta charset="utf-8"><title>IncidentCourt judge access</title><h1>IncidentCourt judge access</h1><p>Sessions are temporary. If the service restarted or your session expired, earlier results may no longer be available. A previous investigation may already have used provider credits. It will not restart automatically.</p><form method="post" action="/login"><label>Access code <input type="password" name="code" required autocomplete="off"></label><button>Continue</button></form></html>'
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Security-Policy', "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body); return
        workspace = session['workspace']
        try:
            if path == '/api/status':
                return self.reply({'data': {'mode':'sample', 'detail':'Curated RCAEval sample.'},
                    'model': {'mode':'configured', 'detail':'Nebius Token Factory', 'inference_enabled':True, 'hosted_only':True, 'requested_model':MODEL, 'provider':'nebius', 'auxiliary_models_verified':False},
                    'memory': {'mode':'official-hmem-reference', 'detail':'Session-isolated H-MEM'}, 'last_verified':None, 'integration_ready':False})
            if path == '/api/cases': return self.reply(workspace.cases())
            if path == '/api/incidents': return self.reply(Store().incidents())
            if path == '/api/investigations': return self.reply({'investigations':workspace.investigations()})
            match = re.fullmatch(r'/api/cases/(IC-\d{3})', path)
            if match: return self.reply(workspace.case(match[1]))
            match = re.fullmatch(r'/api/investigations/([a-f0-9]{20})', path)
            if match: return self.reply(workspace.investigation(match[1]))
            if path == '/':
                from .config import ROOT
                html = (ROOT/'incidentcourt/static/index.html').read_text()
                html = html.replace('</head>', '<link rel="stylesheet" href="/static/judge.css"></head>')
                html = html.replace('<body>', '<body data-judge-mode="true"' + (' data-judge-public="true"' if self.server.judge.access_mode == 'public' else '') + '><p class="judge-banner">Judge demo: sample telemetry and a temporary private session.</p>')
                body = html.encode()
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers(); self.wfile.write(body); return
            if path == '/static/judge.css':
                body = b'#import-button,#review-panel,#review-jump,#check-connections,.archive-note{display:none!important}.judge-banner{padding:10px 20px;margin:0;background:#e9f2ff;color:#142641;font:14px sans-serif}'
                self.send_response(200); self.send_header('Content-Type', 'text/css; charset=utf-8')
                self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
                self.end_headers(); self.wfile.write(body); return
            # Only static routes in the original handler's allowlist remain available.
            return super().do_GET()
        except WorkspaceError as exc:
            return self.reply({'error':str(exc)}, exc.status)
        except Exception:
            return self.reply({'error':'The judge demo is unavailable.'}, 503)

    def do_POST(self):
        state = self.server.judge
        if not self.allowed_host() or self.headers.get('Origin') != state.origin:
            return self.reply({'error':'Invalid origin.'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4095: raise ValueError()
            raw = self.rfile.read(size)
        except (ValueError, TypeError):
            return self.reply({'error':'Invalid request size.'}, 413)
        if self.path == '/session':
            if state.access_mode != 'public': return self.reply({'error':'This action is unavailable.'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                return self.reply({'error':'Invalid form.'}, 415)
            try:
                fields = parse_qs(raw.decode('utf-8'), strict_parsing=True)
                if fields != {'start': ['1']}: raise ValueError()
            except (ValueError, UnicodeError):
                return self.reply({'error':'Invalid form.'}, 400)
            existing = self.token()
            try:
                token = existing if state.session(existing) else state.open_public_session()
            except Exception:
                return self.reply({'error':'Demo temporarily unavailable.'}, 503)
            if not token: return self.reply({'error':'Demo temporarily unavailable.'}, 503)
            cookie = f'judge={token}; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if state.secure else '')
            self.send_response(303); self.send_header('Location', '/'); self.send_header('Set-Cookie', cookie)
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', '0'); self.end_headers(); return
        if self.path == '/login':
            if state.access_mode != 'code': return self.reply({'error':'This action is unavailable.'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                return self.reply({'error':'Invalid form.'}, 415)
            try:
                fields = parse_qs(raw.decode('utf-8'), strict_parsing=True)
                if set(fields) != {'code'} or len(fields['code']) != 1: raise ValueError()
                token = state.authenticate(self.client_address[0], fields['code'][0])
            except (ValueError, UnicodeError): token = None
            except Exception: return self.reply({'error':'Demo temporarily unavailable.'}, 503)
            if not token: return self.reply({'error':'Access denied or temporarily unavailable.'}, 403)
            cookie = f'judge={token}; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if state.secure else '')
            self.send_response(303); self.send_header('Location', '/'); self.send_header('Set-Cookie', cookie)
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', '0'); self.end_headers(); return
        token = self.token(); session = state.session(token)
        if not session: return self.reply({'error':'Sign in required.'}, 401)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': return self.reply({'error':'JSON required.'}, 415)
        try:
            payload = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(payload, dict): raise ValueError()
        except (ValueError, UnicodeError, RecursionError): return self.reply({'error':'Invalid JSON.'}, 400)
        try:
            if self.path == '/api/cases/refresh':
                session['workspace'].cache_cases(Store().incidents())
                return self.reply(session['workspace'].cases())
            if self.path == '/api/investigations':
                if set(payload) != {'incident_id','idempotency_key'}: raise WorkspaceError('Unexpected fields.')
                identity = state.start(token, session, payload['incident_id'], payload['idempotency_key'])
                return self.reply(session['workspace'].investigation(identity), 202)
            return self.reply({'error':'This action is disabled in judge mode.'}, 403)
        except WorkspaceError as exc:
            return self.reply({'error':str(exc)}, exc.status)
        except Exception:
            return self.reply({'error':'The judge demo is unavailable.'}, 503)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8317)
    parser.add_argument('--init-ledger', action='store_true', help='Create a new ledger once; never use to reset an existing budget')
    # Proxy access requires an explicitly designed private ingress. This local preparation binds loopback only.
    args = parser.parse_args()
    if args.init_ledger:
        Quota.initialize(os.environ['JUDGE_QUOTA_LEDGER'])
        print('Initialized a new quota ledger.', flush=True)
        return
    from .config import ROOT
    from .sample import ensure_sample_db
    ensure_sample_db(ROOT / 'data/sample.sqlite3')
    mode = access_mode(os.environ)
    access_code, provider_token = load_credentials(os.environ, mode)
    maximum, per_session = run_limits(os.environ)
    state = JudgeState(os.environ['JUDGE_ORIGIN'], access_code, os.environ['JUDGE_QUOTA_LEDGER'],
        maximum, per_session, positive('JUDGE_MAX_SESSIONS'),
        positive('JUDGE_SESSION_SECONDS'), positive('JUDGE_LOGIN_ATTEMPTS'), positive('JUDGE_LOGIN_WINDOW_SECONDS'),
        provider_token=provider_token, provider_receipt_directory=os.environ.get('JUDGE_RECEIPT_DIR'), access_mode=mode)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), JudgeHandler)
    server.judge = state
    print('Judge gateway running on loopback only.', flush=True)
    try: server.serve_forever()
    finally:
        server.server_close()
        # Never delete active session files while a provider request is still in progress.
        if not state.run_lock.locked(): state.close()


if __name__ == '__main__': main()
