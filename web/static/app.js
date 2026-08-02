const state = {
  data: null,
  selectedFile: "",
  requestDirty: false,
  localLogClearedAt: 0,
  pollTimer: null,
  activeTab: "chat",
  lastPreviewKey: "",
  lastPreviewFile: "",
  sourceBusy: false,
  testBusy: false,
  lastTestResult: null,
  smartBusy: false
};

const $ = (id) => document.getElementById(id);
const OUTPUT_PRIORITY = ["kontrol.md", "rapor.md", "tasarim.md", "plan.md", "kaynak_context.md", "workflow_generated.json", "istek.md"];

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(el._timer);
  el._timer = window.setTimeout(() => el.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...options
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function setBusy(running, waitingCheckpoint) {
  $("startBtn").disabled = running;
  $("resumeBtn").disabled = running;
  $("smartResumeBtn").disabled = running;
  $("saveRequestBtn").disabled = running;
  $("stopBtn").disabled = !running && !waitingCheckpoint;
  $("applyTemplateBtn").disabled = running;
  $("runTestsBtn").disabled = running || state.testBusy;
  if ($("suggestAgentBtn")) $("suggestAgentBtn").disabled = state.smartBusy;
  if ($("buildContextBtn")) $("buildContextBtn").disabled = running || state.smartBusy;
  if ($("saveMemoryBtn")) $("saveMemoryBtn").disabled = state.smartBusy;
  if ($("compareAgentsBtn")) $("compareAgentsBtn").disabled = running || state.smartBusy;
  $("checkpointBox").classList.toggle("hidden", !waitingCheckpoint);
  document.body.classList.toggle("is-running", Boolean(running));
  document.body.classList.toggle("is-waiting", Boolean(waitingCheckpoint));
}

function renderTools(tools, data = {}) {
  const parts = Object.entries(tools || {}).map(([name, ok]) => {
    const cls = ok ? "ok" : "missing";
    const label = ok ? "hazir" : "eksik";
    const backend = name === "gemini" && data.geminiBackend === "antigravity" ? "antigravity" : label;
    return `<span class="tool-chip ${cls}" title="${escapeAttr(name === "gemini" ? data.agentCommands || "" : "")}"><span class="tool-dot"></span>${escapeHtml(name)}: ${escapeHtml(backend)}</span>`;
  });
  $("toolStatus").innerHTML = parts.join("");
}

function statusLabel(status) {
  const labels = {
    complete: "Tamam",
    failed: "Hata",
    idle: "Durdu",
    ready: "Hazir",
    running: "Calisiyor",
    stopped: "Durduruldu",
    waiting: "Karar"
  };
  return labels[status] || status || "Hazir";
}

function formatDuration(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}sn`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}dk ${String(rest).padStart(2, "0")}sn`;
  const hours = Math.floor(minutes / 60);
  return `${hours}s ${String(minutes % 60).padStart(2, "0")}dk`;
}

function liveElapsed(data) {
  if (data.running && data.startedAt) {
    const start = Date.parse(data.startedAt);
    if (!Number.isNaN(start)) {
      return formatDuration(Date.now() - start);
    }
  }
  return data.metrics && data.metrics.elapsed ? data.metrics.elapsed : "0sn";
}

function stageStatusLabel(stage, data) {
  if (data.status === "failed" && data.currentIndex === stage.index) return "hata";
  if (stage.status === "running") return "calisiyor";
  if (stage.status === "done") return "tamam";
  return stage.checkpoint ? "checkpoint" : "otomatik";
}

function renderWorkflow(data) {
  const workflow = data.workflow || { stages: [] };
  const completed = new Set((data.state && data.state.completed) || []);
  const query = $("stageSearch").value.trim().toLowerCase();
  const agentFilter = $("agentFilter").value;
  const filtered = workflow.stages.filter((stage) => {
    const haystack = `${stage.name} ${stage.agent} ${stage.prompt} ${(stage.writes || []).join(" ")}`.toLowerCase();
    const agentMatch = agentFilter === "all" || stage.agent === agentFilter;
    return agentMatch && (!query || haystack.includes(query));
  });

  $("workflowList").innerHTML = filtered.length
    ? filtered.map((stage) => renderStage(stage, data, completed)).join("")
    : emptyState("Filtreye uyan adim yok", "Arama veya ajan filtresini degistir.");

  const select = $("startIndex");
  const previous = select.value;
  select.innerHTML = workflow.stages.map((stage) => `<option value="${stage.index}">${stage.index}. ${escapeHtml(stage.name)}</option>`).join("");
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  } else {
    const next = Math.min(((data.state && data.state.completed || []).length + 1), workflow.stages.length || 1);
    select.value = String(next || 1);
  }
}

function renderStage(stage, data, completed) {
  let cls = stage.status;
  if (data.status === "failed" && data.currentIndex === stage.index) cls = "failed";
  const duration = (data.stageDurations || {})[String(stage.index)] || "";
  const files = stage.writes && stage.writes.length ? stage.writes.join(", ") : "-";
  const reads = stage.reads && stage.reads.length ? stage.reads.join(", ") : "-";
  const done = completed.has(stage.index);
  const meta = done ? `Tamamlandi ${duration ? `- ${duration}` : ""}` : `${stage.timeout}sn limit`;
  const prompt = stage.prompt || "";
  return `
    <article class="timeline-item ${cls}" data-stage="${stage.index}">
      <div class="timeline-rail" aria-hidden="true">
        <span class="timeline-dot"></span>
        <span class="timeline-line"></span>
      </div>
      <div class="timeline-card">
        <div class="stage-top">
          <div class="stage-title"><span>${stage.index}.</span> ${escapeHtml(stage.name)}</div>
          <div class="stage-badges">
            <span class="agent-badge ${escapeAttr(stage.agent)}">${escapeHtml(stage.agent)}</span>
            <span class="status-badge">${escapeHtml(stageStatusLabel(stage, data))}</span>
          </div>
        </div>
        <p class="stage-meta">${escapeHtml(meta)}${stage.fallbackAgent ? ` - fallback ${escapeHtml(stage.fallbackAgent)}` : ""}</p>
        <p class="stage-prompt">${escapeHtml(prompt.length > 170 ? `${prompt.slice(0, 170)}...` : prompt)}</p>
        <div class="stage-files">
          <span>Okur: ${escapeHtml(reads)}</span>
          <span>Yazar: ${escapeHtml(files)}</span>
        </div>
      </div>
    </article>
  `;
}

