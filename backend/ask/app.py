"""
AskFunction: POST /api/ask
Flow:
  1) aws___search_documentation (limit fixed to 10)
  2) aws___read_documentation for top-K URLs
  3) Summarize with Amazon Bedrock
"""

from __future__ import annotations

import os
import base64
import json
from typing import Any, Dict, List, Tuple

import boto3

from mcp_proxy_lib.http_client import mcp_tools_call
from mcp_proxy_lib.security import response, verify_origin

MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT", "https://knowledge-mcp.global.api.aws").strip()
ORIGIN_VERIFY_SECRET = (os.environ.get("ORIGIN_VERIFY_SECRET") or "").strip()

BEDROCK_MODEL_ID = (os.environ.get("BEDROCK_MODEL_ID") or "").strip()
MAX_CHARS_FOR_SUMMARY = int(os.environ.get("MAX_CHARS_FOR_SUMMARY") or "18000")

TOOL_SEARCH = "aws___search_documentation"
TOOL_READ = "aws___read_documentation"

DEFAULT_READ_TOP_K = 3
DEFAULT_READ_MAX_LENGTH = 6000  # 1ページあたりのread量（大きすぎるとBedrock投入が膨らむ）

bedrock = boto3.client("bedrock-runtime")


def _validate_args(params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    search_phrase = (params.get("search_phrase") or "").strip()
    if not search_phrase:
        raise ValueError("search_phrase is required")

    # search と同じく server-side enforcement
    limit = 10

    topics = params.get("topics", None)
    if topics is not None:
        if not isinstance(topics, list):
            raise ValueError("topics must be an array of strings")
        topics = [str(t) for t in topics][:3]

    # ask 専用の追加パラメータ
    read_top_k = params.get("read_top_k", DEFAULT_READ_TOP_K)
    try:
        read_top_k = int(read_top_k)
    except Exception:
        read_top_k = DEFAULT_READ_TOP_K
    read_top_k = max(0, min(read_top_k, 5))  # 上限は安全に 5

    read_max_length = params.get("read_max_length", DEFAULT_READ_MAX_LENGTH)
    try:
        read_max_length = int(read_max_length)
    except Exception:
        read_max_length = DEFAULT_READ_MAX_LENGTH
    read_max_length = max(500, min(read_max_length, 20000))

    out: Dict[str, Any] = {
        "search_phrase": search_phrase,
        "limit": limit,
        "read_top_k": read_top_k,
        "read_max_length": read_max_length,
    }
    if topics:
        out["topics"] = topics
    return out


def _pick_urls_from_search(search_result: Any, k: int) -> List[Dict[str, str]]:
    """
    search結果からURL候補を取り出す（形が多少違っても落ちにくく）
    返り値: [{"title": "...", "url": "..."}, ...]
    """
    if k <= 0:
        return []

    items = None
    if isinstance(search_result, dict):
        items = search_result.get("items") or search_result.get("results") or search_result.get("documents")

    refs: List[Dict[str, str]] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or it.get("link") or "").strip()
            if not url:
                continue
            title = str(it.get("title") or it.get("name") or "").strip()
            refs.append({"title": title, "url": url})
            if len(refs) >= k:
                break
    return refs


def _extract_text_from_read(read_result: Any) -> str:
    """
    read結果から本文を取り出す（toolの返却形に依存するので保守的に）
    - dict内に "content" があり、[{type:"text", text:"..."}] 形式が多い想定で拾う
    - ダメなら全体をJSON化
    """
    if isinstance(read_result, dict):
        content = read_result.get("content")
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    t = c.get("text")
                    if isinstance(t, str) and t.strip():
                        texts.append(t.strip())
            if texts:
                return "\n".join(texts)

    return json.dumps(read_result, ensure_ascii=False)


def _build_source_corpus(search_phrase: str, refs: List[Dict[str, str]], read_texts: List[Tuple[Dict[str, str], str]]) -> str:
    chunks: List[str] = [f"# Question\n{search_phrase}"]
    for ref, text in read_texts:
        title = ref.get("title", "")
        url = ref.get("url", "")
        if not text:
            continue
        chunks.append(f"\n\n## {title}\nURL: {url}\n{text}")
    corpus = "\n".join(chunks).strip()

    if len(corpus) > MAX_CHARS_FOR_SUMMARY:
        corpus = corpus[:MAX_CHARS_FOR_SUMMARY] + "\n\n...(truncated)..."
    return corpus


