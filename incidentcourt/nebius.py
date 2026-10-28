"""Explicitly enabled Nebius Token Factory chat completion client.

Network fixtures verify the contract; they do not prove provider connectivity or billing.
"""
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .integrations import IntegrationError, PROJECT_ROOT

BASE_URL = 'https://api.tokenfactory.nebius.com/v1'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NebiusClient:
    def __init__(self, token='', model='', allow_inference=False, receipt_directory=None, opener=None):
        self.token = token
        self.model = model
        self.allow_inference = allow_inference
        self.receipt_directory = Path(receipt_directory or PROJECT_ROOT / 'artifacts/private/nebius-calls')
        self.opener = opener or build_opener(_NoRedirect())
        self.stopped = False

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('NEBIUS_API_KEY', ''), os.environ.get('NEBIUS_MODEL', ''),
                   os.environ.get('NEBIUS_ALLOW_INFERENCE') == '1')

    @property
    def configured(self):
        return bool(self.token and re.fullmatch(r'nvidia/[A-Za-z0-9_.-]+', self.model, re.IGNORECASE))

    def status(self):
        return {'state': 'configured_unverified' if self.configured else 'not_configured',
                'requested_model': self.model or None, 'inference_enabled': self.allow_inference,
                'hosted_only': True}

    def _request(self, path, body=None):
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'}
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        if data is not None:
            headers['Content-Type'] = 'application/json'
        req = Request(BASE_URL + path, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=180 if body else 30) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise IntegrationError('Nebius response exceeded the size limit.')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except HTTPError as exc:
            raise IntegrationError(f'Nebius HTTP {exc.code}.') from None
        except (URLError, TimeoutError, OSError):
            raise IntegrationError('Nebius is unavailable or timed out.') from None
        except (ValueError, TypeError):
            raise IntegrationError('Nebius returned invalid JSON.') from None

    def list_models(self):
        if not self.configured:
            raise IntegrationError('A Nebius API key and explicit NVIDIA model are required.')
        value = self._request('/models')
        models = value.get('data')
        if not isinstance(models, list):
            raise IntegrationError('Nebius model discovery returned an invalid shape.')
        return [item['id'] for item in models if isinstance(item, dict) and isinstance(item.get('id'), str)]

    def probe(self):
        if not self.configured:
            return {'state': 'not_configured', 'models': []}
        try:
            return {'state': 'online', 'models': self.list_models(), 'live_inference_verified': False}
        except IntegrationError:
            return {'state': 'unavailable', 'models': [], 'live_inference_verified': False}

    def _save(self, call_id, call):
        self.receipt_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.receipt_directory / (call_id + '.json')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(call, stream, indent=2, allow_nan=False)
            stream.write('\n')
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)

    def complete(self, messages, max_tokens=1200):
        if self.stopped:
            raise IntegrationError('Nebius generation stopped after an earlier failure.')
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= 4096:
            raise ValueError('max_tokens must be between 1 and 4096')
        if not isinstance(messages, list) or not messages or len(json.dumps(messages)) > 100_000:
            raise ValueError('A bounded messages list is required')
        call_id = uuid.uuid4().hex[:20]
        request = {'model': self.model, 'messages': messages, 'max_tokens': max_tokens,
                   'temperature': 0.1, 'stream': False}
        call = {'call_id': call_id, 'created_at': datetime.now(timezone.utc).isoformat(),
                'provider': 'nebius-token-factory', 'request': request, 'dispatched': False}
        started = time.monotonic()
        try:
            if not self.configured or not self.allow_inference:
                raise IntegrationError('Nebius inference is disabled or not configured.')
            if self.model not in self.list_models():
                raise IntegrationError('The selected NVIDIA model is not advertised by Nebius for this key.')
            call['dispatched'] = True
            response = self._request('/chat/completions', request)
            try:
                content = response['choices'][0]['message']['content']
                served_model = response['model']
                if served_model != self.model or not isinstance(content, str) or not content.strip():
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise IntegrationError('Nebius returned an invalid or unexpected model response.') from None
            proof = {'content': content, 'served_model': served_model, 'usage': response.get('usage', {}),
                     'provider_request_id': response.get('id')}
            call.update(status='completed', response=proof, elapsed_seconds=round(time.monotonic()-started, 3))
            path = self._save(call_id, call)
            return {**proof, 'provider': 'nebius-token-factory', 'requested_model': self.model,
                    'call_id': call_id, 'call_receipt': path, 'live_inference_verified': True}
        except IntegrationError as exc:
            self.stopped = True
            call.update(status='failed', error=str(exc), elapsed_seconds=round(time.monotonic()-started, 3))
            exc.call_id = call_id
            exc.call_receipt = self._save(call_id, call)
            raise