function renderFiles(files) {
  const query = $("fileSearch").value.trim().toLowerCase();
  const filtered = (files || []).filter((file) => !query || file.name.toLowerCase().includes(query));
  const select = $("fileSelect");
  const previous = state.selectedFile || select.value;
  select.innerHTML = filtered.map((file) => {
    const suffix = file.exists ? "" : " (yok)";
    return `<option value="${escapeAttr(file.name)}">${escapeHtml(file.name + suffix)}</option>`;
  }).join("");

  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  } else if (select.options.length) {
    select.selectedIndex = 0;
  }

  $("fileCountText").textContent = `${filtered.length} dosya`;
  $("fileList").innerHTML = filtered.length
    ? filtered.map((file) => renderFileRow(file, select.value)).join("")
    : emptyState("Dosya bulunamadi", "Filtreyi temizle veya akis ciktisi olusmasini bekle.");

  if (select.value && select.value !== state.selectedFile) {
    state.selectedFile = select.value;
    loadFile(select.value);
  } else if (!select.value) {
    $("fileOutput").textContent = "Dosya sec.";
  }
}

function renderFileRow(file, selectedName) {
  const selected = file.name === selectedName ? "selected" : "";
  const status = file.exists ? "var" : "yok";
  const size = file.exists ? formatBytes(file.size || 0) : "-";
  return `
    <button class="file-row ${selected}" type="button" data-file="${escapeAttr(file.name)}">
      <span class="file-name">${escapeHtml(file.name)}</span>
      <span class="file-meta">${status} - ${size}</span>
    </button>
  `;
}

function renderLog(data) {
  const level = $("logLevel").value;
  const query = $("logSearch").value.trim().toLowerCase();
  const rawLines = (data.logs || []).slice(state.localLogClearedAt);
  const rows = rawLines
    .map((line) => ({ text: line, level: classifyLogLine(line) }))
    .filter((row) => level === "all" || row.level === level)
    .filter((row) => !query || row.text.toLowerCase().includes(query));

  const logOutput = $("logOutput");
  const shouldStick = logOutput.scrollTop + logOutput.clientHeight >= logOutput.scrollHeight - 24;
  logOutput.innerHTML = rows.length
    ? rows.map((row) => `<div class="log-line ${row.level}"><span>${escapeHtml(row.text || " ")}</span></div>`).join("")
    : emptyState("Log henuz yok", data.running ? "Ajan ciktisi bekleniyor." : "Akis basladiginda canli log burada gorunur.");
  if (shouldStick) {
    logOutput.scrollTop = logOutput.scrollHeight;
  }
}

function classifyLogLine(line) {
  const text = String(line || "").toLowerCase();
  if (text.trim().startsWith("[$") || text.includes("$ ") || text.includes("timeout=")) return "command";
  if (text.includes("checkpoint")) return "checkpoint";

  const toolNoise = [
    "codex_core_plugins::manifest",
    "codex_core_skills::loader",
    "codex_core::shell_snapshot",
    "codex_core::tools::router",
    "skills scan truncated",
    "ignoring interface.",
    "skill conflict detected",
    "ripgrep is not available",
    "yolo mode is enabled",
    "256-color support",
  ];
  if (toolNoise.some((marker) => text.includes(marker))) return "tool";

  if (text.includes("graphify") && text.includes("not recognized")) return "warn";

  const realError = [
    "ajan hata",
    "hata:",
    "basarisiz",
    "failed:",
    "not recognized as an internal or external command",
    "operable program or batch file",
    "program 'python.exe' failed",
    "zaman asimi",
  ];
  if (realError.some((marker) => text.includes(marker))) return "error";

  if (text.includes("uyari") || text.includes("warning") || text.includes("eksik")) return "warn";
  if (text.includes("tamamlandi") || text.includes("success") || text.includes("basarili")) return "success";
  return "info";
}

function renderDiagnostics(data) {
  const diagnostics = data.diagnostics || {};
  const issues = diagnostics.issues || [];
  $("issueSummary").innerHTML = issues.length
    ? issues.slice(0, 3).map((issue) => `
        <article class="issue-card ${escapeAttr(issue.severity || "info")}">
          <strong>${escapeHtml(issue.title || "Durum")}</strong>
          <span>${escapeHtml(issue.detail || "")}</span>
        </article>
      `).join("")
    : "";

  $("diagnosticsOutput").innerHTML = issues.length
    ? issues.map((issue) => `
        <article class="diagnostic-row ${escapeAttr(issue.severity || "info")}">
          <div>
            <strong>${escapeHtml(issue.title || "Durum")}</strong>
            <p>${escapeHtml(issue.detail || "")}</p>
            ${issue.action ? `<small>${escapeHtml(issue.action)}</small>` : ""}
          </div>
          <span>${escapeHtml(issue.severity || "info")}</span>
        </article>
      `).join("")
    : emptyState("Sorun yok", "Kritik bir uyari bulunmuyor.");
}

