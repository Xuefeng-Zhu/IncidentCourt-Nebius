"""Local-only HTTP application, serving static assets and bounded workflows."""
import argparse
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import ROOT
from .store import Store, DataError
from .integrations import HMemStore, IntegrationError
from .investigate import investigate
from .workspace import Workspace, WorkspaceError, JobManager, source_context, MAX_REPORT_BYTES, now

RUN_LOCK = threading.Lock()
SERVICES_LOCK = threading.Lock()
SERVICES = {}
RECOVERED_PATHS = set()


def workspace_service():
    context = source_context()
    key = (str(ROOT), context['id'])
    with SERVICES_LOCK:
        if key not in SERVICES:
            workspace = Workspace(ROOT / 'data/workspace.sqlite3', context)
            if str(workspace.path) not in RECOVERED_PATHS:
                workspace.recover()
                RECOVERED_PATHS.add(str(workspace.path))
            SERVICES[key] = (workspace, JobManager(workspace, RUN_LOCK))
        return SERVICES[key]


def connection_check():
    result = {'checked_at': now()}
    try:
        store = Store()
        if store.mode == 'zetaris':
            connected = store.remote.query('SELECT 1 AS connected') == [{'connected': 1}]
        else:
            store.incidents()
            connected = True
        result['data'] = {'state': 'connected' if connected else 'unavailable'}
    except Exception:
        result['data'] = {'state': 'unavailable', 'detail': 'Could not read the configured telemetry source.'}
    if source_context()['mode'] == 'sample' and os.environ.get('INCIDENTCOURT_NEBIUS_SAMPLE') != '1':
        result['model'] = {'state': 'offline', 'detail': 'Offline sample uses rules, with no model calls.'}
    elif os.environ.get('INCIDENTCOURT_NEBIUS_SAMPLE') == '1':
        from .nebius import NebiusClient
        client = NebiusClient.from_env()
        probe = client.probe()
        result['model'] = {'state': probe['state'], 'model_advertised': client.model in probe.get('models', [])}
    else:
        result['model'] = {'state': 'offline', 'detail': 'Local rules do not use a model.'}
    return result


