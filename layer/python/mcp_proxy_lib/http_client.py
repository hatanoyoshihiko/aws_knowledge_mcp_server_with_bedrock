"""
mcp_proxy_lib.http_client

Shared library for calling AWS Knowledge MCP Server (Streamable HTTP) from Lambda.
Packaged as a Lambda Layer and imported by multiple Lambdas.

- Uses JSON-RPC "tools/call".
- Supports "application/json" and "text/event-stream" (SSE).
- Does not depend on session IDs.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def json_loads(s: str) -> Any:
    return json.loads(s)


def decode_mcp_response(content_type: str, body_bytes: bytes) -> List[Dict[str, Any]]:
    body = body_bytes.decode("utf-8", errors="replace").strip()
    if not body:
        return []

    if "text/event-stream" in (content_type or ""):
        msgs: List[Dict[str, Any]] = []
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            try:
                m = json_loads(data)
                if isinstance(m, dict):
                    msgs.append(m)
            except Exception:
                continue
        return msgs

    try:
        parsed = json_loads(body)
    except Exception:
        return []

    if isinstance(parsed, list):
        return [m for m in parsed if isinstance(m, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def http_post_mcp(endpoint: str, payload: Any, timeout_s: int = 25) -> List[Dict[str, Any]]:
    data = json_dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("User-Agent", "aws-knowledge-mcp-browser-proxy/1.0")

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            ctype = resp.headers.get("Content-Type", "")
            body = resp.read() if resp.length is None or resp.length > 0 else b""
            return decode_mcp_response(ctype, body)
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = "<failed to read error body>"
        print("[MCP_HTTP_ERROR]", {
            "status": getattr(e, "code", None),
            "reason": getattr(e, "reason", None),
            "headers": dict(getattr(e, "headers", {}) or {}),
            "body": err_body[:4000],
        })
        raise RuntimeError(f"MCP HTTPError {e.code}: {err_body[:2000]}")
    except urllib.error.URLError as e:
        print("[MCP_URL_ERROR]", str(e))
        raise RuntimeError(f"MCP URLError: {e}")


def call_with_retry(endpoint: str, payload: Any, tool: str, max_retries: int = 3) -> List[Dict[str, Any]]:
    last_err: Optional[str] = None
    for attempt in range(1, max_retries + 1):
        try:
            return http_post_mcp(endpoint, payload)
        except Exception as ex:
            last_err = str(ex)
            transient = ("HTTPError 500" in last_err) or ("URLError" in last_err) or ("timed out" in last_err)
            print("[MCP_CALL_FAILURE]", {
                "attempt": attempt,
                "max_retries": max_retries,
                "tool": tool,
                "error": last_err[:2000],
                "transient": transient,
            })
            if attempt >= max_retries or not transient:
                break
            time.sleep(0.4 * attempt)
    raise RuntimeError(last_err or "Unknown error")


def mcp_tools_call(endpoint: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }

    msgs = call_with_retry(endpoint, payload, tool=tool_name, max_retries=3)

    for m in msgs:
        if m.get("id") == 1 and "result" in m:
            return m["result"]

    return {"isError": True, "content": [{"type": "text", "text": json_dumps(msgs)}]}
