"""Explicitly enabled Nebius Token Factory chat completion client.

Network fixtures verify the contract; they do not prove provider connectivity or billing.
"""
import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .integrations import IntegrationError, PROJECT_ROOT

BASE_URL = 'https://api.tokenfactory.nebius.com/v1'
# The provider response is bounded to 2 MB and the request to 100 KB. A
# larger JSON record is rejected, leaving any pre-dispatch record intact.
MAX_DURABLE_RECEIPT_BYTES = 2_300_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NebiusClient:
    def __init__(self, token='', model='', allow_inference=False, receipt_directory=None, opener=None,
                 durable_receipts=False, max_receipts=None, expected_receipt_identity=None,
                 unlimited_receipts=False):
        self.token = token
        self.model = model
        self.allow_inference = allow_inference
        self.receipt_directory = Path(receipt_directory or PROJECT_ROOT / 'artifacts/private/nebius-calls')
        self.opener = opener or build_opener(_NoRedirect())
        self.durable_receipts = durable_receipts
        bounded = type(max_receipts) is int and max_receipts > 0 and not unlimited_receipts
        unlimited = max_receipts is None and unlimited_receipts is True
        if durable_receipts and (not receipt_directory or not (bounded or unlimited)):
            raise ValueError('Durable receipts require a private directory and an explicit retention policy.')
        self.max_receipts = max_receipts
        self.receipt_identity = None
        if durable_receipts:
            if self.receipt_directory.is_symlink() or not self.receipt_directory.is_dir():
                raise ValueError('The private receipt directory must already exist.')
            stat = self.receipt_directory.stat()
            self.receipt_identity = (stat.st_dev, stat.st_ino)
            if expected_receipt_identity is not None and self.receipt_identity != expected_receipt_identity:
                raise ValueError('The private receipt directory changed.')
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

    def _durable_save(self, call_id, call, *, initial):
        """Create or atomically update a bounded record on the private volume."""
        directory = self.receipt_directory
        if directory.is_symlink():
            raise IntegrationError('The private receipt directory is unavailable.')
        try:
            stat = directory.stat()
            if (stat.st_dev, stat.st_ino) != self.receipt_identity:
                raise IntegrationError('The private receipt directory changed.')
            os.chmod(directory, 0o700)
            def redact(value):
                if isinstance(value, str):
                    return value.replace(self.token, '[redacted]') if self.token else value
                if isinstance(value, list):
                    return [redact(item) for item in value]
                if isinstance(value, dict):
                    return {redact(key): redact(item) for key, item in value.items()}
                return value
            encoded = (json.dumps(redact(call), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
            if len(encoded) > MAX_DURABLE_RECEIPT_BYTES:
                raise IntegrationError('The private receipt exceeds its size limit.')
            path = directory / (call_id + '.json')
            if initial:
                if self.max_receipts is not None and sum(1 for _ in directory.glob('*.json')) >= self.max_receipts:
                    raise IntegrationError('The private receipt limit has been reached.')
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                fd, temp_name = tempfile.mkstemp(prefix='.receipt-', dir=directory)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(encoded)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp_name, path)
                finally:
                    Path(temp_name).unlink(missing_ok=True)
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            return str(path)
        except OSError:
            raise IntegrationError('The private receipt could not be retained.') from None

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
            if self.durable_receipts:
                # An interruption after this point is conservatively unknown.
                call['status'] = 'unknown'
                self._durable_save(call_id, call, initial=True)
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
            path = (self._durable_save(call_id, call, initial=False)
                    if self.durable_receipts else self._save(call_id, call))
            return {**proof, 'provider': 'nebius-token-factory', 'requested_model': self.model,
                    'call_id': call_id, 'call_receipt': path, 'live_inference_verified': True}
        except IntegrationError as exc:
            self.stopped = True
            call.update(status=('unknown' if self.durable_receipts and call['dispatched'] else 'failed'),
                        error=str(exc), elapsed_seconds=round(time.monotonic()-started, 3))
            exc.call_id = call_id
            if self.durable_receipts:
                # A failed pre-dispatch write must never turn into a dispatch.
                path = self.receipt_directory / (call_id + '.json')
                try:
                    exc.call_receipt = self._durable_save(call_id, call, initial=not path.exists())
                except IntegrationError:
                    # Preserve an existing unknown record if an update fails.
                    exc.call_receipt = str(path) if path.exists() else None
            else:
                exc.call_receipt = self._save(call_id, call)
            raise
