"""HTTP client for the Hindsight External API.

The toolkit talks to a running Hindsight instance over its plain HTTP API
(no MCP handshake needed for the REST endpoints). Every call returns parsed
JSON or raises `HindsightAPIError` with the server's message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_API_URL = "http://localhost:8888"
DEFAULT_TENANT = "default"


class HindsightAPIError(RuntimeError):
    """Raised when the Hindsight API returns an error response."""


class HindsightClient:
    """Minimal REST client for the Hindsight External API."""

    def __init__(
        self,
        base_url: str = DEFAULT_API_URL,
        tenant: str = DEFAULT_TENANT,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant
        self.timeout = timeout

    # ── low-level ────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise HindsightAPIError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise HindsightAPIError(f"{method} {path} -> connection failed: {exc.reason}") from exc
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body

    # ── health ───────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """Return the API health document."""
        return self._request("GET", "/health", timeout=15)

    def is_healthy(self) -> bool:
        """True when the API reports healthy AND the database is connected."""
        try:
            doc = self.health()
        except HindsightAPIError:
            return False
        return bool(isinstance(doc, dict) and doc.get("status") == "healthy")

    # ── banks ────────────────────────────────────────────────────────────

    def list_banks(self) -> List[Dict[str, Any]]:
        """List every bank the tenant exposes."""
        doc = self._request("GET", f"/v1/{self.tenant}/banks")
        if isinstance(doc, dict):
            return list(doc.get("banks", []))
        return []

    def bank_ids(self) -> List[str]:
        return [b.get("bank_id") for b in self.list_banks() if b.get("bank_id")]

    def get_bank(self, bank_id: str) -> Dict[str, Any]:
        """Fetch one bank's metadata (raises if it does not exist)."""
        return self._request("GET", f"/v1/{self.tenant}/banks/{bank_id}")

    def bank_exists(self, bank_id: str) -> bool:
        try:
            self.get_bank(bank_id)
            return True
        except HindsightAPIError:
            return False

    def create_bank(
        self,
        bank_id: str,
        mission: str = "",
        disposition: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Create a bank. Idempotent: an existing bank is returned unchanged."""
        payload: Dict[str, Any] = {"bank_id": bank_id}
        if mission:
            payload["mission"] = mission
        if disposition:
            payload["disposition"] = disposition
        return self._request("PUT", f"/v1/{self.tenant}/banks/{bank_id}", payload)

    def update_bank(self, bank_id: str, mission: str = "") -> Dict[str, Any]:
        """Update a bank's mission."""
        payload: Dict[str, Any] = {}
        if mission:
            payload["mission"] = mission
        return self._request("PATCH", f"/v1/{self.tenant}/banks/{bank_id}", payload)

    # ── memories ─────────────────────────────────────────────────────────

    def count_memories(self, bank_id: str) -> int:
        """Total number of memory units in a bank."""
        doc = self._request(
            "GET", f"/v1/{self.tenant}/banks/{bank_id}/memories/list?limit=1&offset=0"
        )
        if isinstance(doc, dict):
            return int(doc.get("total", 0))
        return 0

    def list_memories(self, bank_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Page through a bank's memory units."""
        return self._request(
            "GET",
            f"/v1/{self.tenant}/banks/{bank_id}/memories/list?limit={limit}&offset={offset}",
        )

    def retain(
        self,
        bank_id: str,
        content: str,
        context: str = "general",
        tags: Optional[List[str]] = None,
        async_: bool = False,
        timeout: float = 900.0,
    ) -> Dict[str, Any]:
        """Store a memory.

        With async_=True the server returns immediately with an operation id;
        with async_=False the call blocks until extraction completes. The local
        CPU LLM needs several minutes per fact, so async_=True is the default
        for anything that must not hit a client timeout.
        """
        item: Dict[str, Any] = {"content": content, "context": context}
        if tags:
            item["tags"] = tags
        payload: Dict[str, Any] = {"items": [item]}
        if async_:
            payload["async"] = True
        return self._request(
            "POST",
            f"/v1/{self.tenant}/banks/{bank_id}/memories",
            payload,
            timeout=timeout,
        )

    def recall(self, bank_id: str, query: str, budget: str = "mid") -> Dict[str, Any]:
        """Search a bank's memories."""
        return self._request(
            "POST",
            f"/v1/{self.tenant}/banks/{bank_id}/memories/recall",
            {"query": query, "budget": budget},
            timeout=180.0,
        )

    def operation(self, bank_id: str, operation_id: str) -> Dict[str, Any]:
        """Fetch the status of an async operation."""
        return self._request(
            "GET", f"/v1/{self.tenant}/banks/{bank_id}/operations/{operation_id}"
        )

    def wait_operation(
        self,
        bank_id: str,
        operation_id: str,
        poll_seconds: float = 15.0,
        max_seconds: float = 1800.0,
    ) -> Dict[str, Any]:
        """Poll an operation until it reaches a terminal state."""
        import time

        deadline = time.time() + max_seconds
        last: Dict[str, Any] = {}
        while time.time() < deadline:
            last = self.operation(bank_id, operation_id)
            status = str(last.get("status", "")).lower()
            if status in {"completed", "failed", "error", "cancelled"}:
                return last
            time.sleep(poll_seconds)
        last["status"] = "timeout"
        return last


__all__ = ["HindsightClient", "HindsightAPIError", "DEFAULT_API_URL"]
