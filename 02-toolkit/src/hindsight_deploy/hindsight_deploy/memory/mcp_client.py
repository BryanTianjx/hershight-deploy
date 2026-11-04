"""MCP (Streamable HTTP) client helper for the Hindsight External API.

The MCP session id lives in the `mcp-session-id` RESPONSE HEADER, not in the
body. The server answers with an SSE stream, so the payload is read out of
the `data:` lines.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, List, Tuple

PROTOCOL_VERSION = "2024-11-05"


def _post(url: str, payload: Dict[str, Any], session_id: str = "") -> Tuple[int, Dict[str, str], str]:
    """POST a JSON-RPC request and return (status, headers, body)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if session_id:
        req.add_header("mcp-session-id", session_id)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8", "replace")
        return resp.status, dict(resp.headers), body


def _parse_sse(body: str) -> Dict[str, Any]:
    """Extract the JSON payload from an SSE stream body."""
    for line in body.splitlines():
        if line.startswith("data:"):
            chunk = line[5:].strip()
            if chunk:
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    continue
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def mcp_handshake(base_url: str) -> str:
    """Initialize an MCP session and return its session id."""
    url = f"{base_url.rstrip('/')}/mcp/"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "hindsight-deploy", "version": "1.0"},
        },
    }
    _, headers, _ = _post(url, payload)
    for key, value in headers.items():
        if key.lower() == "mcp-session-id":
            return value
    raise RuntimeError("MCP server did not return an mcp-session-id header")


def mcp_tools(base_url: str, session_id: str) -> List[str]:
    """List the MCP tools the server advertises."""
    url = f"{base_url.rstrip('/')}/mcp/"
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    _, _, body = _post(url, payload, session_id)
    doc = _parse_sse(body)
    return [t.get("name") for t in doc.get("result", {}).get("tools", []) if t.get("name")]


def mcp_call(
    base_url: str,
    session_id: str,
    tool: str,
    arguments: Dict[str, Any],
    call_id: int = 3,
) -> Dict[str, Any]:
    """Invoke an MCP tool and return the parsed result."""
    url = f"{base_url.rstrip('/')}/mcp/"
    payload = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    _, _, body = _post(url, payload, session_id)
    return _parse_sse(body)


__all__ = ["mcp_handshake", "mcp_tools", "mcp_call"]