function renderSourceTree(sourceTree) {
  const files = sourceTree.files || [];
  const copied = Boolean(sourceTree.importPath);
  $("sourceTreeMeta").textContent = sourceTree.enabled
    ? `${sourceTree.includedFiles || 0}/${sourceTree.candidateFiles || 0} dosya - ${copied ? sourceTree.importPath : "kopya yok"}`
    : "Kaynak yok";
  $("copySourceTabBtn").disabled = !sourceTree.enabled || copied || state.sourceBusy;
  $("sourceTreeOutput").innerHTML = sourceTree.enabled
    ? `
      <div class="source-tree-summary">
        <div><span>Kaynak</span><strong>${escapeHtml(sourceTree.sourcePath || "-")}</strong></div>
        <div><span>Kopya</span><strong>${escapeHtml(sourceTree.importPath || "Yok")}</strong></div>
        <div><span>Atlanan</span><strong>${escapeHtml(sourceTree.skippedFiles || 0)}</strong></div>
      </div>
      <div class="source-tree-list">
        ${files.length ? files.map((file) => `
          <div class="source-tree-row">
            <span>${escapeHtml(file.path || "-")}</span>
            <small>${escapeHtml(formatBytes(file.size || 0))}${file.clipped ? " - kirpildi" : ""}</small>
          </div>
        `).join("") : emptyState("Dosya yok", "Kaynak context icinde dosya listesi bulunamadi.")}
      </div>
    `
    : emptyState("Kaynak yok", "Dosya veya klasor secip tarat.");
}

function renderWorkflowTemplates(templatesPayload) {
  const templates = templatesPayload.templates || [];
  const select = $("workflowTemplateSelect");
  const previous = select.value;
  select.innerHTML = templates.map((item) => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.label)} (${item.stageCount})</option>`).join("");
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  } else {
    const active = templates.find((item) => item.active);
    if (active) select.value = active.id;
  }
  const selected = templates.find((item) => item.id === select.value) || templates[0];
  $("templateHint").textContent = selected ? selected.description : "Sablon sec.";
}

function renderTestResult(result) {
  if (!result) {
    $("testStatusText").textContent = state.testBusy ? "Test calisiyor" : "Test bekliyor";
    $("testOutput").innerHTML = emptyState("Test bekliyor", "Test Et butonu ile yerel kontrolleri calistir.");
    return;
  }
  $("testStatusText").textContent = `${result.status} - ${result.ranAt || ""}`;
  const checks = result.checks || [];
  $("testOutput").innerHTML = `
    <div class="test-summary ${escapeAttr(result.status || "info")}">
      <strong>${escapeHtml(result.status || "-")}</strong>
      <span>Hedef: ${escapeHtml(result.target || ".")} - Hata: ${escapeHtml(result.failed || 0)}</span>
    </div>
    ${checks.map((check) => `
      <article class="test-row ${escapeAttr(check.status || "info")}">
        <div>
          <strong>${escapeHtml(check.name || "Kontrol")}</strong>
          <small>${escapeHtml(check.command || "")}</small>
        </div>
        <span>${escapeHtml(check.status || "-")}</span>
        <pre>${escapeHtml(check.output || "")}</pre>
      </article>
    `).join("")}
  `;
}

function renderChat(data) {
  $("chatOutput").textContent = data.chat || "Sohbet henuz yok.";
}

function renderMetrics(data) {
  const metrics = data.metrics || {};
  const recent = metrics.recent || [];
  $("metricsOutput").innerHTML = `
    <div class="metric-table-summary">
      <div><span>Toplam kosu</span><strong>${metrics.total || 0}</strong></div>
      <div><span>Basari</span><strong>${metrics.success || 0}</strong></div>
      <div><span>Hata</span><strong>${metrics.failed || 0}</strong></div>
      <div><span>Toplam sure</span><strong>${escapeHtml(metrics.elapsed || "0sn")}</strong></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Zaman</th><th>Adim</th><th>Ajan</th><th>Durum</th><th>Sure</th></tr></thead>
        <tbody>
          ${recent.length ? recent.slice().reverse().map((row) => `
            <tr>
              <td>${escapeHtml(row.timestamp || "-")}</td>
              <td>${escapeHtml(row.stage_name || "-")}</td>
              <td>${escapeHtml(row.agent || "-")}</td>
              <td><span class="table-status ${escapeAttr(row.status || "")}">${escapeHtml(row.status || "-")}</span></td>
              <td>${escapeHtml(formatDuration(Number(row.elapsed || 0) * 1000))}</td>
            </tr>
          `).join("") : `<tr><td colspan="5">${emptyState("Metrik yok", "Bir akis tamamlandiginda burada gorunur.")}</td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="quality-scores" style="margin-top: 20px;">
      <h3>Son Kalite Skorlari</h3>
      ${(metrics.qualityScores || []).map(q => `
        <div class="quality-row" style="margin-bottom: 12px; background: var(--surface-2); padding: 10px; border-radius: 6px;">
          <div class="quality-head" style="display:flex; justify-content:space-between; margin-bottom: 6px;">
            <strong>${escapeHtml(q.stage_name)}</strong> <span class="muted">${escapeHtml(q.agent)}</span>
          </div>
          <div class="quality-bar-wrap" style="height: 8px; background: var(--surface-3); border-radius: 4px; overflow: hidden; margin-bottom: 6px;">
            <div class="quality-bar" style="height: 100%; width: ${q.score}%; background: ${q.score >= 90 ? 'var(--green)' : q.score >= 70 ? 'var(--cyan)' : q.score >= 40 ? 'var(--amber)' : 'var(--red)'};"></div>
          </div>
          <div class="quality-details" style="font-size: 12px;">
            <strong class="quality-score-text">${q.score}/100</strong> - <span class="muted">${escapeHtml(q.label)}</span>
          </div>
        </div>
      `).join("") || emptyState("Skor yok", "Henuz degerlendirilen adim yok.")}
    </div>
  `;
}

