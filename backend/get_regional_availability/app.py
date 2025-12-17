"""
RegionalAvailabilityFunction: POST /api/get_regional_availability
Upstream tool: aws___get_regional_availability  (※必要なら変更)
"""

from __future__ import annotations

import os
import base64
import json
from typing import Any, Dict, Optional

from mcp_proxy_lib.http_client import mcp_tools_call
from mcp_proxy_lib.security import response, verify_origin

MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT", "https://knowledge-mcp.global.api.aws").strip()
ORIGIN_VERIFY_SECRET = (os.environ.get("ORIGIN_VERIFY_SECRET") or "").strip()

TOOL_NAME = "aws___get_regional_availability"


def _as_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _validate_args(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    何を引数に取るかがUI実装に依存しがちなので、最低限の型ガードだけして
    dict をそのまま upstream に渡します（危険な型だけ弾く）。
    """
    params = params or {}
    if not isinstance(params, dict):
        raise ValueError("body must be a JSON object")

    out: Dict[str, Any] = {}

    # よくある指定: service / region / type など
    # （無ければ無いでOK、あるなら文字列化して渡す）
    for k in ["service", "region", "feature", "sku", "instance_type", "family", "platform"]:
        v = _as_str(params.get(k))
        if v is not None:
            out[k] = v

    # その他、UIが自由に渡している追加キーも許容（プリミティブのみ）
    for k, v in params.items():
        if k in out:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list):
            # list は短く＆中身はプリミティブだけ許容
            cleaned = []
            for item in v[:20]:
                if isinstance(item, (str, int, float, bool)) or item is None:
                    cleaned.append(item)
            out[k] = cleaned
        elif isinstance(v, dict):
            # 入れ子dictは事故りやすいので拒否（必要なら許可に変えてOK）
            raise ValueError(f"{k} must not be an object")
        else:
            raise ValueError(f"{k} has unsupported type")

    return out


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        method = (
            (event.get("requestContext", {}).get("http", {}).get("method")
             or event.get("httpMethod") or "")
            .upper()
        )
        raw_path = event.get("rawPath") or event.get("path") or ""

        if method == "OPTIONS":
            return response(200, {"ok": True})

        headers = event.get("headers") or {}
        if not verify_origin(headers, ORIGIN_VERIFY_SECRET):
            return response(403, {"message": "Forbidden"})

        if method != "POST" or not raw_path.endswith("/api/get_regional_availability"):
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
