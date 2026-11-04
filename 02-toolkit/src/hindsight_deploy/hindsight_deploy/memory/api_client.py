"""Small HTTP client for Hindsight External REST endpoints."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_API_URL = "http://localhost:8888"
DEFAULT_TENANT = "default"


class HindsightAPIError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HindsightClient:
    def __init__(self, base_url: str = DEFAULT_API_URL, tenant: str = DEFAULT_TENANT,
                 timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant
        self.timeout = timeout

    def _bank_path(self, bank_id: str, suffix: str = "") -> str:
        bank = urllib.parse.quote(bank_id, safe="")
        tenant = urllib.parse.quote(self.tenant, safe="")
        return f"/v1/{tenant}/banks/{bank}{suffix}"

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 timeout: Optional[float] = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise HindsightAPIError(
                f"{method} {path} -> HTTP {exc.code}: {detail}", status_code=exc.code
            ) from exc
        except urllib.error.URLError as exc:
            raise HindsightAPIError(f"{method} {path} -> connection failed: {exc.reason}") from exc
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health", timeout=15)

    def is_healthy(self) -> bool:
        try:
            doc = self.health()
        except HindsightAPIError:
            return False
        return bool(isinstance(doc, dict) and doc.get("status") == "healthy")

    def list_banks(self) -> List[Dict[str, Any]]:
        doc = self._request("GET", f"/v1/{urllib.parse.quote(self.tenant, safe='')}/banks")
        return list(doc.get("banks", [])) if isinstance(doc, dict) else []

    def bank_ids(self) -> List[str]:
        return [b["bank_id"] for b in self.list_banks() if isinstance(b, dict) and b.get("bank_id")]

    def get_bank(self, bank_id: str) -> Dict[str, Any]:
        return self._request("GET", self._bank_path(bank_id))

    def bank_exists(self, bank_id: str) -> bool:
        try:
            self.get_bank(bank_id)
            return True
        except HindsightAPIError as exc:
            if exc.status_code == 404:
                return False
            raise

    def create_bank(self, bank_id: str, mission: str = "",
                    disposition: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"bank_id": bank_id}
        if mission:
            payload["mission"] = mission
        if disposition:
            payload["disposition"] = disposition
        return self._request("PUT", self._bank_path(bank_id), payload)

    def update_bank(self, bank_id: str, mission: str = "") -> Dict[str, Any]:
        payload = {"mission": mission} if mission else {}
        return self._request("PATCH", self._bank_path(bank_id), payload)

    def count_memories(self, bank_id: str) -> int:
        doc = self._request("GET", self._bank_path(
            bank_id, "/memories/list?limit=1&offset=0"
        ))
        return int(doc.get("total", 0)) if isinstance(doc, dict) else 0

    def list_memories(self, bank_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return self._request("GET", self._bank_path(
            bank_id, f"/memories/list?limit={limit}&offset={offset}"
        ))

    def retain(self, bank_id: str, content: str, context: str = "general",
               tags: Optional[List[str]] = None, async_: bool = False,
               timeout: float = 900.0) -> Dict[str, Any]:
        item: Dict[str, Any] = {"content": content, "context": context}
        if tags:
            item["tags"] = tags
        payload: Dict[str, Any] = {"items": [item]}
        if async_:
            payload["async"] = True
        return self._request("POST", self._bank_path(bank_id, "/memories"),
                              payload, timeout=timeout)

    def recall(self, bank_id: str, query: str, budget: str = "mid") -> Dict[str, Any]:
        return self._request("POST", self._bank_path(bank_id, "/memories/recall"),
                             {"query": query, "budget": budget}, timeout=180)

    def operation(self, bank_id: str, operation_id: str) -> Dict[str, Any]:
        operation = urllib.parse.quote(operation_id, safe="")
        return self._request("GET", self._bank_path(bank_id, f"/operations/{operation}"))

    def wait_operation(self, bank_id: str, operation_id: str, poll_seconds: float = 15,
                       max_seconds: float = 1800) -> Dict[str, Any]:
        import time
        deadline = time.monotonic() + max_seconds
        last: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.operation(bank_id, operation_id)
            status = str(last.get("status", "")).lower()
            if status in {"completed", "failed", "error", "cancelled"}:
                return last
            time.sleep(poll_seconds)
        return {**last, "status": "timeout"}


__all__ = ["HindsightClient", "HindsightAPIError", "DEFAULT_API_URL"]