function renderSnapshots(data) {
  const rows = data.snapshots || [];
  $("snapshotOutput").innerHTML = rows.length
    ? rows.map((snap) => `
        <article class="snapshot-row" style="cursor:pointer;" onclick="window.loadSnapshot('${escapeHtml(snap.id)}')">
          <strong>${escapeHtml(snap.id || "-")}</strong>
          <span>${escapeHtml(snap.stage_name || snap.stage || "Snapshot")}</span>
          <small>${escapeHtml(snap.created_at || snap.timestamp || "")}</small>
        </article>
      `).join("")
    : emptyState("Gecmis yok", "Akim calisirken her adim oncesi snapshot alinir.");
}

window.loadSnapshot = async function(id) {
  $("snapshotDetailOutput").innerHTML = `<div class="empty-state">Yukleniyor...</div>`;
  try {
    const res = await api(`/api/snapshots/files?id=${encodeURIComponent(id)}`);
    $("snapshotDetailOutput").innerHTML = `
      <h3 style="margin-bottom:12px;">Snapshot: ${escapeHtml(id)}</h3>
      <div class="snapshot-file-list" style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px;">
        ${res.files.map(f => `<button class="btn quiet" onclick="window.viewSnapshotDiff('${id}', '${f}')">${escapeHtml(f)}</button>`).join("")}
      </div>
      <div id="snapshotDiffView"></div>
    `;
  } catch (err) {
    $("snapshotDetailOutput").innerHTML = emptyState("Hata", err.message);
  }
};

