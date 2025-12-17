"""
mcp_proxy_lib.security

Common helpers for API Gateway/Lambda handlers.
"""

from __future__ import annotations

import json
from typing import Any, Dict


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def get_header(headers: Dict[str, Any] | None, name: str) -> str:
    if not headers:
        return ""
    lname = name.lower()
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == lname:
            return "" if v is None else str(v)
    return ""


def verify_origin(headers: Dict[str, Any] | None, secret: str) -> bool:
    if not secret:
        return True
    return get_header(headers, "X-Origin-Verify") == secret


def response(status: int, obj: Any) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "content-type,x-origin-verify",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json_dumps(obj),
    }