def status():
    sample = os.environ.get('SAMPLE_MODE', '').lower() in ('1', 'true')
    mode = 'sample' if sample else os.environ.get('INCIDENTCOURT_DATA_MODE', 'local')
    db = ROOT / ('data/sample.sqlite3' if sample else 'data/telemetry.sqlite3')
    nebius_sample = sample and os.environ.get('INCIDENTCOURT_NEBIUS_SAMPLE') == '1'
    if nebius_sample:
        from .nebius import NebiusClient
        model = NebiusClient.from_env().status()
    else:
        model = {'state': 'not_configured', 'requested_model': None, 'inference_enabled': False, 'hosted_only': False}
    memory = HMemStore(ROOT / ('data/memory-sample' if sample else 'data/memory')).status()
    configured = model.get('state') == 'configured_unverified'
    enabled = bool(nebius_sample and configured and model.get('inference_enabled'))
    hosted = model.get('hosted_only') is True
    model_detail = ('Nebius Token Factory configured; inference is explicitly enabled.' if enabled else
                    'Nebius Token Factory inference is paused or not configured.') if nebius_sample else 'Local deterministic rules; no model calls.'
    return {'data': {'mode': mode if mode in ('zetaris', 'sample') or db.exists() else 'not_imported',
                     'detail': (('Curated real RCAEval subset with Nebius inference.' if nebius_sample else 'Curated real RCAEval subset; offline sample execution.') if sample else 'Local RCAEval telemetry; Zetaris path not verified.') if mode != 'zetaris' else 'Zetaris selected. Current connectivity is not checked by this status view.'},
            'model': {'mode': 'configured' if configured else 'not_configured', 'detail': model_detail,
                      'inference_enabled': enabled, 'hosted_only': hosted,
                      'requested_model': model.get('requested_model'), 'provider': 'nebius' if nebius_sample else 'local', 'auxiliary_models_verified': False},
            'memory': {'mode': 'official-hmem-reference' if memory.get('state') == 'working' else 'unavailable',
                       'detail': 'Official Meterless H-MEM reference; historical context rechecked against current telemetry.',
                       'reference': memory},
            'last_verified': None,
            'integration_ready': False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Avoid logging request bodies, query strings, provider errors or credentials.
        pass

    def reply(self, value, code=200):
        body=json.dumps(value,allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        host=self.headers.get('Host','')
        return host in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.allowed_host():
            return self.reply({'error':'Local access only.'},403)
        path=urlparse(self.path).path
        try:
            if path=='/api/status': return self.reply(status())
            if path=='/api/incidents': return self.reply(Store().incidents())
            if path == '/api/cases':
                return self.reply(workspace_service()[0].cases())
            if path == '/api/investigations':
                return self.reply({'investigations': workspace_service()[0].investigations()})
            match = re.fullmatch(r'/api/cases/(IC-\d{3})', path)
            if match:
                return self.reply(workspace_service()[0].case(match[1]))
            match = re.fullmatch(r'/api/investigations/([a-f0-9]{20})', path)
            if match:
                return self.reply(workspace_service()[0].investigation(match[1]))
            files={'/':('index.html','text/html'),'/static/styles.css':('styles.css','text/css'),'/static/app.js':('app.js','text/javascript'),
                   '/static/visual-data.js':('visual-data.js','text/javascript'),'/static/visuals.js':('visuals.js','text/javascript'),
                   '/static/visuals.css':('visuals.css','text/css')}
            if path not in files: return self.reply({'error':'Not found.'},404)
            name,mime=files[path]
            body=(ROOT/'incidentcourt/static'/name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(body)
        except WorkspaceError as exc:
            self.reply({'error': str(exc), **exc.details}, exc.status)
        except (DataError,IntegrationError,ValueError) as exc:
            self.reply({'error':str(exc)},503)
        except Exception:
            self.reply({'error':'Local application error; inspect configuration and data import.'},500)

    def do_POST(self):
        if not self.allowed_host(): return self.reply({'error': 'Local access only.'}, 403)
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://localhost:{self.server.server_port}', f'http://127.0.0.1:{self.server.server_port}'):
            return self.reply({'error': 'Cross-origin requests are disabled.'}, 403)
        path = self.path
        review = re.fullmatch(r'/api/investigations/([a-f0-9]{20})/review', path)
        known = path in ('/api/investigate', '/run', '/api/investigations', '/api/investigations/import', '/api/cases/refresh', '/api/connections/check') or review
        if not known: return self.reply({'error': 'Not found.'}, 404)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply({'error': 'JSON is required.'}, 415)
        maximum = MAX_REPORT_BYTES if path == '/api/investigations/import' else 65536 if review else 4095
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= maximum: return self.reply({'error': 'Invalid request size.'}, 413)
            def invalid_constant(value): raise ValueError()
            payload = json.loads(self.rfile.read(size), parse_constant=invalid_constant)
            if not isinstance(payload, dict): raise ValueError()
        except (ValueError, TypeError, RecursionError):
            return self.reply({'error': 'Invalid JSON request.'}, 400)
        try:
            if path == '/api/connections/check':
                return self.reply(connection_check())
            if path.startswith('/api/cases') or path.startswith('/api/investigations'):
                workspace, manager = workspace_service()
                if path == '/api/cases/refresh':
                    try:
                        workspace.cache_cases(Store().incidents())
                    except Exception:
                        workspace.catalog_failed()
                        return self.reply({'error': 'Telemetry is unavailable. Cached cases and saved reports remain available.'}, 503)
                    return self.reply(workspace.cases())
                if path == '/api/investigations/import':
                    identity = workspace.save_report(payload)
                    return self.reply(workspace.investigation(identity), 201)
                if review:
                    return self.reply(workspace.save_review(review[1], payload.get('note'), payload.get('reviewed'), payload.get('version')))
                key = payload.get('idempotency_key')
                if not isinstance(key, str): raise WorkspaceError('An idempotency key is required.')
                model = 'nebius' if workspace.context['mode'] == 'sample' and os.environ.get('INCIDENTCOURT_NEBIUS_SAMPLE') == '1' else 'local'
                identity = manager.start(payload.get('incident_id'), key, model)
                return self.reply(workspace.investigation(identity), 202)
            # Hosted execution uses the workspace path with retained receipts.
            # The legacy synchronous endpoint has no equivalent receipt checks.
            if payload.get('model', 'local') == 'nebius':
                return self.reply({'error': 'Hosted investigations must use the guarded workspace flow.'}, 403)
            # Existing offline synchronous API remains compatible and shares the same lock.
            if not RUN_LOCK.acquire(blocking=False):
                return self.reply({'error': 'An investigation is already running.'}, 409)
            try:
                report = investigate(payload.get('incident_id', ''), payload.get('model', 'local'))
                self.reply(report)
            finally:
                RUN_LOCK.release()
        except WorkspaceError as exc:
            self.reply({'error': str(exc), **exc.details}, exc.status)
        except (DataError, IntegrationError, ValueError) as exc:
            self.reply({'error': str(exc)}, 422)
        except Exception:
            self.reply({'error': 'Investigation failed; no completed result was accepted.'}, 500)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8317)
    parser.add_argument('--host',default='127.0.0.1',choices=('127.0.0.1','0.0.0.0'))
    args=parser.parse_args()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    workspace_service()
    print(f'IncidentCourt: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
