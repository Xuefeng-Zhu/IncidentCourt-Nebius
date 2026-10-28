"""Local bridge to the Meterless H-MEM reference implementation."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_REVISION = "1742dec56a66e58eef9dda2d2b865823758ca8cd"
_ID = re.compile(r"^[A-Za-z0-9_:-]{1,120}$")
_MEMORY_LOCK = threading.RLock()


class IntegrationError(RuntimeError):
    """Sanitized integration failure safe to display without credentials."""


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {field}")
    return value


class HMemStore:
    """Calls upstream HMEM; Python does not reimplement its retrieval algorithm.

    Separate persistent store from telemetry. Only reviewed findings from nonholdout
    incidents are eligible. Recall is historical context, never current evidence.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def _run(self, action: str, payload: dict | None = None) -> Any:
        node = shutil.which("node")
        if not node:
            raise IntegrationError("H-MEM requires Node.js 24 or later")
        request = {"action": action, "directory": str(self.path), "payload": payload or {}}
        with _MEMORY_LOCK:
            try:
                result = subprocess.run(
                    [node, "--disable-warning=ExperimentalWarning", "--experimental-transform-types",
                     str(PROJECT_ROOT / "scripts/hmem_bridge.ts")],
                    input=json.dumps(request), text=True, capture_output=True, timeout=20,
                    cwd=PROJECT_ROOT, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise IntegrationError("H-MEM reference process unavailable") from None
            if result.returncode:
                raise IntegrationError("H-MEM reference failed; check Node.js 24 and store integrity")
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                raise IntegrationError("H-MEM returned an invalid response") from None

    def remember_verified(self, incident_id: str, content: str, evidence_ids: list[str],
                          services: list[str], verifier: str, *, split: str = "development",
                          confidence: float = 0.8) -> dict:
        """Caller must verify cited evidence against that earlier incident first.

        No labels, evaluator files, original case paths, or injection metadata belong
        in content. Holdout runs cannot be promoted by this application interface.
        """
        _identifier(incident_id, "incident id")
        if split not in {"development", "history"}:
            raise ValueError("Only nonholdout investigations may enter historical memory")
        if not isinstance(content, str) or not 10 <= len(content.strip()) <= 4000:
            raise ValueError("Memory needs a bounded verified finding")
        if not isinstance(verifier, str) or not verifier.strip():
            raise ValueError("An explicit verifier is required")
        if not evidence_ids or len(evidence_ids) > 50:
            raise ValueError("Verified evidence references are required")
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence must be in [0, 1]")
        for item in evidence_ids:
            _identifier(item, "evidence reference")
        for service in services:
            _identifier(service, "service")
        return self._run("remember", {"incident_id": incident_id, "content": content.strip(),
            "evidence_ids": evidence_ids, "services": services[:10], "verifier": verifier[:120],
            "split": split, "confidence": confidence})

    def retrieve(self, query: str, exclude_incident_id: str, services=(), limit: int = 5) -> dict:
        _identifier(exclude_incident_id, "excluded incident id")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("A bounded retrieval query is required")
        if not 1 <= limit <= 5:
            raise ValueError("Memory retrieval limit must be between 1 and 5")
        for service in services:
            _identifier(service, "retrieval service")
        return self._run("retrieve", {"query": query, "exclude_incident_id": exclude_incident_id,
                                      "services": list(services)[:10], "limit": limit})

    def status(self) -> dict:
        try:
            return {"state": "working", **self._run("status")}
        except IntegrationError as exc:
            return {"state": "unavailable", "engine": "Meterless H-MEM reference", "reason": str(exc)}

    def audit(self) -> list[dict]:
        return self._run("audit")