window.viewSnapshotDiff = async function(id, file) {
  $("snapshotDiffView").innerHTML = `<em>Yukleniyor...</em>`;
  try {
    const res = await api("/api/snapshots/diff", {
      method: "POST",
      body: JSON.stringify({ id, file })
    });
    const diffHtml = res.diff ? `<pre class="diff-viewer" style="background:var(--surface-3); padding:10px; border-radius:4px; overflow-x:auto;">${escapeHtml(res.diff)}</pre>` : "<em>Degisiklik yok veya yeni dosya.</em>";
    $("snapshotDiffView").innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <h4 style="margin:0;">${escapeHtml(file)} Degisiklikleri</h4>
        <button class="btn danger" onclick="window.restoreSnapshotFile('${id}', '${file}')">Bu Dosyayi Geri Al</button>
      </div>
      ${diffHtml}
    `;
  } catch (err) {
    $("snapshotDiffView").innerHTML = emptyState("Hata", err.message);
  }
};

window.restoreSnapshotFile = async function(id, file) {
  if (!confirm(`${file} dosyasi ${id} anindaki haline dondurulecek. Emin misiniz?`)) return;
  try {
    await api("/api/snapshots/restore-file", {
      method: "POST",
      body: JSON.stringify({ id, file })
    });
    toast("Dosya geri alindi.");
    refresh();
  } catch (err) {
    toast(err.message);
  }
};

function renderStatus(data) {
  state.data = data;
  renderTools(data.tools, data);
  renderSource(data.source || {});
  renderSmartOrchestration(data.orchestration || {});
  renderWorkflow(data);
  renderFiles(data.files);
  renderLog(data);
  renderDiagnostics(data);
  renderSourceTree(data.sourceTree || {});
  renderWorkflowTemplates(data.workflowTemplates || {});
  renderTestResult(state.lastTestResult);
  renderChat(data);
  renderMetrics(data);
  renderSnapshots(data);

  if (!state.requestDirty && document.activeElement !== $("requestInput")) {
    $("requestInput").value = data.request || "";
  }

  const total = data.state.total || 0;
  const done = (data.state.completed || []).length;
  $("progressText").textContent = `${done}/${total}`;
  $("successText").textContent = data.metrics.success || 0;
  $("failureText").textContent = data.metrics.failed || 0;
  $("liveElapsedText").textContent = liveElapsed(data);
  $("progressBar").style.width = `${data.state.progress || 0}%`;
  $("statusDetail").textContent = data.statusDetail || "Hazir";
  $("runState").textContent = statusLabel(data.status);
  $("activeStageText").textContent = currentStageText(data);
  $("nextActionText").textContent = nextActionText(data);

  const hasError = Boolean(data.lastError);
  $("errorBanner").classList.toggle("hidden", !hasError);
  $("errorBanner").textContent = hasError ? data.lastError : "";

  setBusy(Boolean(data.running), Boolean(data.waitingCheckpoint));
  updateLastOutputPreview(data).catch((error) => {
    $("lastOutputPreview").textContent = error.message;
  });
}

function renderSource(source) {
  const enabled = Boolean(source.enabled);
  $("sourceState").textContent = enabled ? "Hazir" : "Yok";
  $("sourceState").classList.toggle("muted", !enabled);
  if (source.source_path && document.activeElement !== $("sourcePathInput")) {
    $("sourcePathInput").value = source.source_path;
  }
  if (enabled) {
    const files = source.included_files ?? 0;
    const candidates = source.candidate_files ?? 0;
    const size = source.contextSize || source.context_size || 0;
    $("sourceSummary").textContent = `${files}/${candidates} dosya dahil - ${formatBytes(size)} context`;
  } else {
    $("sourceSummary").textContent = "Dosya sec, klasor sec veya yol gir.";
  }
  $("clearSourceBtn").disabled = !enabled || state.sourceBusy;
  $("scanSourceBtn").disabled = state.sourceBusy;
  $("pickSourceFileBtn").disabled = state.sourceBusy;
  $("pickSourceFolderBtn").disabled = state.sourceBusy;
  $("copySourceBtn").disabled = !enabled || Boolean(source.import_path || source.importPath) || state.sourceBusy;
}

function renderSmartOrchestration(info) {
  if (!$("smartOutput")) return;
  const suggested = info.suggestedAgent || "-";
  $("smartAgentState").textContent = suggested;
  $("smartAgentState").classList.toggle("muted", suggested === "-");
  const ctx = info.contextSummary || {};
  const decisions = Array.isArray(info.decisions) ? info.decisions : [];
  const lines = [
    `Onerilen ajan: ${suggested}`,
    `Context ozeti: ${ctx.exists ? `${ctx.name} (${formatBytes(ctx.size)})` : "yok"}`,
    "",
    "Hafiza:",
    info.memory ? clipText(String(info.memory), 520) : "Henuz proje hafizasi yok.",
  ];
  if (decisions.length) {
    lines.push("", "Son karar kayitlari:");
    decisions.slice(-4).forEach((item) => {
      const changed = (item.degistirdi || []).join(", ") || "-";
      lines.push(`- ${item.agent || "?"} / ${item.stage || "?"}: ${changed}`);
    });
  }
  if ($("smartOutput").dataset.manual !== "1") {
    $("smartOutput").textContent = lines.join("\n");
  }
}

function currentStageText(data) {
  const stages = data.workflow && data.workflow.stages ? data.workflow.stages : [];
  const current = stages.find((stage) => stage.index === data.currentIndex);
  if (current) return `${current.index}. ${current.name} - ${current.agent}`;
  if (data.status === "complete") return "Tum akis tamamlandi";
  if (data.status === "failed") return "Akis hata ile durdu";
  return "Akis beklemede";
}

function nextActionText(data) {
  if (data.waitingCheckpoint) return "Checkpoint karari ver";
  if (data.running) return "Ajan ciktisini izle";
  if (data.status === "failed") return "Hatayi incele ve ilgili adimdan devam et";
  if (data.status === "complete") return "Ciktilari kontrol et";
  const done = (data.state && data.state.completed || []).length;
  return done > 0 ? "Devam et veya bastan baslat" : "Istek gir ve akisi baslat";
}

async function updateLastOutputPreview(data) {
  const files = data.files || [];
  const existing = files.filter((file) => file.exists);
  const preferred = OUTPUT_PRIORITY.map((name) => existing.find((file) => file.name === name)).find(Boolean);
  const latest = preferred || existing.sort((a, b) => String(b.modified).localeCompare(String(a.modified)))[0];
  if (!latest) {
    $("lastOutputTitle").textContent = "Son cikti";
    $("lastOutputPreview").textContent = "Cikti olusunca burada kisa onizleme gorunur.";
    return;
  }
  const key = `${latest.name}:${latest.modified}:${latest.size}`;
  if (key === state.lastPreviewKey) return;
  state.lastPreviewKey = key;
  state.lastPreviewFile = latest.name;
  const file = await api(`/api/file?name=${encodeURIComponent(latest.name)}`);
  $("lastOutputTitle").textContent = `Son cikti - ${latest.name}`;
  const content = String(file.content || "").trim();
  $("lastOutputPreview").textContent = content ? clipText(content, 520) : "Dosya bos.";
}

async function refresh() {
  try {
    const data = await api("/api/status");
    renderStatus(data);
  } catch (error) {
    toast(error.message);
  }
}

async function loadPackages() {
  try {
    const res = await api("/api/packages");
    const pkgs = res.packages || [];
    $("packageOutput").innerHTML = pkgs.length ? pkgs.map(p => `
      <div class="package-card" style="background:var(--surface-2); padding:16px; margin-bottom:12px; border-radius:8px;">
        <div class="pkg-header" style="display:flex; justify-content:space-between; margin-bottom:8px;">
          <strong>${escapeHtml(p.package_name)}</strong>
          <small class="muted">${escapeHtml(p.created_at)}</small>
        </div>
        <div class="pkg-body" style="display:flex; justify-content:space-between; align-items:center;">
          <p style="margin:0; font-size:13px; color:var(--text-soft);">
            Dosya: ${p.file_count} | Boyut: ${formatBytes(p.zip_size)} | Test: ${escapeHtml(p.checks.find(c => c.name === 'Test raporu')?.status || '-')}
          </p>
          <a href="/api/package/download?name=${encodeURIComponent(p.package_name)}" class="btn secondary" target="_blank" download>Indir</a>
        </div>
      </div>
    `).join("") : emptyState("Paket yok", "Henuz teslim paketi uretilmedi.");
  } catch (err) {
    $("packageOutput").innerHTML = emptyState("Hata", err.message);
  }
}

async function createPackage() {
  $("createPackageBtn").disabled = true;
  $("createPackageBtn").textContent = "Olusturuluyor...";
  try {
    await api("/api/package/create", { method: "POST", body: "{}" });
    toast("Teslim paketi olusturuldu.");
    loadPackages();
  } catch (err) {
    toast(err.message);
  } finally {
    $("createPackageBtn").disabled = false;
    $("createPackageBtn").textContent = "Yeni Teslim Paketi Olustur";
  }
}

async function fetchRoles() {
  try {
    const res = await api("/api/roles");
    state.roles = res.roles || {};
    const c = $("rolesContainer");
    if (c && Object.keys(state.roles).length) {
      c.classList.remove("hidden");
      c.innerHTML = `
        <strong style="display:block; margin: 12px 0 8px 0;">Ajan Rolleri</strong>
        <ul style="list-style:none; padding:0; margin:0; font-size:12px; color:var(--muted);">
          ${Object.entries(state.roles).map(([k, v]) => `
            <li style="margin-bottom:6px;">
              <span class="table-status ${escapeAttr(v.agent)}">${escapeHtml(v.label)}</span>
              ${escapeHtml(v.prompt_prefix.substring(0, 50))}...
            </li>`).join("")}
        </ul>
      `;
    }
  } catch (err) {
    state.roles = {};
  }
}

async function pollTaskMonitor() {
  try {
    const tm = await api("/api/task-monitor");
    renderTaskMonitor(tm);
  } catch (err) {
    // ignore
  }
}

function renderTaskMonitor(tm) {
  const box = $("taskMonitorBox");
  if (!box) return;
  if (!tm || !tm.active) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  
  $("tmAgent").textContent = tm.agent || "-";
  $("tmPid").textContent = tm.pid || "-";
  $("tmElapsed").textContent = formatDuration(tm.elapsed * 1000);
  $("tmSilent").textContent = formatDuration(tm.silent_for * 1000);
  $("tmCpu").textContent = (tm.cpu_percent || 0).toFixed(1) + "%";
  $("tmMem").textContent = (tm.memory_mb || 0).toFixed(1) + " MB";

  const badge = $("tmStatusBadge");
  if (tm.probable_status === "normal") {
    badge.className = "state-pill success";
    badge.textContent = "Normal";
  } else if (tm.probable_status === "cikti uretti") {
    badge.className = "state-pill success";
    badge.textContent = "Cikti Uretti";
  } else if (tm.probable_status === "sessiz") {
    badge.className = "state-pill warning";
    badge.textContent = "Sessiz";
  } else if (tm.probable_status === "takildi") {
    badge.className = "state-pill danger";
    badge.textContent = "Takildi (Cok Sessiz)";
  } else {
    badge.className = "state-pill";
    badge.textContent = tm.probable_status;
  }

  $("tmMissingFiles").innerHTML = (tm.missing_outputs || []).length 
    ? tm.missing_outputs.map(f => `<div>${escapeHtml(f)}</div>`).join("") 
    : "-";
  $("tmProducedFiles").innerHTML = (tm.produced_outputs || []).length 
    ? tm.produced_outputs.map(f => `<div>${escapeHtml(f)}</div>`).join("") 
    : "-";
}

async function loadFile(name) {
  if (!name) {
    $("fileOutput").textContent = "Dosya sec.";
    return;
  }
  try {
    const data = await api(`/api/file?name=${encodeURIComponent(name)}`);
    $("fileOutput").textContent = data.content || "";
  } catch (error) {
    $("fileOutput").textContent = error.message;
  }
}

async function saveRequest() {
  const text = $("requestInput").value;
  await api("/api/request", {
    method: "POST",
    body: JSON.stringify({ text })
  });
  state.requestDirty = false;
  $("saveState").textContent = "Kaydedildi";
  toast("Istek kaydedildi.");
  await refresh();
}

async function startRun(resetState) {
  const startIndex = resetState ? 1 : Number($("startIndex").value || 1);
  await api("/api/run/start", {
    method: "POST",
    body: JSON.stringify({
      request: $("requestInput").value,
      resetState,
      startIndex,
      useCheckpoints: $("checkpointToggle").checked
    })
  });
  state.requestDirty = false;
  state.localLogClearedAt = 0;
  state.lastPreviewKey = "";
  toast("Akis basladi.");
  await refresh();
}

async function stopRun() {
  await api("/api/run/stop", { method: "POST", body: "{}" });
  toast("Durdurma istegi gonderildi.");
  await refresh();
}

async function sendDecision(decision) {
  await api("/api/run/decision", {
    method: "POST",
    body: JSON.stringify({ decision })
  });
  await refresh();
}

async function resetProgress() {
  await api("/api/reset", { method: "POST", body: "{}" });
  toast("Ilerleme sifirlandi.");
  await refresh();
}

async function scanSource() {
  const path = $("sourcePathInput").value.trim();
  if (!path) {
    toast("Kaynak yolu gir.");
    return;
  }
  state.sourceBusy = true;
    $("scanSourceBtn").textContent = "Taraniyor";
  try {
    const data = await api("/api/source/scan", {
      method: "POST",
      body: JSON.stringify({ path })
    });
    toast("Kaynak context hazirlandi.");
    renderStatus(data.status || await api("/api/status"));
    activateTab("files");
    $("fileSearch").value = "kaynak_context";
  } finally {
    state.sourceBusy = false;
    $("scanSourceBtn").textContent = "Tarat";
    await refresh();
  }
}

async function uploadSourceFiles(fileList, label) {
  const selected = Array.from(fileList || []);
  if (!selected.length) {
    return;
  }
  state.sourceBusy = true;
  $("scanSourceBtn").disabled = true;
  $("pickSourceFileBtn").disabled = true;
  $("pickSourceFolderBtn").disabled = true;
  toast("Dosyalar okunuyor.");
  try {
    const files = [];
    for (const file of selected.slice(0, 80)) {
      const name = file.webkitRelativePath || file.name;
      const content = await file.text();
      files.push({
        name,
        size: file.size,
        modified: file.lastModified ? new Date(file.lastModified).toISOString() : "",
        content
      });
    }
    const data = await api("/api/source/upload", {
      method: "POST",
      body: JSON.stringify({ label, files })
    });
    toast("Secilen dosyalar kaynak context'e alindi.");
    renderStatus(data.status || await api("/api/status"));
    activateTab("files");
    $("fileSearch").value = "kaynak_context";
    state.data && renderFiles(state.data.files || []);
  } finally {
    state.sourceBusy = false;
    $("scanSourceBtn").disabled = false;
    $("pickSourceFileBtn").disabled = false;
    $("pickSourceFolderBtn").disabled = false;
    $("sourceFileInput").value = "";
    $("sourceFolderInput").value = "";
    await refresh();
  }
}

async function clearSource() {
  state.sourceBusy = true;
  try {
    const data = await api("/api/source/clear", { method: "POST", body: "{}" });
    $("sourcePathInput").value = "";
    toast("Kaynak context temizlendi.");
    renderStatus(data.status || await api("/api/status"));
  } finally {
    state.sourceBusy = false;
    await refresh();
  }
}

async function repairState() {
  try {
    const data = await api("/api/state/repair", { method: "POST", body: "{}" });
    toast("Ilerleme dosyalardan toparlandi.");
    renderStatus(data.state ? { ...state.data, state: data.state } : await api("/api/status"));
  } catch (error) {
    toast(error.message);
  }
}

async function copySource() {
  state.sourceBusy = true;
  $("copySourceBtn").disabled = true;
  $("copySourceTabBtn").disabled = true;
  try {
    const data = await api("/api/source/copy", { method: "POST", body: "{}" });
    toast(`Kaynak kopyalandi: ${data.result.importPath}`);
    renderStatus(data.status || await api("/api/status"));
    activateTab("source");
  } finally {
    state.sourceBusy = false;
    await refresh();
  }
}

async function runProjectTests() {
  state.testBusy = true;
  $("runTestsBtn").disabled = true;
  $("testStatusText").textContent = "Test calisiyor";
  try {
    const data = await api("/api/project/test", {
      method: "POST",
      body: JSON.stringify({ target: $("testTarget").value })
    });
    state.lastTestResult = data.result;
    renderTestResult(data.result);
    toast(data.result.status === "success" ? "Testler temiz." : "Testlerde sorun var.");
    renderStatus(data.status || await api("/api/status"));
    activateTab("tests");
  } finally {
    state.testBusy = false;
    $("runTestsBtn").disabled = false;
    await refresh();
  }
}

async function applyWorkflowTemplate() {
  const templateId = $("workflowTemplateSelect").value;
  if (!templateId) return;
  const data = await api("/api/workflow/apply-template", {
    method: "POST",
    body: JSON.stringify({ templateId })
  });
  toast("Workflow sablonu uygulandi.");
  renderStatus(data.status || await api("/api/status"));
}

async function smartResume() {
  const suggested = state.data && state.data.diagnostics ? Number(state.data.diagnostics.suggestedStartIndex || 1) : 1;
  $("startIndex").value = String(suggested || 1);
  await startRun(false);
}

async function sendChat() {
  const input = $("chatInput");
  const text = input.value.trim();
  if (!text) return;
  await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({ text })
  });
  input.value = "";
  await refresh();
}

async function suggestAgentAction() {
  const text = $("requestInput").value.trim();
  state.smartBusy = true;
  $("smartOutput").dataset.manual = "1";
  try {
    const data = await api("/api/orchestration/suggest", {
      method: "POST",
      body: JSON.stringify({ text })
    });
    $("smartAgentState").textContent = data.agent;
    $("smartAgentState").classList.remove("muted");
    $("smartOutput").textContent = `Bu is icin onerilen ajan: ${data.agent}`;
  } finally {
    state.smartBusy = false;
    setBusy(Boolean(state.data && state.data.running), Boolean(state.data && state.data.waitingCheckpoint));
  }
}

async function buildContextSummaryAction() {
  state.smartBusy = true;
  $("smartOutput").dataset.manual = "1";
  try {
    const data = await api("/api/orchestration/context-summary", { method: "POST", body: "{}" });
    const summary = data.summary || {};
    $("smartOutput").textContent = `Context ozeti hazir: ${summary.name || "proje_ozeti.md"} (${formatBytes(summary.size)})`;
    toast("Context ozeti olusturuldu.");
    await refresh();
  } finally {
    state.smartBusy = false;
    setBusy(Boolean(state.data && state.data.running), Boolean(state.data && state.data.waitingCheckpoint));
  }
}

async function saveMemoryAction() {
  const note = $("memoryNoteInput").value.trim();
  if (!note) {
    toast("Hafiza notu bos.");
    return;
  }
  state.smartBusy = true;
  $("smartOutput").dataset.manual = "";
  try {
    const data = await api("/api/orchestration/memory", {
      method: "POST",
      body: JSON.stringify({ note })
    });
    $("memoryNoteInput").value = "";
    renderSmartOrchestration(data.orchestration || {});
    toast("Hafizaya eklendi.");
    await refresh();
  } finally {
    state.smartBusy = false;
    setBusy(Boolean(state.data && state.data.running), Boolean(state.data && state.data.waitingCheckpoint));
  }
}

async function compareAgentsAction() {
  const prompt = $("requestInput").value.trim();
  if (!prompt) {
    toast("Karsilastirma icin istek yaz.");
    return;
  }
  if (!confirm("Ayni gorev birden fazla ajana verilecek. Bu islem ajan sayisi kadar limit/token tuketir. Devam edilsin mi?")) {
    return;
  }
  const writes = $("compareWritesInput").value.split(",").map((item) => item.trim()).filter(Boolean);
  state.smartBusy = true;
  $("smartOutput").dataset.manual = "1";
  $("smartOutput").textContent = "Ajan karsilastirma calisiyor...";
  try {
    const data = await api("/api/orchestration/compare", {
      method: "POST",
      body: JSON.stringify({ prompt, writes })
    });
    const comparison = data.comparison || {};
    const rows = (comparison.results || []).map((item) => {
      const status = item.ok ? "basarili" : `basarisiz (${item.reason})`;
      return `- ${item.agent}: ${status}, ${item.elapsed}sn, dosyalar: ${(item.produced || []).join(", ") || "-"}`;
    });
    $("smartOutput").textContent = [`Rapor: ${comparison.report || "karsilastirma.md"}`, ...rows].join("\n");
    toast("Ajan karsilastirma tamamlandi.");
    await refresh();
  } finally {
    state.smartBusy = false;
    setBusy(Boolean(state.data && state.data.running), Boolean(state.data && state.data.waitingCheckpoint));
  }
}

function activateTab(name) {
  state.activeTab = name;
  document.querySelectorAll(".tab").forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".tab-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === `tab-${name}`);
  });
}

function emptyState(title, body) {
  return `<div class="empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(body)}</span></div>`;
}

function clipText(value, length) {
  return value.length > length ? `${value.slice(0, length)}\n...` : value;
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function bindEvents() {
  $("refreshBtn").addEventListener("click", refresh);
  if ($("packageBtn")) $("packageBtn").addEventListener("click", () => activateTab("packages"));
  if ($("createPackageBtn")) $("createPackageBtn").addEventListener("click", createPackage);
  $("resetBtn").addEventListener("click", () => resetProgress().catch((error) => toast(error.message)));
  $("saveRequestBtn").addEventListener("click", () => saveRequest().catch((error) => toast(error.message)));
  $("scanSourceBtn").addEventListener("click", () => scanSource().catch((error) => toast(error.message)));
  $("clearSourceBtn").addEventListener("click", () => clearSource().catch((error) => toast(error.message)));
  $("copySourceBtn").addEventListener("click", () => copySource().catch((error) => toast(error.message)));
  $("copySourceTabBtn").addEventListener("click", () => copySource().catch((error) => toast(error.message)));
  $("pickSourceFileBtn").addEventListener("click", () => $("sourceFileInput").click());
  $("pickSourceFolderBtn").addEventListener("click", () => $("sourceFolderInput").click());
  $("sourceFileInput").addEventListener("change", (event) => {
    uploadSourceFiles(event.target.files, "Secilen dosyalar").catch((error) => toast(error.message));
  });
  $("sourceFolderInput").addEventListener("change", (event) => {
    uploadSourceFiles(event.target.files, "Secilen klasor").catch((error) => toast(error.message));
  });
  $("startBtn").addEventListener("click", () => startRun(true).catch((error) => toast(error.message)));
  $("resumeBtn").addEventListener("click", () => startRun(false).catch((error) => toast(error.message)));
  $("smartResumeBtn").addEventListener("click", () => smartResume().catch((error) => toast(error.message)));
  $("stopBtn").addEventListener("click", () => stopRun().catch((error) => toast(error.message)));
  $("repairStateBtn").addEventListener("click", () => repairState());
  $("runTestsBtn").addEventListener("click", () => runProjectTests().catch((error) => toast(error.message)));
  $("applyTemplateBtn").addEventListener("click", () => applyWorkflowTemplate().catch((error) => toast(error.message)));
  $("workflowTemplateSelect").addEventListener("change", () => state.data && renderWorkflowTemplates(state.data.workflowTemplates || {}));
  if ($("suggestAgentBtn")) $("suggestAgentBtn").addEventListener("click", () => suggestAgentAction().catch((error) => toast(error.message)));
  if ($("buildContextBtn")) $("buildContextBtn").addEventListener("click", () => buildContextSummaryAction().catch((error) => toast(error.message)));
  if ($("saveMemoryBtn")) $("saveMemoryBtn").addEventListener("click", () => saveMemoryAction().catch((error) => toast(error.message)));
  if ($("compareAgentsBtn")) $("compareAgentsBtn").addEventListener("click", () => compareAgentsAction().catch((error) => toast(error.message)));

  if ($("tmForceCompleteBtn")) {
    $("tmForceCompleteBtn").addEventListener("click", async () => {
      try {
        await api("/api/run/force-complete", { method: "POST", body: "{}" });
        toast("Tamamlandi sayildi.");
      } catch (error) { toast(error.message); }
    });
  }
  if ($("tmForceFallbackBtn")) {
    $("tmForceFallbackBtn").addEventListener("click", async () => {
      try {
        await api("/api/run/force-fallback", { method: "POST", body: "{}" });
        toast("Fallback tetiklendi.");
      } catch (error) { toast(error.message); }
    });
  }

  $("clearLogBtn").addEventListener("click", () => {
    const logs = (state.data && state.data.logs) || [];
    state.localLogClearedAt = logs.length;
    $("logOutput").innerHTML = emptyState("Log temizlendi", "Yeni log satirlari burada gorunecek.");
  });
  $("requestInput").addEventListener("input", () => {
    state.requestDirty = true;
    $("saveState").textContent = "Degisti";
  });
  $("stageSearch").addEventListener("input", () => state.data && renderWorkflow(state.data));
  $("agentFilter").addEventListener("change", () => state.data && renderWorkflow(state.data));
  $("logSearch").addEventListener("input", () => state.data && renderLog(state.data));
  $("logLevel").addEventListener("change", () => state.data && renderLog(state.data));
  $("fileSearch").addEventListener("input", () => state.data && renderFiles(state.data.files || []));
  $("fileSelect").addEventListener("change", (event) => {
    state.selectedFile = event.target.value;
    loadFile(state.selectedFile);
    state.data && renderFiles(state.data.files || []);
  });
  $("fileList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-file]");
    if (!button) return;
    state.selectedFile = button.dataset.file;
    $("fileSelect").value = state.selectedFile;
    loadFile(state.selectedFile);
    state.data && renderFiles(state.data.files || []);
  });
  $("sendChatBtn").addEventListener("click", () => sendChat().catch((error) => toast(error.message)));
  $("chatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      sendChat().catch((error) => toast(error.message));
    }
  });
  document.querySelectorAll("[data-decision]").forEach((button) => {
    button.addEventListener("click", () => sendDecision(button.dataset.decision).catch((error) => toast(error.message)));
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });
}

bindEvents();
fetchRoles();
loadPackages();
refresh();
pollTaskMonitor();
state.pollTimer = window.setInterval(refresh, 1500);
state.tmPollTimer = window.setInterval(pollTaskMonitor, 2000);
