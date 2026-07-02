(() => {
  "use strict";

  // ── DOM ───────────────────────────────────────────────────────────────────

  const probeForm    = document.getElementById("probe-form");
  const urlInput     = document.getElementById("url-input");
  const urlCount     = document.getElementById("url-count");
  const probeBtn     = document.getElementById("probe-btn");
  const probeLabel   = document.getElementById("probe-label");
  const probeSpinner = document.getElementById("probe-spinner");
  const formError    = document.getElementById("form-error");
  const resultsCard  = document.getElementById("results-card");
  const resultsBody  = document.getElementById("results-body");
  const summaryEl    = document.getElementById("summary");
  const emptyState   = document.getElementById("empty-state");

  // ── State ─────────────────────────────────────────────────────────────────

  let probeItems = [];   // [{url, platform, caption, filename, status}]
  const rowDl = {};      // idx → {dlId, status, percent, speed, eta, filename, caption, error}

  // ── Icons ─────────────────────────────────────────────────────────────────

  const IC = {
    clock: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M12 7v5l3 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    spin:  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" class="badge-spin"><path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    check: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    x:     '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    dl:    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    save:  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 21v-6h6v6M9 3v4h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

  // ── API key display ───────────────────────────────────────────────────────

  const apiKeyVal    = document.getElementById("api-key-val");
  const apiKeyCopy   = document.getElementById("api-key-copy");
  const apiKeyToggle = document.getElementById("api-key-toggle");
  const apiKeyNew    = document.getElementById("api-key-new");
  const iconCopy     = document.getElementById("icon-copy");
  const iconCheck    = document.getElementById("icon-check");
  const iconEye      = document.getElementById("icon-eye");
  const iconEyeOff   = document.getElementById("icon-eye-off");
  const keyDialog    = document.getElementById("key-dialog");
  const keyDialogName    = document.getElementById("key-dialog-name");
  const keyDialogCancel  = document.getElementById("key-dialog-cancel");
  const keyDialogConfirm = document.getElementById("key-dialog-confirm");
  let   _apiKey     = "";
  let   _keyName    = "default";
  let   _keyVisible = false;

  function updateKeyDisplay() {
    if (!apiKeyVal) return;
    apiKeyVal.textContent = _keyVisible
      ? _apiKey
      : _apiKey ? "fbdl-" + "•".repeat(16) : "…";
    if (iconEye)    iconEye.classList.toggle("is-hidden",  _keyVisible);
    if (iconEyeOff) iconEyeOff.classList.toggle("is-hidden", !_keyVisible);
  }

  fetch("/api/info").then(r => r.json()).then(d => {
    _apiKey  = d.api_key  || "";
    _keyName = d.key_name || "default";
    updateKeyDisplay();
  }).catch(() => {
    if (apiKeyVal) apiKeyVal.textContent = "—";
  });

  apiKeyToggle?.addEventListener("click", () => {
    _keyVisible = !_keyVisible;
    updateKeyDisplay();
  });

  apiKeyCopy?.addEventListener("click", () => {
    if (!_apiKey) return;
    navigator.clipboard.writeText(_apiKey).then(() => {
      iconCopy?.classList.add("is-hidden");
      iconCheck?.classList.remove("is-hidden");
      apiKeyCopy.classList.add("copied");
      setTimeout(() => {
        iconCopy?.classList.remove("is-hidden");
        iconCheck?.classList.add("is-hidden");
        apiKeyCopy.classList.remove("copied");
      }, 2000);
    });
  });

  // ── New key dialog ────────────────────────────────────────────────────────

  apiKeyNew?.addEventListener("click", () => {
    if (!keyDialog) return;
    keyDialogName.value = _keyName || "";
    keyDialog.showModal();
    keyDialogName.select();
  });

  keyDialogCancel?.addEventListener("click", () => keyDialog?.close());

  keyDialog?.addEventListener("keydown", e => {
    if (e.key === "Escape") keyDialog.close();
  });

  document.getElementById("key-dialog-form")?.addEventListener("submit", async e => {
    e.preventDefault();
    const name = (keyDialogName.value || "").trim() || "default";
    keyDialogConfirm.disabled = true;
    try {
      const res  = await fetch("/api/regenerate_key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (!res.ok) { keyDialog.close(); return; }
      _apiKey     = data.api_key  || "";
      _keyName    = data.key_name || "default";
      _keyVisible = true;
      updateKeyDisplay();
      keyDialog.close();
    } catch {
      keyDialog.close();
    } finally {
      keyDialogConfirm.disabled = false;
    }
  });

  // ── Textarea auto-resize ──────────────────────────────────────────────────

  function autoResize() {
    urlInput.style.height = "auto";
    urlInput.style.height = Math.min(urlInput.scrollHeight, 240) + "px";
    const n = parseUrls().length;
    urlCount.textContent = n > 1 ? `(${n} link)` : (n === 1 ? "(1 link)" : "");
  }

  urlInput.addEventListener("input", autoResize);
  urlInput.addEventListener("paste", () => setTimeout(autoResize, 0));

  function parseUrls() {
    return (urlInput.value || "").split("\n")
      .map(l => l.trim())
      .filter(l => l && !l.startsWith("#"));
  }

  // ── Submit → probe ────────────────────────────────────────────────────────

  probeForm.addEventListener("submit", e => {
    e.preventDefault();
    hideErr();

    const urls = parseUrls();
    if (!urls.length) { showErr("Vui lòng nhập ít nhất 1 link."); return; }

    Object.keys(rowDl).forEach(k => delete rowDl[k]);
    probeItems = urls.map(url => ({
      url, status: "done", caption: "", filename: "", error: "",
      platform: detectPlatform(url),
    }));
    // Pre-fill all rows as queued so every row shows a disabled button immediately —
    // prevents user from clicking "Tải & Lưu" on pending rows and racing the serial loop.
    urls.forEach((_, idx) => {
      rowDl[idx] = { status: "queued", percent: 0, speed: null, eta: null,
                     dlId: null, filename: null, error: null };
    });
    showTable();
    // Process links one by one: download → save → next
    (async () => {
      for (let idx = 0; idx < urls.length; idx++) {
        try {
          await startDownloadJob(idx);
          if (rowDl[idx]?.status === "dl_done") await streamFile(idx);
        } catch (e) {}
      }
    })();
  });

  // ── Per-row "Tải & Lưu" ───────────────────────────────────────────────────

  async function downloadAndSaveRow(idx) {
    await startDownloadJob(idx);
    if (rowDl[idx]?.status === "dl_done") await streamFile(idx);
  }

  // ── Core: download job (returns when done or throws) ──────────────────────

  function startDownloadJob(idx) {
    rowDl[idx] = { status: "queued", percent: 0, speed: null, eta: null,
                   dlId: null, filename: null, error: null };
    renderRow(idx);

    return new Promise((resolve, reject) => {
      (async () => {
        try {
          const dlId = await _startAndPoll(idx);
          resolve(dlId);
        } catch (e) {
          rowDl[idx] = { ...rowDl[idx], status: "dl_error", error: e.message || "Lỗi kết nối." };
          renderRow(idx); reject(e);
        }
      })();
    });
  }

  async function _startAndPoll(idx) {
    const item = probeItems[idx] || {};
    const res  = await fetch("/api/start_dl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url:    item.url || "",
        height: null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Lỗi server.");

    const dlId = data.dl_id;
    rowDl[idx].dlId   = dlId;
    rowDl[idx].status = "downloading";
    renderRow(idx);

    return new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const r = await fetch(`/api/dl_status/${dlId}`);
          const d = await r.json();
          Object.assign(rowDl[idx], d, { dlId });
          if (d.status === "done") {
            rowDl[idx].status = "dl_done";
            if (d.caption)  probeItems[idx].caption  = d.caption;
            if (d.filename) probeItems[idx].filename = d.filename;
            clearInterval(timer); renderRow(idx); resolve(dlId);
          } else if (d.status === "error") {
            clearInterval(timer); rowDl[idx].status = "dl_error";
            renderRow(idx); reject(new Error(d.error || "Download failed"));
          } else { renderRow(idx); }
        } catch (e) { clearInterval(timer); reject(e); }
      }, 300);
    });
  }

  // ── Core: fetch file from server → stream into blob → browser save ──────

  async function streamFile(idx) {
    const dl = rowDl[idx];
    if (!dl || dl.status !== "dl_done") return;

    dl.status    = "saving";
    dl.saveBytes = 0;
    dl.saveTotal = 0;
    renderRow(idx);

    try {
      const res = await fetch(`/api/dl_file/${dl.dlId}`);
      if (!res.ok) {
        let msg = `Server lỗi ${res.status}`;
        try { const d = await res.json(); if (d.error) msg = d.error; } catch {}
        throw new Error(msg);
      }

      const contentLength = +(res.headers.get("content-length") || 0);
      dl.saveTotal = contentLength;

      let blob;
      if (contentLength > 0 && res.body) {
        const reader = res.body.getReader();
        const chunks = [];
        let received = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.length;
          dl.saveBytes = received;
          renderRow(idx);
        }
        blob = new Blob(chunks, { type: "video/mp4" });
      } else {
        blob = await res.blob();
      }

      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      const baseName = dl.filename || "video.mp4";
      a.download = probeItems.length > 1
        ? `${String(idx + 1).padStart(2, "0")}_${baseName}`
        : baseName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
      dl.status = "saved";
    } catch (e) {
      dl.status = "save_error";
      dl.error  = e.message;
    }
    renderRow(idx);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  function showTable() {
    emptyState.classList.add("is-hidden");
    resultsCard.classList.remove("is-hidden");
    probeItems.forEach((_, i) => renderRow(i));
  }

  function renderAllRows() {
    probeItems.forEach((_, i) => renderRow(i));
  }

  function renderRow(idx) {
    const item = probeItems[idx];
    const dl   = rowDl[idx] || null;

    let tr = document.getElementById(`row-${idx}`);
    if (!tr) {
      tr = document.createElement("tr");
      tr.id = `row-${idx}`;
      resultsBody.appendChild(tr);
    }

    tr.innerHTML = `
      <td class="col-idx">${idx + 1}</td>
      <td class="caption-cell">${captionCell(item)}</td>
      <td class="col-progress">${progressCell(dl)}</td>
      <td class="col-status">${statusBadge(item, dl)}</td>
      <td class="col-action">${actionCell(idx, item, dl)}</td>
    `;

    tr.querySelector(".btn-dl-save")?.addEventListener("click", () => downloadAndSaveRow(idx));
    tr.querySelector(".btn-stream-save")?.addEventListener("click", () => streamFile(idx));

    updateSummary();
  }

  // ── Cell renderers ────────────────────────────────────────────────────────

  function detectPlatform(url) {
    const u = (url || "").toLowerCase();
    if (u.includes("facebook.com") || u.includes("fb.watch")) return "facebook";
    if (u.includes("tiktok.com")) return "tiktok";
    return "other";
  }

  function platformLabel(plat) {
    const map = { facebook: "FB", tiktok: "TikTok", youtube: "YT", instagram: "IG" };
    return map[plat] || plat || "?";
  }

  function captionCell(item) {
    const cap  = item.caption?.trim() || (item.status === "done" ? "(không có caption)" : "…");
    const plat = item.platform || "other";
    const badge = `<span class="plat-badge plat-${esc(plat)}">${platformLabel(plat)}</span>`;
    let html = `${badge}<span class="caption-text" title="${esc(cap)}">${esc(cap)}</span>`;
    if (item.error) html += `<span class="error-text">${esc(item.error.split("\n")[0])}</span>`;
    return html;
  }

  function progressCell(dl) {
    if (!dl || dl.status === "queued") return `<span class="prog-dash">—</span>`;

    const pct        = typeof dl.percent === "number" ? Math.max(0, Math.min(100, dl.percent)) : null;
    const isDownload = dl.status === "downloading";
    const isSaving   = dl.status === "saving";
    const isSuccess  = dl.status === "saved";
    const isDone     = ["dl_done", "saving", "saved"].includes(dl.status);

    // Save progress: 0→100% based on bytes received
    const savePct = (isSaving && dl.saveTotal > 0)
      ? Math.round(dl.saveBytes / dl.saveTotal * 100)
      : null;

    const indet   = (isDownload && pct === null) || (isSaving && savePct === null);
    const fillPct = indet ? 0
      : isSaving ? (savePct ?? 100)
      : (pct ?? (isDone ? 100 : 0));

    let label = "";
    if (isSaving && savePct !== null)
      label = `<span class="prog-label prog-pct">Lưu ${savePct}%</span>`;
    else if (isSaving)
      label = `<span class="prog-label">Lưu…</span>`;
    else if (isDownload && pct != null)
      label = `<span class="prog-label prog-pct">${pct.toFixed(0)}%</span>`;
    else if (isDone)
      label = `<span class="prog-label prog-pct${isSuccess ? " prog-ok" : ""}">100%</span>`;

    let sub = "";
    if (isDownload) {
      const parts = [];
      if (dl.speed) parts.push(dl.speed >= 1048576
        ? `${(dl.speed / 1048576).toFixed(1)} MB/s`
        : `${(dl.speed / 1024).toFixed(0)} KB/s`);
      if (dl.eta > 0) {
        const m = Math.floor(dl.eta / 60), s = Math.floor(dl.eta % 60);
        parts.push(m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`);
      }
      if (parts.length) sub = `<div class="prog-sub">${parts.join(" · ")}</div>`;
    }

    return `<div class="prog-wrap">
      <div class="prog-bar-row">
        <div class="progress-track${isSuccess ? " is-success" : ""}">
          <div class="${indet ? "progress-fill is-indeterminate" : "progress-fill"}" style="width:${fillPct}%"></div>
        </div>
        ${label}
      </div>
      ${sub}
    </div>`;
  }

  function statusBadge(item, dl) {
    if (!dl) {
      switch (item.status) {
        case "queued":  return badge("queued",  IC.clock, "Đang chờ");
        case "probing": return badge("probing", IC.spin,  "Đang lấy thông tin");
        case "done":    return badge("done",    IC.check, "Sẵn sàng");
        case "error":   return badge("error",   IC.x,     "Lỗi");
      }
    }
    switch (dl.status) {
      case "queued":      return badge("probing",     IC.spin,  "Chuẩn bị");
      case "downloading": return badge("downloading", IC.spin,  "Đang tải");
      case "processing":  return badge("downloading", IC.spin,  "Đang xử lý");
      case "dl_done":     return badge("done",        IC.check, "Tải xong");
      case "saving":      return badge("probing",     IC.spin,  "Đang lưu");
      case "saved":       return badge("done",        IC.check, "Đã lưu ✓");
      case "dl_error":    return badge("error",       IC.x,     "Lỗi tải");
      case "save_error":  return badge("error",       IC.x,     "Lỗi lưu");
    }
    return badge("queued", IC.clock, esc(dl.status));
  }

  function badge(type, icon, label) {
    return `<span class="badge badge-${type}">${icon} ${label}</span>`;
  }

  function actionCell(idx, item, dl) {
    if (item.status === "error") return `<span class="dl-dash">—</span>`;

    if (!dl) {
      if (item.status === "done")
        return `<button class="btn-dl-save row-btn row-btn--primary" type="button">${IC.dl} Tải &amp; Lưu</button>`;
      return `<span class="dl-dash">—</span>`;
    }

    switch (dl.status) {
      case "queued":
      case "downloading":
        return `<button class="row-btn" type="button" disabled>${IC.spin} Đang tải…</button>`;
      case "processing":
        return `<button class="row-btn" type="button" disabled>${IC.spin} Đang xử lý…</button>`;
      case "dl_done":
        return `<button class="btn-stream-save row-btn row-btn--primary" type="button">${IC.save} Lưu file</button>`;
      case "saving":
        return `<button class="row-btn" type="button" disabled>${IC.spin} Đang lưu…</button>`;
      case "saved":
        return `<span class="saved-label">${IC.check} Đã lưu</span>`;
      case "dl_error": {
        const errMsg = dl.error ? `<div class="dl-error-text">${esc(dl.error.split("\n")[0])}</div>` : "";
        return `<div class="dl-error-wrap"><button class="btn-dl-save row-btn row-btn--primary" type="button">${IC.dl} Thử lại</button>${errMsg}</div>`;
      }
      case "save_error": {
        const saveErr = dl.error ? `<div class="dl-error-text">${esc(dl.error.split("\n")[0])}</div>` : "";
        return `<div class="dl-error-wrap"><button class="btn-dl-save row-btn row-btn--primary" type="button">${IC.save} Thử lại lưu</button>${saveErr}</div>`;
      }
    }
    return `<span class="dl-dash">—</span>`;
  }

  function updateSummary() {
    const total  = probeItems.length;
    const ready  = probeItems.filter(i => i.status === "done").length;
    const dlDone = Object.values(rowDl).filter(d => ["dl_done","saving","saved"].includes(d.status)).length;
    const saved  = Object.values(rowDl).filter(d => d.status === "saved").length;
    summaryEl.textContent =
      `Tổng: ${total}  ·  Sẵn sàng: ${ready}  ·  Tải xong: ${dlDone}  ·  Đã lưu: ${saved}`;
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function setBusy(busy) {
    probeBtn.disabled = busy;
    probeSpinner.classList.toggle("is-hidden", !busy);
    probeLabel.textContent = busy ? "Đang xử lý…" : "Tải Xuống";
  }
  function hideErr() { formError.classList.add("is-hidden"); formError.textContent = ""; }
  function showErr(msg) { formError.textContent = msg; formError.classList.remove("is-hidden"); }
  function esc(str) { const d = document.createElement("div"); d.textContent = str ?? ""; return d.innerHTML; }
})();
