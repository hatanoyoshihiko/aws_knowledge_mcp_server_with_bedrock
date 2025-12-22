// marked settings (avoid header ids / mangling)
if (window.marked) {
  marked.setOptions({ headerIds: false, mangle: false });
}

document.addEventListener("DOMContentLoaded", () => {
  const toolSelect = document.getElementById("tool");
  const runBtn = document.getElementById("run");
  const clearBtn = document.getElementById("clear");
  const statusEl = document.getElementById("status");

  const searchField = document.getElementById("search-phrase-field");
  const topicsField = document.getElementById("topics-field");
  const askOptionsField = document.getElementById("ask-options-field");
  const urlField = document.getElementById("url-field");
  const listRegionsField = document.getElementById("list-regions-field");
  const regionalAvailabilityField = document.getElementById("regional-availability-field");

  const renderEl = document.getElementById("render");
  const rawEl = document.getElementById("raw");
  const copyBtn = document.getElementById("copyBtn");

  const topicsHint = document.getElementById("topicsHint");
  const topicCheckboxes = Array.from(document.querySelectorAll("input[name='topics']"));

  const jsonHint = document.getElementById("jsonHint");

  let lastReadMarkdown = "";

  function setStatus(msg) { statusEl.textContent = msg || ""; }

  function clearOutput() {
    renderEl.innerHTML = "";
    rawEl.textContent = "";
    setStatus("");
    lastReadMarkdown = "";
    copyBtn.classList.add("hidden");
    copyBtn.disabled = true;
    copyBtn.textContent = "📋 Markdownをコピー";
    copyBtn.classList.remove("text-green-700");
  }

  function updateForm() {
    const tool = toolSelect.value;

    searchField.classList.add("hidden");
    topicsField.classList.add("hidden");
    askOptionsField.classList.add("hidden");
    urlField.classList.add("hidden");
    listRegionsField.classList.add("hidden");
    regionalAvailabilityField.classList.add("hidden");

    if (tool === "aws___search_documentation" || tool === "aws___ask") {
      searchField.classList.remove("hidden");
      topicsField.classList.remove("hidden");
      if (tool === "aws___ask") askOptionsField.classList.remove("hidden");
    } else if (tool === "aws___read_documentation" || tool === "aws___recommend") {
      urlField.classList.remove("hidden");
    } else if (tool === "aws___list_regions") {
      listRegionsField.classList.remove("hidden");
    } else if (tool === "aws___get_regional_availability") {
      regionalAvailabilityField.classList.remove("hidden");
    }

    if (tool === "aws___read_documentation") {
      copyBtn.classList.remove("hidden");
      copyBtn.disabled = true;
    } else {
      copyBtn.classList.add("hidden");
      copyBtn.disabled = true;
    }
  }

  toolSelect.addEventListener("change", () => {
    updateForm();
    clearOutput();
  });
  updateForm();

  function flashTopicsHint() {
    topicsHint.classList.remove("hidden");
    setTimeout(() => topicsHint.classList.add("hidden"), 1600);
  }

  topicCheckboxes.forEach(cb => {
    cb.addEventListener("change", () => {
      const checked = topicCheckboxes.filter(x => x.checked);
      if (checked.length > 3) {
        cb.checked = false;
        flashTopicsHint();
      }
    });
  });

  function flashJsonHint() {
    jsonHint.classList.remove("hidden");
    setTimeout(() => jsonHint.classList.add("hidden"), 1600);
  }

  function safeJsonParse(s) { try { return JSON.parse(s); } catch { return null; } }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(s) { return escapeHtml(s).replaceAll("\n", " "); }

  // If MCP proxy returns error in the outer envelope, show it.
  function getErrorText(apiResult) {
    if (!apiResult) return null;
    if (apiResult.isError && Array.isArray(apiResult.content)) {
      const t = apiResult.content.find(x => x && x.type === "text" && typeof x.text === "string");
      return t ? t.text : "Unknown error";
    }
    return null;
  }

  // Prefer nested JSON result, but fallback to plain text for read/ask-like responses
  function getMcpInnerResult(apiResult) {
    if (!apiResult || !apiResult.content || !Array.isArray(apiResult.content)) return null;
    const textPart = apiResult.content.find(x => x && x.type === "text" && typeof x.text === "string");
    if (!textPart) return null;

    const inner = safeJsonParse(textPart.text);
    if (inner && inner.content && typeof inner.content === "object") return inner.content.result ?? null;

    // fallback: use raw text (read_documentation often returns markdown text)
    return textPart.text;
  }

  function renderErrorBox(text) {
    renderEl.innerHTML = `
      <div class="text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
        <div class="font-semibold">Error</div>
        <div class="mt-2 text-sm whitespace-pre-wrap">${escapeHtml(String(text || "").slice(0, 4000))}</div>
      </div>
    `;
  }

  function renderMarkdownToHtmlCard(title, markdownText) {
    const md = String(markdownText || "");
    const html = (window.marked ? marked.parse(md) : `<pre>${escapeHtml(md)}</pre>`);

    renderEl.innerHTML = `
      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="text-sm font-semibold text-slate-800">${escapeHtml(title)}</div>
        <div class="mt-3 md text-sm text-slate-800 leading-relaxed">${html}</div>
      </div>
    `;
  }

  // ====== ask の参考URL重複を解消（summary内の「## 参考URL」を削除し、refs側に最大3件集約） ======

  function stripReferenceSectionFromSummary(summaryText) {
    if (!summaryText || typeof summaryText !== "string") return summaryText || "";
    return summaryText.replace(/\n##\s*参考URL[\s\S]*?(?=\n##\s|\s*$)/g, "").trim();
  }

  function buildRefsHtml(refs, maxItems = 3) {
    if (!Array.isArray(refs) || refs.length === 0) return "";
    const picked = refs.slice(0, maxItems);

    return `
      <div class="mt-4">
        <div class="text-sm font-semibold text-slate-800">参考URL</div>
        <ul class="mt-2 list-disc pl-5 space-y-1 text-sm">
          ${picked.map(r => {
            const title = (r && (r.title || r.url)) ? String(r.title || r.url) : "(link)";
            const url = (r && r.url) ? String(r.url) : "";
            if (!url) return `<li>${escapeHtml(title)}</li>`;
            return `<li>
              <a class="text-sky-700 hover:underline break-all" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">
                ${escapeHtml(title)}
              </a>
            </li>`;
          }).join("")}
        </ul>
      </div>
    `;
  }

  function renderAskResult(apiJson) {
    const rawSummary = apiJson?.summary || "";
    const summary = stripReferenceSectionFromSummary(String(rawSummary || ""));

    const refs = Array.isArray(apiJson?.refs) ? apiJson.refs : [];
    const refList = buildRefsHtml(refs, 3);

    const html = (window.marked ? marked.parse(String(summary || "")) : `<pre>${escapeHtml(String(summary || ""))}</pre>`);

    renderEl.innerHTML = `
      <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="text-sm font-semibold text-slate-800">要約</div>
        <div class="mt-3 md text-sm text-slate-800 leading-relaxed">${html}</div>
        ${refList}
      </div>
    `;
  }

  function renderSearchResults(items) {
    if (!Array.isArray(items) || items.length === 0) {
      renderEl.innerHTML = `<div class="text-slate-600">結果がありませんでした。</div>`;
      return;
    }

    const cards = items.map(it => {
      const title = it.title || "(no title)";
      const url = it.url || "";
      const context = it.context || "";

      return `
        <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="flex items-start justify-between gap-3">
            <a href="${url}" target="_blank" rel="noopener noreferrer"
               class="text-sky-700 hover:underline font-semibold leading-snug">
              ${escapeHtml(title)}
            </a>
            <button class="copy-url text-xs rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-50"
                    data-copy="${escapeAttr(url)}">
              URLコピー
            </button>
          </div>
          <div class="mt-1 text-xs text-slate-500 break-all">${escapeHtml(url)}</div>
          <div class="mt-3 text-sm text-slate-700 whitespace-pre-wrap">${escapeHtml(context)}</div>
        </div>
      `;
    }).join("");

    renderEl.innerHTML = `<div class="space-y-3">${cards}</div>`;

    renderEl.querySelectorAll(".copy-url").forEach(btn => {
      btn.addEventListener("click", async () => {
        const text = btn.getAttribute("data-copy") || "";
        try {
          await navigator.clipboard.writeText(text);
          const original = btn.textContent;
          btn.textContent = "コピー済";
          setTimeout(() => btn.textContent = original, 900);
        } catch {
          const original = btn.textContent;
          btn.textContent = "失敗";
          setTimeout(() => btn.textContent = original, 900);
        }
      });
    });
  }

  function renderReadResult(markdownText) {
    const md = String(markdownText || "");
    lastReadMarkdown = md;

    copyBtn.disabled = !md;
    copyBtn.classList.remove("hidden");

    renderMarkdownToHtmlCard("Markdown（表示）", md);
  }

  function renderRecommend(items) {
    if (!Array.isArray(items) || items.length === 0) {
      renderEl.innerHTML = `<div class="text-slate-600">推薦がありませんでした。</div>`;
      return;
    }

    const cards = items.map(it => {
      const title = it.title || "(no title)";
      const url = it.url || "";
      const context = it.context || "";

      return `
        <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <a href="${url}" target="_blank" rel="noopener noreferrer"
             class="text-sky-700 hover:underline font-semibold">
            ${escapeHtml(title)}
          </a>
          <div class="mt-1 text-xs text-slate-500 break-all">${escapeHtml(url)}</div>
          ${context ? `<div class="mt-3 text-sm text-slate-700 whitespace-pre-wrap">${escapeHtml(context)}</div>` : ""}
        </div>
      `;
    }).join("");

    renderEl.innerHTML = `<div class="space-y-3">${cards}</div>`;
  }

  function renderRegions(items) {
    if (Array.isArray(items) && items.length > 0) {
      const cards = items.map(it => {
        if (typeof it === "string") {
          return `
            <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div class="font-semibold text-slate-900">${escapeHtml(it)}</div>
            </div>
          `;
        }
        const name = it.region_id || it.name || it.region || it.id || it.code || "(region)";
        const desc = it.region_long_name || it.description || it.label || it.long_name || "";
        return `
          <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div class="font-semibold text-slate-900">${escapeHtml(String(name))}</div>
            ${desc ? `<div class="mt-1 text-sm text-slate-700">${escapeHtml(String(desc))}</div>` : ""}
            <div class="mt-3 text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-2 whitespace-pre-wrap">${escapeHtml(JSON.stringify(it, null, 2))}</div>
          </div>
        `;
      }).join("");
      renderEl.innerHTML = `<div class="space-y-3">${cards}</div>`;
      return;
    }

    renderEl.innerHTML = `
      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">${escapeHtml(JSON.stringify(items, null, 2))}</div>
      </div>
    `;
  }

  function renderAvailability(itemsOrObj) {
    if (Array.isArray(itemsOrObj)) {
      if (itemsOrObj.length === 0) {
        renderEl.innerHTML = `<div class="text-slate-600">結果がありませんでした。</div>`;
        return;
      }

      const cards = itemsOrObj.map((it) => {
        const title =
          it.resource ||
          it.resource_id ||
          it.id ||
          it.name ||
          it.filter ||
          it.identifier ||
          "(resource)";

        const available = it.isAvailableIn || it.available || it.availableIn;
        const notAvailable = it.isNotAvailableIn || it.notAvailable || it.notAvailableIn;
        const planned = it.isPlannedIn || it.plannedIn;

        return `
          <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div class="font-semibold text-slate-900">${escapeHtml(String(title))}</div>

            <div class="mt-3 space-y-2 text-sm">
              ${available ? `<div><span class="font-semibold text-green-700">isAvailableIn</span>: <span class="text-slate-700">${escapeHtml(JSON.stringify(available))}</span></div>` : ""}
              ${notAvailable ? `<div><span class="font-semibold text-red-700">isNotAvailableIn</span>: <span class="text-slate-700">${escapeHtml(JSON.stringify(notAvailable))}</span></div>` : ""}
              ${planned ? `<div><span class="font-semibold text-amber-700">isPlannedIn</span>: <span class="text-slate-700">${escapeHtml(JSON.stringify(planned))}</span></div>` : ""}
            </div>

            <div class="mt-3 text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-2 whitespace-pre-wrap">${escapeHtml(JSON.stringify(it, null, 2))}</div>
          </div>
        `;
      }).join("");

      renderEl.innerHTML = `<div class="space-y-3">${cards}</div>`;
      return;
    }

    renderEl.innerHTML = `
      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">${escapeHtml(JSON.stringify(itemsOrObj, null, 2))}</div>
      </div>
    `;
  }

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(lastReadMarkdown || "");
      const original = copyBtn.textContent;
      copyBtn.textContent = "✓ コピーしました";
      copyBtn.classList.add("text-green-700");
      setTimeout(() => {
        copyBtn.textContent = original;
        copyBtn.classList.remove("text-green-700");
      }, 1200);
    } catch {
      alert("コピーに失敗しました（ブラウザの権限設定をご確認ください）");
    }
  });

  function apiPathForTool(tool) {
    if (tool === "aws___search_documentation") return "/api/search";
    if (tool === "aws___ask") return "/api/ask";
    if (tool === "aws___read_documentation") return "/api/read";
    if (tool === "aws___recommend") return "/api/recommend";
    if (tool === "aws___list_regions") return "/api/list_regions";
    if (tool === "aws___get_regional_availability") return "/api/get_regional_availability";
    return "/api/search";
  }

  async function readResponseAsJsonOrText(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const text = await res.text();
    rawEl.textContent = text;

    if (ct.includes("application/json")) {
      const j = safeJsonParse(text);
      if (j) return { kind: "json", value: j };
      return { kind: "text", value: text };
    }
    return { kind: "text", value: text };
  }

  function parseCommaList(s) {
    return String(s || "")
      .split(",")
      .map(x => x.trim())
      .filter(Boolean);
  }

  function buildAvailabilityParamsFromForm() {
    const params = {};
    const region = (document.getElementById("gaRegion").value || "").trim();
    const resourceType = (document.getElementById("gaResourceType").value || "").trim();
    const filters = parseCommaList(document.getElementById("gaFilters").value || "");
    const nextToken = (document.getElementById("gaNextToken").value || "").trim();

    if (region) params.region = region;
    if (resourceType) params.resource_type = resourceType;
    if (filters.length > 0) params.filters = filters;
    if (nextToken) params.next_token = nextToken;

    return params;
  }

  function buildAvailabilityParams() {
    const jsonText = (document.getElementById("gaJson").value || "").trim();
    if (jsonText) {
      const j = safeJsonParse(jsonText);
      if (j && typeof j === "object" && !Array.isArray(j)) return j;
      flashJsonHint();
    }
    return buildAvailabilityParamsFromForm();
  }

  function validateAvailabilityParams(params) {
    const missing = [];
    if (!params || typeof params !== "object") return ["region", "resource_type"];
    if (!params.region) missing.push("region");
    if (!params.resource_type) missing.push("resource_type");
    return missing;
  }

  runBtn.addEventListener("click", async () => {
    clearOutput();
    setStatus("実行中...");

    const tool = toolSelect.value;
    const params = {};

    if (tool === "aws___search_documentation" || tool === "aws___ask") {
      params.search_phrase = document.getElementById("searchPhrase").value || "";
      params.limit = 10;
      const topics = topicCheckboxes.filter(x => x.checked).map(x => x.value);
      if (topics.length > 0) params.topics = topics.slice(0, 3);

      if (tool === "aws___ask") {
        params.read_top_k = Number(document.getElementById("askReadTopK").value || 3);
        params.read_max_length = Number(document.getElementById("askReadMaxLen").value || 6000);
      }

    } else if (tool === "aws___read_documentation" || tool === "aws___recommend") {
      params.url = document.getElementById("urlInput").value || "";

    } else if (tool === "aws___list_regions") {
      // no params

    } else if (tool === "aws___get_regional_availability") {
      Object.assign(params, buildAvailabilityParams());

      const missing = validateAvailabilityParams(params);
      if (missing.length > 0) {
        renderErrorBox(`必須パラメータが不足しています: ${missing.join(", ")}\n例: {"region":"ap-northeast-1","resource_type":"cfn","filters":["AWS::Lambda::Function"]}`);
        setStatus("");
        return;
      }
    }

    if (tool === "aws___read_documentation") {
      copyBtn.classList.remove("hidden");
      copyBtn.disabled = true;
    } else {
      copyBtn.classList.add("hidden");
      copyBtn.disabled = true;
    }

    const apiPath = apiPathForTool(tool);

    try {
      const res = await fetch(apiPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params }),
      });

      const parsed = await readResponseAsJsonOrText(res);

      if (!res.ok) {
        const msg = (parsed.kind === "json")
          ? (parsed.value?.message || JSON.stringify(parsed.value))
          : parsed.value;

        renderErrorBox(`HTTP ${res.status}\n${String(msg).slice(0, 4000)}`);
        setStatus("");
        return;
      }

      if (parsed.kind !== "json") {
        renderErrorBox(`JSONではない応答が返ってきました（APIパスやCloudFrontのエラールーティングを確認してください）\n\n${String(parsed.value).slice(0, 4000)}`);
        setStatus("");
        return;
      }

      const apiJson = parsed.value;
      rawEl.textContent = JSON.stringify(apiJson, null, 2);

      const outerErr = getErrorText(apiJson);
      if (outerErr) {
        renderErrorBox(outerErr);
        setStatus("");
        return;
      }

      if (tool === "aws___ask") {
        renderAskResult(apiJson);
        setStatus("完了");
        setTimeout(() => setStatus(""), 1200);
        return;
      }

      const inner = getMcpInnerResult(apiJson);

      if (inner === null && tool === "aws___get_regional_availability") {
        renderErrorBox("結果の取り出しに失敗しました。Raw を確認してください（ツール応答が想定フォーマットと異なる可能性があります）。");
        setStatus("");
        return;
      }

      if (tool === "aws___search_documentation") {
        renderSearchResults(inner);
      } else if (tool === "aws___read_documentation") {
        renderReadResult(inner);
      } else if (tool === "aws___recommend") {
        renderRecommend(inner);
      } else if (tool === "aws___list_regions") {
        renderRegions(inner);
      } else if (tool === "aws___get_regional_availability") {
        renderAvailability(inner);
      } else {
        renderEl.innerHTML = `<div class="text-slate-700">${escapeHtml(String(inner ?? ""))}</div>`;
      }

      setStatus("完了");
      setTimeout(() => setStatus(""), 1200);

    } catch (e) {
      renderErrorBox(String(e));
      setStatus("");
    }
  });

  clearBtn.addEventListener("click", clearOutput);
});
