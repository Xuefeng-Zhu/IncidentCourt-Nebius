"""Pinned hosted response checks and receipts for browser investigations.

The client records gateway requests and checks each real receipt before permitting
another. A winning route describes the returned answer, not auxiliary model calls.
A zero cost reported after a request cannot prevent that request from being billed,
or prove an account's billing status. The caller must establish the approved
free-credit-only route independently before use.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import uuid

from .integrations import IntegrationError, PROJECT_ROOT

@dataclass(frozen=True)
class HostedRunPolicy:
    """Hosted NVIDIA route selected for an investigation."""

    approved_route: str

    @classmethod
    def from_env(cls, client):
        if not (isinstance(client.model, str) and client.model.startswith('nvidia/nemotron-')
                and client.configured and client.allow_inference and client.hosted_only is True):
            raise IntegrationError('A configured hosted NVIDIA Nemotron route is required; inference remains paused.')
        return cls(client.model)


class HostedNightshiftClient:
    """Pass through to Nightshift and verify each runtime response."""

    def __init__(self, client, policy, run_id, output_root=None):
        if not re.fullmatch(r'[a-f0-9]{20}', str(run_id)):
            raise ValueError('Invalid workspace run id')
        self.client, self.policy = client, policy
        self.attempts = 0
        self.stopped = False
        self.receipt_ids, self.decision_ids = set(), set()
        base = Path(output_root) if output_root is not None else PROJECT_ROOT / 'artifacts/private/hosted-browser-runs'
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.output = base / run_id
        self.output.mkdir(mode=0o700, exist_ok=False)
        self.client.receipt_directory = self.output / 'provider-calls'
        self.journal = {'format': 2, 'scope': 'browser investigation', 'run_id': run_id,
                        'approved_route': policy.approved_route,
                        'gateway_generation_attempts': 0,
                        'actual_upstream_attempts': None,
                        'provider_dispatch_stopped': False, 'calls': []}
        self._flush()

    def _flush(self):
        temporary = self.output / 'journal.json.part'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as target:
            json.dump(self.journal, target, indent=2, allow_nan=False)
            target.write('\n')
        temporary.replace(self.output / 'journal.json')

    def _validate_receipt(self, result, nonce, limit):
        if not isinstance(result, dict):
            raise IntegrationError('Nightshift did not return a verifiable response.')
        path_value = result.get('call_receipt')
        if not isinstance(path_value, str) or not path_value:
            raise IntegrationError('Nightshift did not retain its private call receipt.')
        path = Path(path_value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            path = path.resolve(strict=True)
            allowed = self.client.receipt_directory.resolve(strict=True)
            if path.parent != allowed or not path.is_file() or path.stat().st_size > 2_000_000:
                raise ValueError()
            call = json.loads(path.read_text())
        except (OSError, ValueError, TypeError):
            raise IntegrationError('Nightshift did not retain a valid private call receipt.') from None
        try:
            request, response = call['request'], call['response']
            receipt = response['runtime_receipt']
            winning = receipt['winning_route']
            actual = receipt['cost']['actual_usd']
            request_limit = request.get('max_tokens')
            output_tokens = response.get('usage', {}).get('completion_tokens', receipt.get('usage', {}).get('output_tokens'))
            valid = (call.get('status') == 'completed' and call.get('dispatched') is True
                and call.get('provider') == 'nightshift' and call.get('call_id') == result.get('call_id')
                and request.get('model') == self.policy.approved_route
                and isinstance(request_limit, int) and not isinstance(request_limit, bool) and 1 <= request_limit <= limit
                and nonce in json.dumps(request.get('messages', []))
                and response.get('served_model') == self.policy.approved_route
                and receipt.get('schema') == 'meterless.compute_receipt.v1'
                and receipt.get('requested_model') == self.policy.approved_route
                and receipt.get('routed_model') == self.policy.approved_route
                and winning.get('provider') == 'nvidia' and winning.get('model') == self.policy.approved_route
                and receipt.get('from_cache') is False and receipt.get('cache', {}).get('status') == 'miss'
                and receipt.get('privacy', {}).get('path') in ('cloud-ok', 'cloud')
                and isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual == 0
                and isinstance(output_tokens, (int, float)) and not isinstance(output_tokens, bool)
                and 0 < output_tokens <= request_limit
                and response.get('runtime_receipt') == result.get('runtime_receipt')
                and response.get('served_model') == result.get('served_model')
                and response.get('content') == result.get('content')
                and isinstance(receipt.get('receipt_id'), str) and bool(receipt['receipt_id'])
                and isinstance(receipt.get('decision_id'), str) and bool(receipt['decision_id'])
                and receipt['receipt_id'] not in self.receipt_ids
                and receipt['decision_id'] not in self.decision_ids)
            if not valid:
                raise ValueError()
        except (KeyError, AttributeError, TypeError, ValueError):
            raise IntegrationError('Nightshift did not report the approved uncached hosted route and zero estimated cost; further calls are stopped.') from None
        self.receipt_ids.add(receipt['receipt_id'])
        self.decision_ids.add(receipt['decision_id'])
        return {'call_id': call['call_id'], 'receipt_id': receipt['receipt_id'],
                'decision_id': receipt['decision_id'], 'actual_usd': actual,
                'output_tokens': output_tokens, 'max_output_tokens': request_limit}

    def complete(self, messages, max_tokens=1200):
        if self.stopped:
            raise IntegrationError('Hosted generation has stopped after an earlier failure.')
        try:
            if not (isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and 1 <= max_tokens <= 4096):
                raise ValueError('Invalid requested output-token limit')
            if not (self.client.configured and self.client.allow_inference and self.client.hosted_only is True
                    and self.client.model == self.policy.approved_route):
                raise IntegrationError('Nightshift no longer matches the approved hosted configuration.')
            limit = max_tokens
            self.attempts += 1
            self.journal['gateway_generation_attempts'] = self.attempts
            self._flush()  # Record an attempted request even if it times out.
            nonce = 'incidentcourt-browser-' + uuid.uuid4().hex
            dispatched = [dict(item) for item in messages]
            marker = '\nVerification context nonce: ' + nonce + '. Keep the requested response schema unchanged; do not echo this nonce.'
            if dispatched and dispatched[0].get('role') == 'system' and isinstance(dispatched[0].get('content'), str):
                dispatched[0]['content'] += marker
            else:
                dispatched.insert(0, {'role': 'system', 'content': marker.strip()})
            result = self.client.complete(dispatched, max_tokens=limit)
            proof = self._validate_receipt(result, nonce, limit)
            self.journal['calls'].append(proof)
            self._flush()
            return result
        except BaseException:
            self.stopped = True
            self.journal['provider_dispatch_stopped'] = True
            try:
                self._flush()
            except Exception:
                pass  # Preserve the original failure; the in-memory guard stays stopped.
            raise