def _summarize_with_bedrock(search_phrase: str, corpus: str, refs: List[Dict[str, str]]) -> str:
    if not BEDROCK_MODEL_ID:
        raise ValueError("BEDROCK_MODEL_ID is empty")

    # --- system (top-level) ---
    system_text = (
        "あなたはAWS公式ドキュメントの要約アシスタントです。"
        "必ず日本語で、事実に基づいて簡潔にまとめてください。推測はしない。"
        "不明な点は不明と書く。"
        "引用元のURLは最後に箇条書きで列挙する。"
    )

    ref_lines = "\n".join(
        f"- {r.get('title','')}: {r.get('url','')}"
        for r in (refs or [])
        if isinstance(r, dict) and r.get("url")
    )

    user_text = f"""ユーザーの質問:
{search_phrase}

参考情報（readした本文中心）:
---
{corpus}
---

候補URL:
{ref_lines if ref_lines else "(なし)"}

出力形式:
- 結論（1〜3行）
- 要点（箇条書き 3〜7個）
- 注意点（あれば）
- 参考URL（箇条書き）
"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_text,  # ★messages内にsystem roleを入れない
        "max_tokens": 800,
        "temperature": 0.2,
        "messages": [
            {"role": "user", "content": user_text},
        ],
    }

    r = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )
    payload = json.loads(r["body"].read())

    # content: [{ "type": "text", "text": "..." }, ...]
    content = payload.get("content") or []
    if isinstance(content, list) and content and isinstance(content[0], dict):
        return (content[0].get("text") or "").strip()

    # fallback
    return json.dumps(payload, ensure_ascii=False)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod") or "").upper()
        raw_path = event.get("rawPath") or event.get("path") or ""

        if method == "OPTIONS":
            return response(200, {"ok": True})

        headers = event.get("headers") or {}
        if not verify_origin(headers, ORIGIN_VERIFY_SECRET):
            return response(403, {"message": "Forbidden"})

        if method != "POST" or not raw_path.endswith("/api/ask"):
            return response(404, {"message": "Not Found"})

        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", errors="replace")

        req = json.loads(body) if body else {}
        params = req.get("params") or req
        args = _validate_args(params)

        # 1) search
        search_args = {"search_phrase": args["search_phrase"], "limit": 10}
        if "topics" in args:
            search_args["topics"] = args["topics"]
        search_result = mcp_tools_call(MCP_ENDPOINT, TOOL_SEARCH, search_args)

        # 2) pick URLs & read top-K
        refs = _pick_urls_from_search(search_result, k=args["read_top_k"])
        read_texts: List[Tuple[Dict[str, str], str]] = []

        for ref in refs:
            url = ref.get("url", "")
            if not url:
                continue
            read_args = {"url": url, "max_length": args["read_max_length"], "start_index": 0}
            read_result = mcp_tools_call(MCP_ENDPOINT, TOOL_READ, read_args)
            text = _extract_text_from_read(read_result)
            read_texts.append((ref, text))

        corpus = _build_source_corpus(args["search_phrase"], refs, read_texts)
        summary = _summarize_with_bedrock(args["search_phrase"], corpus, refs)

        return response(200, {
            "summary": summary,
            "refs": refs,
            "search": search_result,   # デバッグ用（不要なら削除OK）
        })

    except ValueError as ve:
        return response(400, {"message": str(ve)})
    except Exception as e:
        import traceback
        print("[HANDLER_ERROR]", traceback.format_exc())
        return response(500, {"message": "Internal Server Error", "error": str(e)[:2000]})


def _unwrap_tool_text(tool_result: Any) -> str:
    """
    mcp_tools_call の戻り（だいたい {content:[{type:'text',text:'...'}]}）から text を取り出す。
    """
    if isinstance(tool_result, dict):
        content = tool_result.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                    return c["text"]
    return ""


def _unwrap_tool_json(tool_result: Any) -> Any:
    """
    text が JSON っぽければ JSON にして返す。無理なら None。
    """
    t = _unwrap_tool_text(tool_result).strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except Exception:
        return None


def _pick_urls_from_search(search_result: Any, k: int) -> List[Dict[str, str]]:
    if k <= 0:
        return []

    # まず tool result の text を JSON として解釈してみる
    inner = _unwrap_tool_json(search_result)

    # search が「配列」を返すケース（[{title,url,context}, ...]）
    items = inner if isinstance(inner, list) else None

    # もし {content:{result:[...]}} みたいなラップが来てる場合も拾う
    if items is None and isinstance(inner, dict):
        maybe = inner.get("content", {})
        if isinstance(maybe, dict) and isinstance(maybe.get("result"), list):
            items = maybe["result"]

    refs: List[Dict[str, str]] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or it.get("link") or "").strip()
            if not url:
                continue
            title = str(it.get("title") or it.get("name") or "").strip()
            refs.append({"title": title, "url": url})
            if len(refs) >= k:
                break

    return refs


def _extract_text_from_read(read_result: Any) -> str:
    # read は text がそのまま Markdown のことが多い
    t = _unwrap_tool_text(read_result).strip()
    if t:
        return t

    # もし JSON で返ってくるなら JSON を文字列化
    inner = _unwrap_tool_json(read_result)
    if inner is not None:
        return json.dumps(inner, ensure_ascii=False)

    # 最後の保険
    return json.dumps(read_result, ensure_ascii=False)
