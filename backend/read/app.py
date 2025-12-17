"""
ReadFunction: POST /api/read
Upstream tool: aws___read_documentation
"""

from __future__ import annotations

import os
import base64
import json
from typing import Any, Dict

from mcp_proxy_lib.http_client import mcp_tools_call
from mcp_proxy_lib.security import response, verify_origin

MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT", "https://knowledge-mcp.global.api.aws").strip()
ORIGIN_VERIFY_SECRET = (os.environ.get("ORIGIN_VERIFY_SECRET") or "").strip()

TOOL_NAME = "aws___read_documentation"


def _validate_args(params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    url = (params.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")

    out: Dict[str, Any] = {"url": url}

    if "max_length" in params and params["max_length"] is not None and str(params["max_length"]).strip() != "":
        try:
            out["max_length"] = int(params["max_length"])
        except Exception:
            pass

    if "start_index" in params and params["start_index"] is not None and str(params["start_index"]).strip() != "":
        try:
            out["start_index"] = int(params["start_index"])
        except Exception:
            pass

    return out


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod") or "").upper()
        raw_path = event.get("rawPath") or event.get("path") or ""

        if method == "OPTIONS":
            return response(200, {"ok": True})

        headers = event.get("headers") or {}
        if not verify_origin(headers, ORIGIN_VERIFY_SECRET):
            return response(403, {"message": "Forbidden"})

        if method != "POST" or not raw_path.endswith("/api/read"):
            return response(404, {"message": "Not Found"})

        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", errors="replace")

        req = json.loads(body) if body else {}
        params = req.get("params") or req
        args = _validate_args(params)

        result = mcp_tools_call(MCP_ENDPOINT, TOOL_NAME, args)
        return response(200, result)

    except ValueError as ve:
        return response(400, {"message": str(ve)})
    except Exception as e:
        import traceback
        print("[HANDLER_ERROR]", traceback.format_exc())
        return response(500, {"message": "Internal Server Error", "error": str(e)[:2000]})
