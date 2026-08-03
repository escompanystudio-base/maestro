#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maestro web panel.

This module intentionally uses only the Python standard library. The desktop
GUI remains available, while this file exposes the same orchestration engine
through a local browser panel.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
import webbrowser
from collections import Counter, deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import workflow as WF
from logging_config import setup_logging
from runner import run_agent_stage
from orkestra import (
    CHAT_FILE,
    GENERATED_WORKFLOW_FILE,
    CONTEXT_SUMMARY_FILE,
    LOG_DIR,
    REQUEST_FILE,
    STATE_FILE,
    WorkflowError,
    AGENT_ROLES,
    ANTIGRAVITY_OUTPUT_EXIT_GRACE_SECONDS,
    agent_for_role,
    assess_run_quality,
    append_project_memory,
    append_chat_entry,
    append_event,
    append_metric,
    build_context_summary,
    extract_last_handoff,
    load_decisions,
    load_events,
    load_project_memory,
    load_run_records,
    produced_files,
    record_stage_decision,
    antigravity_outputs_ready,
    build_command,
    chat_path,
    check_inputs,
    create_delivery_package,
    list_delivery_packages,
    compose_wizard_brief,
    create_snapshot,
    ensure_chat_file,
    expected_agent_commands_label,
    fallback_agent_for,
    find_tool,
    gemini_backend,
    kill_process_tree,
    is_antigravity_gemini_stage,
    latest_antigravity_transcript,
    list_snapshots,
    load_generated_workflow,
    load_metrics,
    load_quality_scores,
    load_state,
    missing_required_tools,
    next_stage_ref,
    process_env,
    process_kwargs,
    read_antigravity_transcript_summary,
    read_chat_tail,
    read_user_request,
    resolve_command,
    resolve_project_dir,
    restore_snapshot,
    restore_snapshot_files,
    run_agent_comparison,
    save_generated_workflow,
    save_state,
    save_user_request,
    score_stage_quality,
    snapshot_diff,
    snapshot_files_dir,
    stage_ref,
    suggest_agent,
    validate_workflow,
    verify_outputs,
    with_fallback_agent,
    workflow_hash,
    workflow_uses_request,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web" / "static"
OUTPUT_FILES = [
    REQUEST_FILE,
    "kaynak_context.md",
    CHAT_FILE,
    "plan.md",
    "tasarim.md",
    "rapor.md",
    "kontrol.md",
    "test_raporu.json",
    "kalite_raporu.json",
    "web_qa_raporu.json",
    "kabul_kriterleri.md",
    "kabul_kontrol.md",
    GENERATED_WORKFLOW_FILE,
]
CODE_EXTS = {
    ".bat",
    ".cs",
    ".css",
    ".csv",
    ".env.example",
    ".go",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".php",
    ".ps1",
    ".rs",
    ".scss",
    ".sql",
    ".svelte",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
SOURCE_CONTEXT_FILE = "kaynak_context.md"
SOURCE_META_FILE = "source_context.json"
SOURCE_IMPORT_DIR = "source_import"
TEST_REPORT_FILE = "test_raporu.json"
QUALITY_REPORT_FILE = "kalite_raporu.json"
WEB_AUDIT_REPORT_FILE = "web_qa_raporu.json"
ACCEPTANCE_FILE = "kabul_kriterleri.md"
ACCEPTANCE_REPORT_FILE = "kabul_kontrol.md"
MAX_SOURCE_FILES = 80
MAX_SOURCE_TREE_FILES = 260
MAX_SOURCE_FILE_BYTES = 14_000
MAX_SOURCE_TOTAL_BYTES = 360_000
MAX_COPY_FILES = 260
MAX_TEST_OUTPUT_CHARS = 14_000
TEXT_FILENAMES = {
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "Makefile",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
MAX_UPLOADED_FILES = 80
MAX_UPLOADED_FILE_CHARS = 24_000
MAX_UPLOADED_TOTAL_CHARS = 420_000
SKIP_DIRS = {
    ".git",
    ".next",
    ".orkestra",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    LOG_DIR,
    "node_modules",
    SOURCE_IMPORT_DIR,
    "venv",
}

WORKFLOW_TEMPLATES: dict[str, dict[str, Any]] = {
    "default": {
        "label": "Genel Uygulama",
        "description": "Plan, tasarim, kodlama, kontrol ve duzeltme akisi.",
        "data": {
            "summary": "Genel Maestro ajan akisi",
            "project_type": "default",
            "brief_hash": "",
            "stages": WF.STAGES,
        },
    },
    "existing-app": {
        "label": "Mevcut Projeyi Gelistir",
        "description": "Secilen dosya/klasor context'ini esas alip mevcut projeyi bozmadan iyilestirir.",
        "data": {
            "summary": "Mevcut proje gelistirme akisi",
            "project_type": "existing-app",
            "brief_hash": "",
            "stages": [
                {
                    "name": "Kaynak Analizi",
                    "agent": "codex",
                    "prompt": "kaynak_context.md, istek.md ve sohbet.md dosyalarini oku. Mevcut projenin mimarisini, risklerini, eksiklerini ve gelistirme sirasini plan.md dosyasina yaz. Kod yazma.",
                    "reads": ["istek.md", SOURCE_CONTEXT_FILE],
                    "writes": ["plan.md"],
                    "checkpoint": True,
                    "timeout": 1800,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Uygulanabilir Tasarim",
                    "agent": "claude",
                    "prompt": "plan.md ve kaynak_context.md dosyalarini oku. Mevcut teknolojiye uygun UI/UX, dosya yapisi ve uygulama akisini tasarim.md dosyasina sade ve uygulanabilir sekilde yaz.",
                    "reads": ["plan.md", SOURCE_CONTEXT_FILE],
                    "writes": ["tasarim.md"],
                    "checkpoint": True,
                    "timeout": 1800,
                    "fallback_agent": "codex",
                },
                {
                    "name": "Kodlama",
                    "agent": "claude",
                    "prompt": "istek.md, plan.md, tasarim.md ve kaynak_context.md dosyalarini oku. Mevcut projeyi bastan yazmadan tamamla veya project icinde calisir hale getir. Bitince rapor.md dosyasina calistirma adimlarini yaz.",
                    "reads": ["istek.md", "plan.md", "tasarim.md", SOURCE_CONTEXT_FILE],
                    "writes": ["rapor.md"],
                    "checkpoint": True,
                    "timeout": 2400,
                    "fallback_agent": "codex",
                },
                {
                    "name": "Yerel Test",
                    "agent": "codex",
                    "prompt": "Uretilen kodu yerel olarak kontrol et. py_compile, varsa pytest ve calistirma talimatlarini denetle. Bulgulari kontrol.md dosyasina yaz.",
                    "reads": ["rapor.md"],
                    "writes": ["kontrol.md"],
                    "checkpoint": True,
                    "timeout": 1800,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Son Duzeltme",
                    "agent": "claude",
                    "prompt": "kontrol.md dosyasindaki eksikleri uygula. rapor.md dosyasini son durum ve calistirma komutlariyla guncelle.",
                    "reads": ["kontrol.md"],
                    "writes": ["rapor.md"],
                    "checkpoint": False,
                    "timeout": 1800,
                    "fallback_agent": "codex",
                },
            ],
        },
    },
    "test-fix": {
        "label": "Sadece Test ve Bugfix",
        "description": "Mevcut ciktiyi test eder, hata listesini cikarir ve duzeltir.",
        "data": {
            "summary": "Test ve bugfix odakli akis",
            "project_type": "test-fix",
            "brief_hash": "",
            "stages": [
                {
                    "name": "Test Plani",
                    "agent": "codex",
                    "prompt": "istek.md, kaynak_context.md ve mevcut kod dosyalarini oku. Calistirma/test stratejisini plan.md dosyasina yaz.",
                    "reads": ["istek.md"],
                    "writes": ["plan.md"],
                    "checkpoint": True,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Kod Kontrolu",
                    "agent": "codex",
                    "prompt": "Projeyi statik olarak incele, py_compile/pytest sonucunu dikkate al ve hatalari kontrol.md dosyasina yaz. Kodu degistirme.",
                    "reads": ["plan.md"],
                    "writes": ["kontrol.md"],
                    "checkpoint": True,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Bugfix",
                    "agent": "claude",
                    "prompt": "kontrol.md dosyasindaki hatalari uygula, calistirma adimlarini rapor.md dosyasina yaz.",
                    "reads": ["kontrol.md"],
                    "writes": ["rapor.md"],
                    "checkpoint": False,
                    "timeout": 1800,
                    "fallback_agent": "codex",
                },
            ],
        },
    },
    "desktop-python": {
        "label": "Python Masaustu",
        "description": "Tkinter/PySide benzeri masaustu uygulamalari icin daha kisa ve kod odakli akis.",
        "data": {
            "summary": "Python masaustu uygulama akisi",
            "project_type": "desktop-python",
            "brief_hash": "",
            "stages": [
                {
                    "name": "Masaustu Kapsam",
                    "agent": "codex",
                    "prompt": "istek.md ve kaynak_context.md dosyalarini oku. Masaustu uygulama kapsam, ekranlar, veri dosyalari, calistirma ve kabul kriterlerini plan.md dosyasina yaz.",
                    "reads": ["istek.md"],
                    "writes": ["plan.md"],
                    "checkpoint": True,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
                {
                    "name": "UI ve Akis",
                    "agent": "claude",
                    "prompt": "plan.md dosyasina gore masaustu UI yerlesimini ve kullanici akislarini tasarim.md dosyasina yaz. Mevcut teknolojiye yakin kal.",
                    "reads": ["plan.md"],
                    "writes": ["tasarim.md"],
                    "checkpoint": True,
                    "timeout": 1200,
                    "fallback_agent": "codex",
                },
                {
                    "name": "Uygulama Kodlama",
                    "agent": "claude",
                    "prompt": "plan.md ve tasarim.md dosyalarini oku. Python masaustu uygulamasini calisir hale getir, run.bat ve README ekle. Sonucu rapor.md dosyasina yaz.",
                    "reads": ["plan.md", "tasarim.md"],
                    "writes": ["rapor.md"],
                    "checkpoint": True,
                    "timeout": 2400,
                    "fallback_agent": "codex",
                },
                {
                    "name": "Test ve Paket Hazirligi",
                    "agent": "codex",
                    "prompt": "Kodun calisma risklerini ve paketleme/test eksiklerini kontrol.md dosyasina yaz.",
                    "reads": ["rapor.md"],
                    "writes": ["kontrol.md"],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
            ],
        },
    },
}


def fmt_seconds(value: float | int | None) -> str:
    if value is None:
        return ""
    seconds = int(max(0, value))
    if seconds < 60:
        return f"{seconds}sn"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}dk {seconds:02d}sn"


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stage_public(stage: dict[str, Any], idx: int, completed: set[int], current: int | None) -> dict[str, Any]:
    if current == idx:
        status = "running"
    elif idx in completed:
        status = "done"
    else:
        status = "pending"
    return {
        "index": idx,
        "name": stage.get("name", f"Adim {idx}"),
        "agent": stage.get("agent", "-"),
        "prompt": stage.get("prompt", ""),
        "reads": stage.get("reads", []),
        "writes": stage.get("writes", []),
        "checkpoint": bool(stage.get("checkpoint", False)),
        "timeout": int(stage.get("timeout", WF.DEFAULT_TIMEOUT)),
        "fallbackAgent": stage.get("fallback_agent"),
        "status": status,
    }


def _lang_for(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return {
        "bat": "bat",
        "cs": "csharp",
        "css": "css",
        "go": "go",
        "html": "html",
        "java": "java",
        "js": "javascript",
        "json": "json",
        "jsx": "jsx",
        "kt": "kotlin",
        "md": "markdown",
        "php": "php",
        "ps1": "powershell",
        "py": "python",
        "rs": "rust",
        "scss": "scss",
        "sql": "sql",
        "svelte": "svelte",
        "ts": "typescript",
        "tsx": "tsx",
        "vue": "vue",
        "xml": "xml",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(suffix, "")


def _is_source_text_file(path: Path) -> bool:
    return path.name in TEXT_FILENAMES or path.suffix.lower() in CODE_EXTS


def _looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return True
    return b"\x00" in chunk


def _safe_upload_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("\\", "/").lstrip("/")
    if ":" in raw:
        raw = raw.split(":", 1)[-1].lstrip("/")
    parts = [part for part in raw.split("/") if part and part not in (".", "..")]
    if not parts:
        return None
    return "/".join(parts)


def _is_source_text_name(name: str) -> bool:
    path = Path(name)
    return path.name in TEXT_FILENAMES or path.suffix.lower() in CODE_EXTS


class MaestroWebPanel:
    """Thread-safe orchestration state used by the local web API."""

    def __init__(self, project_dir: str | os.PathLike[str] | None = None) -> None:
        self.project_dir = resolve_project_dir(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / LOG_DIR).mkdir(parents=True, exist_ok=True)
        setup_logging(self.project_dir / LOG_DIR)
        ensure_chat_file(self.project_dir)

        self.lock = threading.RLock()
        self.proc_lock = threading.Lock()
        self.proc: subprocess.Popen[str] | None = None
        self.stop_event = threading.Event()
        self.decision_event = threading.Event()
        self.force_complete_event = threading.Event()
        self.force_fallback_event = threading.Event()
        self.decision: str | None = None

        self.running = False
        self.waiting_checkpoint = False
        self.status = "ready"
        self.status_detail = "Hazir"
        self.current_index: int | None = None
        self.run_id: str | None = None
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.server_host: str | None = None
        self.auth_enabled = False
        self.last_error = ""
        self.log_path: Path | None = None
        self.log_lines: deque[str] = deque(maxlen=1200)
        self.stage_durations: dict[int, float] = {}
        self.session_workflow_data: dict[str, Any] | None = None
        self.last_test_result: dict[str, Any] | None = None
        
        self.proc_started_at: float | None = None
        self.last_output_at: float | None = None
        self.current_stage_writes: list[str] = []
        self.preview_proc: subprocess.Popen[str] | None = None
        self.preview_url = ""
        self.preview_root: Path | None = None
        self.preview_log_path: Path | None = None

    # ---------- workflow/state ----------

    def active_workflow_data(self) -> dict[str, Any]:
        with self.lock:
            session = self.session_workflow_data
            running = self.running
        if session:
            try:
                session_hash = workflow_hash(session["stages"])
                state = load_state(self.project_dir)
                if running or state.get("workflow_hash") == session_hash:
                    return self._quality_enhanced_workflow_data(session)
            except Exception:
                pass
        data = load_generated_workflow(self.project_dir)
        if data:
            return self._quality_enhanced_workflow_data(data)
        return self._quality_enhanced_workflow_data({
            "summary": "Varsayilan Maestro ajan akisi",
            "project_type": "default",
            "stages": WF.STAGES,
        })

    def active_stages(self) -> list[dict[str, Any]]:
        return self.active_workflow_data()["stages"]

    def _quality_enhanced_workflow_data(self, data: dict[str, Any]) -> dict[str, Any]:
        project_type = str(data.get("project_type", ""))
        if project_type == "runtime" or project_type.startswith(("error-", "quality-")):
            return data
        enhanced = json.loads(json.dumps(data, ensure_ascii=False))
        stages = list(enhanced.get("stages", []))
        if not stages:
            return enhanced

        has_acceptance = any(ACCEPTANCE_FILE in stage.get("writes", []) for stage in stages)
        if not has_acceptance:
            first = stages[0]
            writes = list(first.get("writes", []))
            if ACCEPTANCE_FILE not in writes:
                writes.append(ACCEPTANCE_FILE)
            first["writes"] = writes
            first["prompt"] = (
                first.get("prompt", "")
                + f"\n\nKullanici istegini madde madde kabul kriterlerine cevir ve {ACCEPTANCE_FILE} dosyasina yaz."
            )

        insert_at = 1
        for idx, stage in enumerate(stages):
            haystack = f"{stage.get('name', '')} {stage.get('prompt', '')}".lower()
            if any(key in haystack for key in ("kod", "code", "implement", "bugfix", "duzelt", "düzelt")):
                insert_at = idx + 1
                break

        has_ui_polish = any("ui polish" in stage.get("name", "").lower() or "arayuz polish" in stage.get("name", "").lower() for stage in stages)
        ui_polish_ok = "desktop" not in project_type.lower() and "test-fix" not in project_type.lower()
        if ui_polish_ok and not has_ui_polish and len(stages) < 8:
            stages.insert(
                insert_at,
                {
                    "name": "UI Polish",
                    "agent": "gemini",
                    "prompt": (
                        f"{REQUEST_FILE}, tasarim.md, rapor.md ve {ACCEPTANCE_FILE} dosyalarini oku. "
                        "Sadece arayuz kalitesine odaklan: spacing, renk kontrasti, mobil gorunum, bos/tasan alan, "
                        "okunabilirlik ve hizli kullanilabilirlik sorunlarini duzelt. Kucuk CSS/layout/erisilebilirlik "
                        "duzeltmeleri yap; kapsam buyutme. Sonucu kontrol.md dosyasina yaz."
                    ),
                    "reads": [REQUEST_FILE, "tasarim.md", "rapor.md", ACCEPTANCE_FILE],
                    "writes": ["kontrol.md"],
                    "checkpoint": True,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
            )
            insert_at += 1

        has_test_generation = any("test uret" in stage.get("name", "").lower() or "test üret" in stage.get("name", "").lower() for stage in stages)
        if not has_test_generation and len(stages) < 8:
            stages.insert(
                insert_at,
                {
                    "name": "Test Uretimi",
                    "agent": "codex",
                    "prompt": (
                        f"{REQUEST_FILE}, plan.md, rapor.md ve {ACCEPTANCE_FILE} dosyalarini oku. "
                        "Kodlama bittigi icin ayri test ajani gibi davran: uygun unit/smoke/regression testlerini "
                        f"projeye ekle veya net test taslagini olustur. Sonucu {TEST_REPORT_FILE} dosyasina yaz."
                    ),
                    "reads": [REQUEST_FILE, "plan.md", "rapor.md", ACCEPTANCE_FILE],
                    "writes": [TEST_REPORT_FILE],
                    "checkpoint": True,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
            )

        has_acceptance_check = any(ACCEPTANCE_REPORT_FILE in stage.get("writes", []) for stage in stages)
        if not has_acceptance_check and len(stages) < 8:
            stages.append(
                {
                    "name": "Kabul Kontrolu",
                    "agent": "codex",
                    "prompt": (
                        f"{ACCEPTANCE_FILE}, rapor.md, kontrol.md ve {TEST_REPORT_FILE} dosyalarini oku. "
                        "Kabul kriterlerini tek tek dogrula: gecti/kontrol gerekli/eksik/test gecmedi durumlarini "
                        f"{ACCEPTANCE_REPORT_FILE} dosyasina yaz."
                    ),
                    "reads": [ACCEPTANCE_FILE, "rapor.md", "kontrol.md", TEST_REPORT_FILE],
                    "writes": [ACCEPTANCE_REPORT_FILE],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                }
            )

        enhanced["stages"] = stages
        return enhanced

    def save_request(self, text: str) -> None:
        save_user_request(self.project_dir, text)
        append_chat_entry(self.project_dir, "Kullanici", f"Web panel istegi kaydedildi:\n{text.strip() or '-'}")

    def source_meta_path(self) -> Path:
        path = self.project_dir / ".orkestra"
        path.mkdir(parents=True, exist_ok=True)
        return path / SOURCE_META_FILE

    def source_context_path(self) -> Path:
        return self.project_dir / SOURCE_CONTEXT_FILE

    def load_source_meta(self) -> dict[str, Any]:
        meta_path = self.source_meta_path()
        context_path = self.source_context_path()
        if not meta_path.exists():
            return {"enabled": context_path.exists(), "contextFile": SOURCE_CONTEXT_FILE}
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        raw["enabled"] = context_path.exists()
        raw["contextFile"] = SOURCE_CONTEXT_FILE
        if context_path.exists():
            raw["contextSize"] = context_path.stat().st_size
            raw["contextModified"] = datetime.fromtimestamp(context_path.stat().st_mtime).isoformat(timespec="seconds")
        return raw

    def clear_source_context(self) -> None:
        for path in (self.source_context_path(), self.source_meta_path()):
            if path.exists():
                path.unlink()
        append_chat_entry(self.project_dir, "Orkestra", "Kaynak proje/dosya context'i temizlendi.")

    def scan_source_path(self, raw_path: str) -> dict[str, Any]:
        raw = raw_path.strip().strip('"')
        if not raw:
            raise ValueError("Kaynak dosya veya klasor yolu bos olamaz.")
        source = Path(raw).expanduser().resolve()
        if not source.exists():
            raise ValueError(f"Kaynak yol bulunamadi: {source}")
        context, meta = self._build_source_context(source)
        context_path = self.source_context_path()
        context_path.write_text(context, encoding="utf-8")
        meta["context_file"] = SOURCE_CONTEXT_FILE
        meta["context_size"] = context_path.stat().st_size
        meta["context_hash"] = hashlib.sha256(context.encode("utf-8", errors="replace")).hexdigest()
        self.source_meta_path().write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        append_chat_entry(
            self.project_dir,
            "Orkestra",
            (
                "Kaynak proje/dosya tarandi ve context hazirlandi.\n"
                f"- Kaynak: {source}\n"
                f"- Context: {SOURCE_CONTEXT_FILE}\n"
                f"- Dahil edilen dosya: {meta['included_files']}/{meta['candidate_files']}"
            ),
        )
        return self.load_source_meta()

    def scan_uploaded_source(self, files: Any, label: str = "Secilen dosyalar") -> dict[str, Any]:
        if not isinstance(files, list) or not files:
            raise ValueError("Secilecek dosya bulunamadi.")
        context, meta = self._build_uploaded_source_context(files, label)
        context_path = self.source_context_path()
        context_path.write_text(context, encoding="utf-8")
        import_path = self._persist_uploaded_source_files(files, label)
        if import_path:
            meta["import_path"] = import_path
        meta["context_file"] = SOURCE_CONTEXT_FILE
        meta["context_size"] = context_path.stat().st_size
        meta["context_hash"] = hashlib.sha256(context.encode("utf-8", errors="replace")).hexdigest()
        self.source_meta_path().write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        append_chat_entry(
            self.project_dir,
            "Orkestra",
            (
                "Secilen dosya/klasor icerigi tarandi ve context hazirlandi.\n"
                f"- Kaynak: {label}\n"
                f"- Context: {SOURCE_CONTEXT_FILE}\n"
                f"- Dahil edilen dosya: {meta['included_files']}/{meta['candidate_files']}"
            ),
        )
        return self.load_source_meta()

    def source_tree_payload(self) -> dict[str, Any]:
        meta = self.load_source_meta()
        files = meta.get("files") if isinstance(meta, dict) else []
        if not isinstance(files, list):
            files = []
        return {
            "enabled": bool(meta.get("enabled")),
            "sourcePath": meta.get("source_path") or "",
            "sourceKind": meta.get("source_kind") or "",
            "rootPath": meta.get("root_path") or "",
            "importPath": meta.get("import_path") or "",
            "candidateFiles": meta.get("candidate_files") or 0,
            "includedFiles": meta.get("included_files") or 0,
            "skippedFiles": meta.get("skipped_files") or 0,
            "files": files[:MAX_SOURCE_TREE_FILES],
        }

    def orchestration_payload(self) -> dict[str, Any]:
        request_text = read_user_request(self.project_dir)
        context_path = self.project_dir / CONTEXT_SUMMARY_FILE
        context_meta: dict[str, Any] = {
            "exists": context_path.exists(),
            "name": CONTEXT_SUMMARY_FILE,
            "size": 0,
            "modified": "",
        }
        if context_path.exists():
            stat = context_path.stat()
            context_meta.update(
                {
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        return {
            "suggestedAgent": suggest_agent(request_text),
            "memory": load_project_memory(self.project_dir),
            "contextSummary": context_meta,
            "decisions": load_decisions(self.project_dir, limit=8),
        }

    def append_memory_note(self, note: str) -> dict[str, Any]:
        append_project_memory(self.project_dir, note)
        append_chat_entry(self.project_dir, "Orkestra", "Proje hafizasina yeni karar/tercih notu eklendi.")
        return self.orchestration_payload()

    def create_context_summary_payload(self) -> dict[str, Any]:
        out = build_context_summary(self.project_dir)
        append_chat_entry(self.project_dir, "Orkestra", f"Context sikistirici calisti: {CONTEXT_SUMMARY_FILE} hazir.")
        return {
            "ok": True,
            "summary": {
                "name": CONTEXT_SUMMARY_FILE,
                "size": out.stat().st_size,
                "modified": datetime.fromtimestamp(out.stat().st_mtime).isoformat(timespec="seconds"),
            },
            "orchestration": self.orchestration_payload(),
        }

    def suggest_agent_payload(self, text: str) -> dict[str, Any]:
        chosen = suggest_agent(text or read_user_request(self.project_dir))
        return {"ok": True, "agent": chosen}

    def compare_agents_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.running:
            raise RuntimeError("Akis calisirken ajan karsilastirma baslatilamaz.")
        prompt = str(payload.get("prompt") or read_user_request(self.project_dir)).strip()
        if not prompt:
            raise ValueError("Karsilastirma icin gorev metni bos olamaz.")
        raw_agents = payload.get("agents")
        agents = [str(item) for item in raw_agents] if isinstance(raw_agents, list) else None
        raw_writes = payload.get("writes")
        writes = [str(item) for item in raw_writes if str(item).strip()] if isinstance(raw_writes, list) else []
        timeout = int(payload.get("timeout") or 600)
        result = run_agent_comparison(
            self.project_dir,
            prompt,
            agents=agents,
            writes=writes,
            timeout=timeout,
            log=self._log,
        )
        report = Path(result["report"])
        return {
            "ok": True,
            "comparison": {
                "results": result["results"],
                "report": str(report.relative_to(self.project_dir)).replace("\\", "/"),
            },
            "status": self.status_payload(),
        }

    def copy_source_to_project(self) -> dict[str, Any]:
        meta = self.load_source_meta()
        if not meta.get("enabled"):
            raise ValueError("Kopyalanacak kaynak context yok.")
        existing_import = meta.get("import_path")
        if isinstance(existing_import, str) and existing_import:
            import_path = self.safe_file_path(existing_import)
            if import_path.exists():
                return {"ok": True, "importPath": existing_import, "copiedFiles": len(meta.get("files") or []), "alreadyCopied": True}

        root_value = meta.get("root_path") or meta.get("source_path")
        if not isinstance(root_value, str) or not root_value or root_value.startswith("Secilen "):
            raise ValueError("Bu kaynak tarayici upload'i; dosyalar zaten source_import altinda yoksa yeniden klasor sec.")

        source = Path(root_value).expanduser().resolve()
        if not source.exists():
            raise ValueError(f"Kaynak yol bulunamadi: {source}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.name or "source").strip("._") or "source"
        target_root = (self.project_dir / SOURCE_IMPORT_DIR / f"{stamp}_{safe_name}").resolve()
        target_root.relative_to(self.project_dir)
        target_root.mkdir(parents=True, exist_ok=False)

        copied = 0
        root = source if source.is_dir() else source.parent
        for path in self._source_candidates(source)[:MAX_COPY_FILES]:
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = Path(path.name)
            dest = (target_root / rel).resolve()
            try:
                dest.relative_to(target_root)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            copied += 1

        rel_import = str(target_root.relative_to(self.project_dir)).replace("\\", "/")
        meta["import_path"] = rel_import
        self.source_meta_path().write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        append_chat_entry(
            self.project_dir,
            "Orkestra",
            f"Kaynak proje project/{rel_import} altina kopyalandi. Kopyalanan dosya: {copied}",
        )
        return {"ok": True, "importPath": rel_import, "copiedFiles": copied, "alreadyCopied": False}

    def _persist_uploaded_source_files(self, files: list[Any], label: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("._") or "upload"
        target_root = (self.project_dir / SOURCE_IMPORT_DIR / f"{stamp}_{safe_label}").resolve()
        target_root.relative_to(self.project_dir)
        copied = 0
        for item in files[:MAX_UPLOADED_FILES]:
            if not isinstance(item, dict):
                continue
            name = _safe_upload_name(item.get("name") or item.get("path"))
            text = item.get("content")
            if not name or not _is_source_text_name(name) or not isinstance(text, str) or "\x00" in text:
                continue
            dest = (target_root / name).resolve()
            try:
                dest.relative_to(target_root)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text[:MAX_UPLOADED_FILE_CHARS], encoding="utf-8", errors="replace")
            copied += 1
        if not copied:
            return ""
        return str(target_root.relative_to(self.project_dir)).replace("\\", "/")

    def _build_uploaded_source_context(self, files: list[Any], label: str) -> tuple[str, dict[str, Any]]:
        included: list[dict[str, Any]] = []
        sections: list[str] = []
        tree_lines: list[str] = []
        skipped = 0
        total_chars = 0

        for item in files[:MAX_UPLOADED_FILES]:
            if not isinstance(item, dict):
                skipped += 1
                continue
            name = _safe_upload_name(item.get("name") or item.get("path"))
            if not name or not _is_source_text_name(name):
                skipped += 1
                continue
            text = item.get("content")
            if not isinstance(text, str):
                skipped += 1
                continue
            if "\x00" in text:
                skipped += 1
                continue
            if total_chars >= MAX_UPLOADED_TOTAL_CHARS:
                skipped += 1
                continue
            clipped = len(text) > MAX_UPLOADED_FILE_CHARS
            content = text[:MAX_UPLOADED_FILE_CHARS]
            total_chars += len(content)
            tree_lines.append(f"- {name}")
            included.append(
                {
                    "path": name,
                    "size": int(item.get("size") or len(text)),
                    "modified": item.get("modified") or "",
                    "clipped": clipped,
                }
            )
            lang = _lang_for(Path(name))
            clip_note = "\n\n[Not: dosya uzun oldugu icin ilk kisim alindi.]" if clipped else ""
            sections.append(
                f"## Dosya: {name}\n\n"
                f"- Boyut: {int(item.get('size') or len(text))} byte\n"
                f"- Degisim: {item.get('modified') or '-'}\n\n"
                f"```{lang}\n{content.rstrip()}{clip_note}\n```\n"
            )

        if not included:
            raise ValueError("Secilen dosyalarda okunabilir kod/metin dosyasi bulunamadi.")

        header = [
            "# Kaynak Proje/Dosya Context",
            "",
            "Bu dosya Maestro web panel tarafindan secilen dosyalardan otomatik uretildi.",
            "Ajanlar yeni is yapmadan once bu dosyayi okuyup mevcut proje/dosya yapisini anlamali.",
            "",
            "## Talimat",
            "",
            "- Kullanici yeni istegini uygularken bu kaynak context'ini mevcut is/proje zemini olarak kabul et.",
            "- Eski yapidaki isimleri, teknoloji secimlerini, dosya iliskilerini ve davranislari korumaya calis.",
            "- Gereksiz bastan yazma yapma; devam ettir, iyilestir, eksiklerini tamamla.",
            "- Eger kaynak eksik/kirpilmissa raporda bunu belirt.",
            "",
            "## Kaynak Ozeti",
            "",
            "- Kaynak turu: tarayicidan secilen dosya/klasor",
            f"- Kaynak etiketi: {label}",
            f"- Tarama zamani: {now_stamp()}",
            f"- Aday dosya: {len(files)}",
            f"- Dahil edilen dosya: {len(included)}",
            f"- Atlanan/limit disi: {skipped}",
            "",
            "## Dosya Haritasi",
            "",
            *tree_lines[:MAX_SOURCE_TREE_FILES],
            "",
            "## Icerik Ornekleri",
            "",
        ]
        context = "\n".join(header) + "\n".join(sections)
        meta = {
            "source_path": label,
            "source_kind": "upload",
            "root_path": label,
            "scanned_at": now_stamp(),
            "candidate_files": len(files),
            "included_files": len(included),
            "skipped_files": skipped,
            "included_bytes": total_chars,
            "files": included,
        }
        return context, meta

    def _build_source_context(self, source: Path) -> tuple[str, dict[str, Any]]:
        root = source if source.is_dir() else source.parent
        candidates = self._source_candidates(source)
        if not candidates:
            raise ValueError("Kaynakta okunabilir kod/metin dosyasi bulunamadi.")
        included: list[dict[str, Any]] = []
        skipped = 0
        total_bytes = 0
        sections: list[str] = []

        for path in candidates:
            if len(included) >= MAX_SOURCE_FILES or total_bytes >= MAX_SOURCE_TOTAL_BYTES:
                skipped += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                skipped += 1
                continue
            if stat.st_size <= 0 or _looks_binary(path):
                skipped += 1
                continue
            try:
                raw_bytes = path.read_bytes()[:MAX_SOURCE_FILE_BYTES]
                text = raw_bytes.decode("utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            clipped = stat.st_size > MAX_SOURCE_FILE_BYTES
            total_bytes += len(raw_bytes)
            included.append(
                {
                    "path": rel,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "clipped": clipped,
                }
            )
            lang = _lang_for(path)
            clip_note = "\n\n[Not: dosya uzun oldugu icin ilk kisim alindi.]" if clipped else ""
            sections.append(
                f"## Dosya: {rel}\n\n"
                f"- Boyut: {stat.st_size} byte\n"
                f"- Degisim: {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}\n\n"
                f"```{lang}\n{text.rstrip()}{clip_note}\n```\n"
            )

        tree_lines = []
        for path in candidates[:MAX_SOURCE_TREE_FILES]:
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = path.name
            tree_lines.append(f"- {rel}")

        source_kind = "klasor" if source.is_dir() else "dosya"
        header = [
            "# Kaynak Proje/Dosya Context",
            "",
            "Bu dosya Maestro web panel tarafindan otomatik uretildi.",
            "Ajanlar yeni is yapmadan once bu dosyayi okuyup mevcut proje/dosya yapisini anlamali.",
            "",
            "## Talimat",
            "",
            "- Kullanici yeni istegini uygularken bu kaynak context'ini mevcut is/proje zemini olarak kabul et.",
            "- Eski yapidaki isimleri, teknoloji secimlerini, dosya iliskilerini ve davranislari korumaya calis.",
            "- Gereksiz bastan yazma yapma; devam ettir, iyilestir, eksiklerini tamamla.",
            "- Eger kaynak eksik/kirpilmissa raporda bunu belirt.",
            "",
            "## Kaynak Ozeti",
            "",
            f"- Kaynak turu: {source_kind}",
            f"- Kaynak yol: {source}",
            f"- Tarama zamani: {now_stamp()}",
            f"- Aday dosya: {len(candidates)}",
            f"- Dahil edilen dosya: {len(included)}",
            f"- Atlanan/limit disi: {skipped}",
            "",
            "## Dosya Haritasi",
            "",
            *tree_lines,
            "",
            "## Icerik Ornekleri",
            "",
        ]
        context = "\n".join(header) + "\n".join(sections)
        meta = {
            "source_path": str(source),
            "source_kind": source_kind,
            "root_path": str(root),
            "scanned_at": now_stamp(),
            "candidate_files": len(candidates),
            "included_files": len(included),
            "skipped_files": skipped,
            "included_bytes": total_bytes,
            "files": included,
        }
        return context, meta

    def _source_candidates(self, source: Path) -> list[Path]:
        if source.is_file():
            return [source] if _is_source_text_file(source) else []
        rows: list[Path] = []
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel_parts = path.relative_to(source).parts
            except ValueError:
                rel_parts = path.parts
            if any(part in SKIP_DIRS or part.startswith(".git") for part in rel_parts[:-1]):
                continue
            if not _is_source_text_file(path):
                continue
            rows.append(path)
        rows.sort(key=lambda item: (0 if item.name in ("README.md", "package.json", "pyproject.toml", "requirements.txt") else 1, str(item).lower()))
        return rows

    def reset_progress(self) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("Akis calisirken ilerleme sifirlanamaz.")
            state_file = self.project_dir / STATE_FILE
            if state_file.exists():
                state_file.unlink()
            self.current_index = None
            self.stage_durations.clear()
            self.status = "ready"
            self.status_detail = "Ilerleme sifirlandi"
            self.last_error = ""
            self._log("Ilerleme sifirlandi.")

    def tool_status(self) -> dict[str, bool]:
        return {tool: bool(find_tool(tool)) for tool in ("codex", "gemini", "claude")}

    # ---------- run control ----------

    def start_run(
        self,
        *,
        start_idx: int = 1,
        reset_state: bool = False,
        use_checkpoints: bool = True,
        stages: list[dict[str, Any]] | None = None,
    ) -> None:
        active_stages = self._stages_with_source_context(stages or self.active_stages())
        validate_workflow(active_stages)
        total = len(active_stages)
        if start_idx < 1 or start_idx > total:
            raise ValueError(f"Baslangic adimi 1 ile {total} arasinda olmali.")
        if workflow_uses_request(active_stages) and not read_user_request(self.project_dir):
            raise ValueError(f"{REQUEST_FILE} bos. Once is istegini kaydet.")

        missing = missing_required_tools(active_stages[start_idx - 1 :])
        if missing:
            raise RuntimeError(
                "Eksik ajan komutlari: "
                + ", ".join(missing)
                + ". Beklenenler: "
                + expected_agent_commands_label()
            )

        with self.lock:
            if self.running:
                raise RuntimeError("Akis zaten calisiyor.")
            if reset_state or start_idx == 1:
                state_file = self.project_dir / STATE_FILE
                if state_file.exists():
                    state_file.unlink()
            self.run_id = f"web_{datetime.now():%Y%m%d_%H%M%S}"
            self.started_at = now_stamp()
            self.finished_at = None
            self.log_path = self.project_dir / LOG_DIR / f"{self.run_id}.log"
            self.log_lines.clear()
            self.stop_event.clear()
            self.decision_event.clear()
            self.force_complete_event.clear()
            self.force_fallback_event.clear()
            self.decision = None
            self.running = True
            self.waiting_checkpoint = False
            self.status = "running"
            self.status_detail = "Akis basladi"
            self.current_index = start_idx
            self.last_error = ""
            self.stage_durations.clear()
            self.proc_started_at = None
            self.last_output_at = None
            self.current_stage_writes = []
            self.session_workflow_data = {
                "summary": "Calisan Maestro akisi",
                "project_type": "runtime",
                "brief_hash": "",
                "stages": active_stages,
            }
            self._log(f"Akis basladi. Baslangic adimi: {start_idx}")
            append_event(self.project_dir, "run_started", run_id=self.run_id, start_idx=start_idx, stages=len(active_stages))

        self.worker = threading.Thread(
            target=self._run_pipeline,
            args=(start_idx, use_checkpoints, active_stages),
            daemon=True,
        )
        self.worker.start()

    def _stages_with_source_context(self, stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.source_context_path().exists():
            return stages
        enhanced: list[dict[str, Any]] = []
        prefix = (
            f"{SOURCE_CONTEXT_FILE} dosyasini once oku. Bu dosya kullanicinin onceki proje/dosya "
            "kaynaklarini ozetler. Yeni isi bu mevcut kaynagi anlayarak devam ettir; gereksiz bastan "
            "yazma yapma, mevcut yapinin ustune kaliteli iyilestirme yap.\n\n"
        )
        for stage in stages:
            copy = dict(stage)
            reads = list(copy.get("reads", []))
            if SOURCE_CONTEXT_FILE not in reads:
                reads.insert(0, SOURCE_CONTEXT_FILE)
            copy["reads"] = reads
            if SOURCE_CONTEXT_FILE not in copy.get("prompt", ""):
                copy["prompt"] = prefix + copy["prompt"]
            enhanced.append(copy)
        return enhanced

    def stop_run(self) -> None:
        with self.lock:
            if not self.running:
                self.status_detail = "Calisan akis yok"
                return
            self.status_detail = "Durdurma istegi gonderildi"
            self._log("Durdurma istegi alindi.")
        self.stop_event.set()
        self.decision = "stop"
        self.decision_event.set()
        with self.proc_lock:
            proc = self.proc
        kill_process_tree(proc)

    def send_decision(self, decision: str) -> None:
        if decision not in {"continue", "retry", "stop"}:
            raise ValueError("Karar continue, retry veya stop olmali.")
        with self.lock:
            if not self.waiting_checkpoint:
                raise RuntimeError("Checkpoint karari beklenmiyor.")
            self.decision = decision
            self.status_detail = f"Checkpoint karari: {decision}"
            self._log(f"Checkpoint karari: {decision}")
        self.decision_event.set()

    def _run_pipeline(self, start_idx: int, use_checkpoints: bool, stages: list[dict[str, Any]]) -> None:
        total = len(stages)
        current_hash = workflow_hash(stages)
        state = load_state(self.project_dir)
        if state.get("workflow_hash") != current_hash:
            state["completed"] = []
            state["workflow_hash"] = current_hash

        i = start_idx
        stopped = False
        try:
            while i <= total and not self.stop_event.is_set():
                stage = stages[i - 1]
                with self.lock:
                    self.current_index = i
                    self.waiting_checkpoint = False
                    self.status = "running"
                    self.status_detail = f"{i}/{total}: {stage['name']}"
                self._run_stage_start_notice(stage, i, total, stages)

                missing_inputs = check_inputs(self.project_dir, stage)
                if missing_inputs:
                    reason = "Eksik girdiler: " + ", ".join(missing_inputs)
                    self._fail_stage(stage, i, reason)
                    break

                try:
                    meta = create_snapshot(self.project_dir, self.run_id or "web", i, stage)
                    self._log(f"Snapshot alindi: {meta.get('id')}")
                except Exception as exc:
                    self._log(f"Snapshot alinamadi: {exc}")

                active_stage = stage
                fallback_used = False
                ok, elapsed, reason, output = self._run_one(stage, i, total, stages)
                fallback = fallback_agent_for(stage, output)
                if not ok and reason == "exit" and fallback and find_tool(fallback):
                    fallback_used = True
                    self._log(f"{stage['agent']} hata verdi; {fallback} devraliyor.")
                    append_chat_entry(
                        self.project_dir,
                        "Orkestra",
                        f"{stage_ref(stage, i)} {stage['agent']} ile tamamlanamadi. Ayni gorev {fallback} ajanina devrediliyor.",
                    )
                    active_stage = with_fallback_agent(stage, fallback)
                    ok, elapsed, reason, output = self._run_one(active_stage, i, total, stages)

                if self.stop_event.is_set() or reason == "stopped":
                    stopped = True
                    self._record_metric(active_stage, i, "stopped", elapsed, "stopped", fallback_used)
                    append_chat_entry(self.project_dir, "Orkestra", f"{stage_ref(active_stage, i)} web panelden durduruldu.")
                    break

                if not ok:
                    self._record_metric(active_stage, i, "failed", elapsed, reason, fallback_used)
                    self._fail_stage(active_stage, i, reason)
                    break

                missing_outputs = verify_outputs(self.project_dir, stage)
                if missing_outputs:
                    reason = "Eksik ciktilar: " + ", ".join(missing_outputs)
                    self._record_metric(active_stage, i, "failed", elapsed, reason, fallback_used)
                    self._fail_stage(active_stage, i, reason)
                    break

                produced = ", ".join(stage.get("writes", [])) or "-"
                self._log(f"Adim tamamlandi ({fmt_seconds(elapsed)}). Ciktilar: {produced}")
                append_chat_entry(
                    self.project_dir,
                    active_stage["agent"].upper(),
                    (
                        f"{stage_ref(active_stage, i)} tamamlandi.\n"
                        f"- Sure: {fmt_seconds(elapsed)}\n"
                        f"- Uretilen/beklenen ciktilar: {produced}\n"
                        f"- Siradaki: {next_stage_ref(stages, i)}"
                    ),
                )
                if i not in state["completed"]:
                    state["completed"].append(i)
                state["workflow_hash"] = current_hash
                save_state(self.project_dir, state)
                self.stage_durations[i] = elapsed

                # --- FAZ 7: OTOMATIK SMOKE TEST ---
                # Test, metrik/kalite skorundan ONCE kosar ki skor gercek test
                # sonucunu gorsun (last_test_result -> score_stage_quality).
                test_cmd = (
                    stage.get("test_command")
                    or self.session_workflow_data.get("test_command")
                    or self._default_test_command(stage)
                )
                test_failed = False
                self.last_test_result = None
                if test_cmd:
                    self._log(f"Otomatik smoke test calistiriliyor: {test_cmd}")
                    test_result = self._run_check("smoke_test", test_cmd.split(), cwd=self.project_dir, timeout=60)
                    self.last_test_result = test_result
                    if test_result["status"] == "failed":
                        test_failed = True
                        self._log(f"Test basarisiz. Hata:\n{test_result['output']}")
                        append_event(self.project_dir, "test_failed", idx=i, command=str(test_cmd), output_tail=str(test_result.get("output", ""))[-500:])
                        self._record_metric(active_stage, i, "failed", elapsed, "test-hatasi: otomatik smoke", fallback_used)
                        # Kayip-uyandirma yarisina karsi: event, bayrak gorunur
                        # olmadan ONCE temizlenir; dongu decision'i da yoklar.
                        self.decision_event.clear()
                        with self.lock:
                            self.decision = None
                            self.waiting_checkpoint = True
                            self.status = "waiting"
                            self.status_detail = f"{i}. adim testi basarisiz; karar bekleniyor"
                        self._log("Test hatasi! Devam, tekrar (hata prompt'a eklenecek), veya durdur karari bekleniyor.")

                        while not self.decision_event.wait(0.2):
                            if self.stop_event.is_set():
                                break
                            with self.lock:
                                if self.decision is not None:
                                    break
                        with self.lock:
                            decision = self.decision or "stop"
                            self.decision = None
                            self.waiting_checkpoint = False

                        if decision == "stop" or self.stop_event.is_set():
                            stopped = True
                            break
                        if decision == "retry":
                            stage["prompt"] += f"\n\n[Oto-Test Hatasi]\nOnceki denemede test asagidaki hatayi verdi. Lutfen duzelt:\n{test_result['output']}"
                            state["completed"] = [x for x in state.get("completed", []) if x != i]
                            save_state(self.project_dir, state)
                            self.stage_durations.pop(i, None)
                            self._log(f"{i}. adim test hatasiyla tekrar calisacak.")
                            continue

                self._record_metric(active_stage, i, "success", elapsed, "", fallback_used)
                record_stage_decision(
                    self.project_dir, self.run_id, i, active_stage,
                    produced_files(self.project_dir, [active_stage]),
                    extract_last_handoff(self.project_dir, active_stage.get("agent", "")),
                )

                if use_checkpoints and stage.get("checkpoint") and i < total and not test_failed:
                    # Kayip-uyandirma yarisina karsi (bkz. test-hatasi bloklari).
                    self.decision_event.clear()
                    with self.lock:
                        self.decision = None
                        self.waiting_checkpoint = True
                        self.status = "waiting"
                        self.status_detail = f"{i}. adim bitti; karar bekleniyor"
                    self._log("Checkpoint: devam, tekrar veya durdur karari bekleniyor.")
                    while not self.decision_event.wait(0.2):
                        if self.stop_event.is_set():
                            break
                        with self.lock:
                            if self.decision is not None:
                                break
                    with self.lock:
                        decision = self.decision or "stop"
                        self.decision = None
                        self.waiting_checkpoint = False
                    if decision == "stop" or self.stop_event.is_set():
                        stopped = True
                        break
                    if decision == "retry":
                        state["completed"] = [x for x in state.get("completed", []) if x != i]
                        save_state(self.project_dir, state)
                        self.stage_durations.pop(i, None)
                        self._log(f"{i}. adim tekrar calisacak.")
                        continue

                i += 1

            with self.lock:
                self.finished_at = now_stamp()
                self.running = False
                self.waiting_checkpoint = False
                if i > total and not self.stop_event.is_set():
                    self.status = "complete"
                    self.status_detail = "Tum akis tamamlandi"
                    self.current_index = None
                    self._log("Tum akis tamamlandi.")
                    append_event(self.project_dir, "run_finished", run_id=self.run_id, status="complete")
                elif stopped:
                    self.status = "stopped"
                    self.status_detail = "Akis durduruldu"
                    self._log("Akis durduruldu.")
                elif self.status != "failed":
                    self.status = "idle"
                    self.status_detail = "Akis durdu"
        except Exception as exc:
            with self.lock:
                self.finished_at = now_stamp()
                self.running = False
                self.waiting_checkpoint = False
                self.status = "failed"
                self.status_detail = "Beklenmeyen hata"
                self.last_error = str(exc)
            self._log(f"Beklenmeyen hata: {exc}")
        finally:
            with self.proc_lock:
                self.proc = None

    def _run_stage_start_notice(self, stage: dict[str, Any], idx: int, total: int, stages: list[dict[str, Any]]) -> None:
        self._log("")
        self._log(f"=== ADIM {idx}/{total}: {stage['name']} [{stage['agent']}] ===")
        append_chat_entry(
            self.project_dir,
            "Orkestra",
            (
                f"Sira {idx}/{total}: {stage_ref(stage, idx)} basliyor.\n"
                f"- Gorev: {stage['prompt'][:220]}{'...' if len(stage['prompt']) > 220 else ''}\n"
                f"- Sonraki: {next_stage_ref(stages, idx)}"
            ),
        )

    def _run_one(
        self,
        stage: dict[str, Any],
        idx: int,
        total: int,
        stages: list[dict[str, Any]],
    ) -> tuple[bool, float, str, str]:
        # Surec kosturma mantigi runner.run_agent_stage'de (gui.py ile ortak kaynak).
        with self.lock:
            self.proc_started_at = time.time()
            self.last_output_at = time.time()
            self.current_stage_writes = stage.get("writes", [])

        # Checkpoint/adimlar arasi birikmis "tamamlandi say"/"fallback" sinyalleri
        # YENI adimin surecini aninda oldurmesin; her adim temiz baslar.
        self.force_complete_event.clear()
        self.force_fallback_event.clear()

        current: list[Any] = [None]

        def register_proc(p: Any) -> None:
            with self.proc_lock:
                if p is None:
                    if self.proc is current[0]:
                        self.proc = None
                else:
                    current[0] = p
                    self.proc = p

        def mark_activity() -> None:
            with self.lock:
                self.last_output_at = time.time()

        return run_agent_stage(
            stage,
            idx,
            total,
            stages,
            self.project_dir,
            stop_event=self.stop_event,
            log=self._log,
            force_complete_event=self.force_complete_event,
            force_fallback_event=self.force_fallback_event,
            on_proc=register_proc,
            on_activity=mark_activity,
        )

                

    def _default_test_command(self, stage: dict[str, Any]) -> str | None:
        """Kodlama/duzeltme adimlarindan sonra sifir maliyetli varsayilan smoke.

        test_command tanimli degilse ve projede .py dosyasi varsa, soz dizimi
        derlemesi (compileall) kosulur. Token harcamaz; sadece dosya sistemi.
        """
        haystack = f"{stage.get('name', '')} {stage.get('prompt', '')}".lower()
        if not any(key in haystack for key in ("kod", "code", "duzelt", "düzelt", "fix", "implement")):
            return None
        if next(Path(self.project_dir).rglob("*.py"), None) is None:
            return None
        return "python -m compileall -q -x (node_modules|venv|\\.git|__pycache__) ."

    def _fail_stage(self, stage: dict[str, Any], idx: int, reason: str) -> None:
        with self.lock:
            self.status = "failed"
            self.status_detail = f"{idx}. adim basarisiz"
            self.current_index = idx
            self.last_error = reason
        self._log(f"Hata: {reason}")
        append_event(self.project_dir, "run_finished", run_id=self.run_id, status="failed", error=str(reason), stage=idx)
        append_chat_entry(self.project_dir, stage.get("agent", "Orkestra").upper(), f"{stage_ref(stage, idx)} basarisiz oldu. Sebep: {reason}")

    def _record_metric(self, stage: dict[str, Any], idx: int, status: str, elapsed: float, reason: str, fallback_used: bool = False) -> None:
        entry = {
            "stage_index": idx,
            "stage_name": stage.get("name", f"Adim {idx}"),
            "agent": stage.get("agent", "bilinmiyor"),
            "status": status,
            "elapsed": round(elapsed, 3),
            "reason": reason,
            "fallback_used": fallback_used,
            "run_id": self.run_id,
        }
        append_metric(self.project_dir, entry)
        if status == "success":
            # Faz 6: Ajan Kalite Skoru hesapla
            score_stage_quality(self.project_dir, stage, idx, self._recent_log_text(), getattr(self, "last_test_result", None))

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}" if message else ""
        with self.lock:
            self.log_lines.append(line)
            path = self.log_path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(line + "\n")

    def task_monitor_payload(self) -> dict[str, Any]:
        with self.lock:
            running = self.running
            stage_idx = self.current_index
            started_at = self.proc_started_at
            last_out = self.last_output_at
            active_stage = None
            
            if running and stage_idx and self.session_workflow_data:
                stages = self.session_workflow_data.get("stages", [])
                if 1 <= stage_idx <= len(stages):
                    active_stage = stages[stage_idx - 1]

        with self.proc_lock:
            pid = self.proc.pid if self.proc else None

        if not running or not active_stage:
            return {"active": False}

        from orkestra import stage_output_status, process_info
        out_status = stage_output_status(self.project_dir, active_stage)
        pinfo = process_info(pid) if pid else {}
        
        now = time.time()
        elapsed = (now - started_at) if started_at else 0
        silent_for = (now - last_out) if last_out else 0

        from orkestra import AGENT_STUCK_POLICIES
        agent_name = active_stage.get("agent", "default").lower()
        policy = AGENT_STUCK_POLICIES.get(agent_name, AGENT_STUCK_POLICIES["default"])

        probable_status = "normal"
        if not out_status["missing"] and out_status["expected"]:
            probable_status = "cikti uretti"
        elif silent_for > policy["silent_warn"]:
            probable_status = "sessiz"
            if silent_for > policy["silent_stuck"]:
                probable_status = "takildi"

        last_file_mtime = None
        for f in out_status["produced"]:
            try:
                mtime = (self.project_dir / f).stat().st_mtime
                if not last_file_mtime or mtime > last_file_mtime:
                    last_file_mtime = mtime
            except OSError:
                pass

        return {
            "active": True,
            "agent": active_stage.get("agent", ""),
            "pid": pid,
            "elapsed": round(elapsed, 1),
            "silent_for": round(silent_for, 1),
            "last_file_mtime": datetime.fromtimestamp(last_file_mtime).isoformat(timespec="seconds") if last_file_mtime else None,
            "expected_outputs": out_status["expected"],
            "missing_outputs": out_status["missing"],
            "produced_outputs": out_status["produced"],
            "cpu_percent": pinfo.get("cpu_percent", 0.0),
            "memory_mb": pinfo.get("memory_mb", 0.0),
            "probable_status": probable_status
        }

    def state_repair_payload(self) -> dict[str, Any]:
        from orkestra import repair_state_from_outputs, WF
        with self.lock:
            state = repair_state_from_outputs(self.project_dir, WF.STAGES)
            self._log(f"Ilerleme dosyalardan toparlandi. Tamamlanan adimlar: {state.get('completed', [])}")
            return {"ok": True, "state": state}

    # ---------- API payload helpers ----------

    def stop_all_processes(self) -> None:
        self.stop_run()
        def harakiri():
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=harakiri, daemon=True).start()

    def processes_payload(self) -> dict[str, Any]:
        processes = []
        if sys.platform == "win32":
            try:
                out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], encoding="utf-8", errors="replace")
                import csv
                for row in csv.reader(out.splitlines()):
                    if len(row) >= 2:
                        name, pid_str = row[0], row[1]
                        lower_name = name.lower()
                        if lower_name in ("python.exe", "python3.exe", "node.exe", "cmd.exe", "conhost.exe") or "maestro" in lower_name or "claude" in lower_name or "gemini" in lower_name:
                            try:
                                processes.append({"pid": int(pid_str), "name": name})
                            except ValueError:
                                pass
            except Exception:
                pass
        else:
            try:
                out = subprocess.check_output(["ps", "-eo", "pid,comm"], encoding="utf-8", errors="replace")
                for line in out.splitlines()[1:]:
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        pid_str, name = parts
                        lower_name = name.lower()
                        if lower_name in ("python", "python3", "node", "sh", "bash") or "maestro" in lower_name or "claude" in lower_name or "gemini" in lower_name:
                            try:
                                processes.append({"pid": int(pid_str), "name": name})
                            except ValueError:
                                pass
            except Exception:
                pass

        return {
            "serverPid": os.getpid(),
            "activeAgentPid": getattr(self, "proc", None).pid if getattr(self, "proc", None) else None,
            "activePort": getattr(self, "server_port", None),
            "systemProcesses": processes,
        }

    def status_payload(self) -> dict[str, Any]:
        workflow_data = self.active_workflow_data()
        stages = self._stages_with_source_context(workflow_data["stages"])
        current_hash = workflow_hash(stages)
        state = load_state(self.project_dir)
        completed = set(state.get("completed", [])) if state.get("workflow_hash") == current_hash else set()
        total = len(stages)
        progress = int((len(completed) / total) * 100) if total else 0
        with self.proc_lock:
            proc_ref = self.proc
            active_pid = proc_ref.pid if proc_ref else None
        with self.lock:
            payload = {
                "projectDir": str(self.project_dir),
                "request": read_user_request(self.project_dir),
                "tools": self.tool_status(),
                "geminiBackend": gemini_backend(),
                "agentCommands": expected_agent_commands_label(),
                "status": self.status,
                "statusDetail": self.status_detail,
                "running": self.running,
                "waitingCheckpoint": self.waiting_checkpoint,
                "currentIndex": self.current_index,
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
                "lastError": self.last_error,
                "runId": self.run_id,
                "logPath": str(self.log_path) if self.log_path else "",
                "logs": list(self.log_lines),
                "stageDurations": {str(k): fmt_seconds(v) for k, v in self.stage_durations.items()},
                "activePort": getattr(self, "server_port", None),
                "serverPid": os.getpid(),
                "activeAgentPid": active_pid,
            }
        payload.update(
            {
                "workflow": {
                    "summary": workflow_data.get("summary", ""),
                    "projectType": workflow_data.get("project_type", ""),
                    "stages": [
                        _stage_public(stage, idx, completed, payload["currentIndex"])
                        for idx, stage in enumerate(stages, 1)
                    ],
                },
                "state": {
                    "completed": sorted(completed),
                    "total": total,
                    "progress": progress,
                    "workflowHashMatches": state.get("workflow_hash") == current_hash,
                    "lastRun": state.get("last_run"),
                },
                "files": self.file_list(),
                "chat": read_chat_tail(self.project_dir, limit=12000),
                "metrics": self.metric_summary(),
                "snapshots": self.snapshot_list(limit=10),
                "source": self.load_source_meta(),
                "sourceTree": self.source_tree_payload(),
                "orchestration": self.orchestration_payload(),
                "diagnostics": self.diagnostics_payload(),
                "workflowTemplates": self.workflow_templates_payload(),
                "resultQuality": self._result_quality_payload(stages, payload["status"], payload["lastError"]),
                "projectQuality": self.quality_summary_payload(),
                "webApp": self.webapp_summary_payload(),
            }
        )
        return payload

    def file_list(self) -> list[dict[str, Any]]:
        names: set[str] = set(OUTPUT_FILES)
        try:
            for stage in self.active_stages():
                names.update(str(item) for item in stage.get("reads", []))
                names.update(str(item) for item in stage.get("writes", []))
        except Exception:
            pass
        for path in self._iter_code_files(limit=120):
            names.add(str(path.relative_to(self.project_dir)).replace("\\", "/"))

        rows = []
        for name in sorted(names):
            path = self.safe_file_path(name)
            exists = path.exists()
            stat = path.stat() if exists else None
            rows.append(
                {
                    "name": name,
                    "exists": exists,
                    "size": stat.st_size if stat else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else "",
                }
            )
        return rows

    def read_file(self, name: str, limit: int = 200_000) -> dict[str, Any]:
        path = self.safe_file_path(name)
        if not path.exists():
            return {"name": name, "exists": False, "content": f"{name} henuz olusmadi.\n"}
        if not path.is_file():
            raise ValueError("Sadece dosyalar okunabilir.")
        text = path.read_text(encoding="utf-8", errors="replace")
        clipped = len(text) > limit
        return {
            "name": name,
            "exists": True,
            "content": text[:limit] + ("\n\n... dosya kirpildi ..." if clipped else ""),
            "clipped": clipped,
        }

    def safe_file_path(self, name: str) -> Path:
        raw = unquote(name or "").replace("\\", "/").strip("/")
        if not raw or raw.startswith("/") or ":" in raw:
            raise ValueError("Gecersiz dosya yolu.")
        path = (self.project_dir / raw).resolve()
        try:
            path.relative_to(self.project_dir)
        except ValueError as exc:
            raise ValueError("Dosya proje disina cikamaz.") from exc
        return path

    def metric_summary(self) -> dict[str, Any]:
        rows = load_metrics(self.project_dir)
        total = len(rows)
        success = sum(1 for row in rows if row.get("status") == "success")
        failed = sum(1 for row in rows if row.get("status") == "failed")
        elapsed = sum(float(row.get("elapsed") or 0) for row in rows)
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "elapsed": fmt_seconds(elapsed),
            "recent": rows[-8:],
            "qualityScores": load_quality_scores(self.project_dir)[-5:],
        }

    def suggested_start_index(self) -> int:
        workflow_data = self.active_workflow_data()
        stages = self._stages_with_source_context(workflow_data["stages"])
        total = len(stages)
        current_hash = workflow_hash(stages)
        state = load_state(self.project_dir)
        completed = state.get("completed", []) if state.get("workflow_hash") == current_hash else []
        completed = [idx for idx in completed if isinstance(idx, int)]
        if self.status in {"failed", "stopped"} and self.current_index:
            return max(1, min(int(self.current_index), total or 1))
        if completed:
            return max(1, min(max(completed) + 1, total or 1))
        return 1

    def diagnostics_payload(self) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        log_text = self._recent_log_text().lower()
        files = {row["name"]: row for row in self.file_list()}

        def add(severity: str, title: str, detail: str, action: str = "") -> None:
            issues.append({"severity": severity, "title": title, "detail": detail, "action": action})

        if ("resource_exhausted" in log_text or "monthly spending cap" in log_text) and gemini_backend() != "antigravity":
            add(
                "error",
                "Gemini kotasi dolmus",
                "Son loglarda Gemini 429 RESOURCE_EXHAUSTED / monthly spending cap hatasi var.",
                "Gemini backend'i Antigravity CLI yap veya Claude/Codex fallback kullan.",
            )
        if "web panelden durduruldu" in log_text or self.status == "stopped":
            add(
                "warn",
                "Ajan adimi durdurulmus",
                "Son akista bir adim panelden durdurulmus. Uretilen proje yarim kalmis olabilir.",
                f"Baslangic adimini {self.suggested_start_index()} secip Devam Et.",
            )
        if "not recognized as an internal or external command" in log_text:
            add(
                "error",
                "CLI komut yolu bozulmus",
                "Bir ajan komutu Windows tarafinda calistirilamamis.",
                "Arac durumlarini kontrol et; Maestro bozuk FNM shim'lerini atlayacak sekilde guncellendi.",
            )
        if "error executing tool write_file" in log_text:
            add(
                "warn",
                "Ajan arac cagrisi hatasi",
                "Bir ajan write_file aracini hatali parametreyle cagirmis; genelde retry veya fallback ile asil is devam edebilir.",
                "Logda ayni satir tekrar ediyorsa ilgili adimi tekrar calistir.",
            )

        for name in ("rapor.md", "kontrol.md"):
            if name in files and not files[name]["exists"]:
                add("warn", f"{name} henuz yok", "Workflow bu ciktiyi bekliyor ama dosya olusmamis.", "Ilgili adimdan devam et.")

        mp3_root = self.project_dir / "MP3INDIRICI"
        if mp3_root.exists():
            missing = [name for name in ("main.py", "README.md", "requirements.txt", "run.bat") if not (mp3_root / name).exists()]
            if missing:
                add(
                    "warn",
                    "MP3 uygulamasi iskelet halinde",
                    "MP3INDIRICI klasoru var ama temel calistirma dosyalari eksik: " + ", ".join(missing),
                    "Kodlama adimini tamamla veya yerel tamamlama uygula.",
                )

        source = self.load_source_meta()
        if source.get("enabled") and not source.get("import_path"):
            add(
                "info",
                "Kaynak sadece context olarak duruyor",
                "Ajanlar kaynak_context.md okuyabilir; fiziksel kopya istersen kaynak project/source_import altina alinabilir.",
                "Kaynak sekmesinden Kopyala.",
            )

        tools = self.tool_status()
        missing_tools = [name for name, ok in tools.items() if not ok]
        if missing_tools:
            add("error", "Eksik ajan araci", "PATH icinde bulunamayan araclar: " + ", ".join(missing_tools), "CLI kurulumlarini kontrol et.")

        if not issues:
            add("success", "Kritik sorun yok", "Panel hazir; kaynak ve workflow secimine gore akis baslatilabilir.", "")

        return {
            "issues": issues,
            "suggestedStartIndex": self.suggested_start_index(),
            "latestLogPath": str(self.log_path or self._latest_log_path() or ""),
        }

    def workflow_templates_payload(self) -> dict[str, Any]:
        current = self.active_workflow_data()
        current_type = current.get("project_type", "")
        return {
            "currentType": current_type,
            "templates": [
                {
                    "id": key,
                    "label": value["label"],
                    "description": value["description"],
                    "stageCount": len(value["data"]["stages"]),
                    "active": current_type == value["data"].get("project_type"),
                }
                for key, value in WORKFLOW_TEMPLATES.items()
            ],
        }

    def _reset_ready_state(self, detail: str) -> None:
        state_file = self.project_dir / STATE_FILE
        if state_file.exists():
            state_file.unlink()
        with self.lock:
            self.session_workflow_data = None
            self.current_index = None
            self.stage_durations.clear()
            self.status = "ready"
            self.status_detail = detail
            self.last_error = ""
            self.last_test_result = None

    def _apply_generated_workflow(self, data: dict[str, Any], *, detail: str, chat_message: str) -> Path:
        if self.running:
            raise RuntimeError("Akis calisirken workflow degistirilemez.")
        path = save_generated_workflow(self.project_dir, data)
        self._reset_ready_state(detail)
        self._log(detail)
        append_chat_entry(self.project_dir, "Orkestra", chat_message)
        return path

    def apply_workflow_template(self, template_id: str) -> dict[str, Any]:
        if self.running:
            raise RuntimeError("Akis calisirken workflow sablonu degistirilemez.")
        template = WORKFLOW_TEMPLATES.get(template_id)
        if not template:
            raise ValueError("Bilinmeyen workflow sablonu.")
        data = json.loads(json.dumps(template["data"], ensure_ascii=False))
        self._apply_generated_workflow(
            data,
            detail=f"Workflow sablonu: {template['label']}",
            chat_message=f"Workflow sablonu uygulandi: {template['label']}",
        )
        return self.workflow_templates_payload()

    def _wizard_template_id(self, project_type: str, platform: str, test_expectation: str) -> str:
        project_text = project_type.lower()
        platform_text = platform.lower()
        test_text = test_expectation.lower()
        haystack = f"{project_text} {platform_text} {test_text}"
        if any(key in project_text for key in ("bug", "hata", "test", "kontrol", "fix")) or any(
            key in test_text for key in ("sadece test", "bugfix", "hata odakli")
        ):
            return "test-fix"
        if any(key in haystack for key in ("masaustu", "desktop", "windows", "tkinter", "pyside", "python")):
            return "desktop-python"
        if any(key in haystack for key in ("mevcut", "var olan", "refactor", "gelistir")):
            return "existing-app"
        return "default"

    def wizard_workflow_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.running:
            raise RuntimeError("Akis calisirken sihirbaz workflow'u degistirilemez.")
        request = str(payload.get("request", "") or read_user_request(self.project_dir))
        project_type = str(payload.get("projectType", "")).strip()
        platform = str(payload.get("platform", "")).strip()
        design = str(payload.get("design", "")).strip()
        test_expectation = str(payload.get("testExpectation", "")).strip()
        brief = compose_wizard_brief(request, project_type, platform, design, test_expectation)
        if not brief:
            raise ValueError("Sihirbaz icin once istek yaz.")

        template_id = self._wizard_template_id(project_type, platform, test_expectation)
        template = WORKFLOW_TEMPLATES[template_id]
        data = json.loads(json.dumps(template["data"], ensure_ascii=False))
        data["summary"] = f"Sihirbaz akisi: {project_type or template['label']}"
        data["project_type"] = f"wizard-{data.get('project_type') or template_id}"
        data["brief_hash"] = hashlib.sha256(brief.encode("utf-8", errors="replace")).hexdigest()[:16]
        picks = [
            f"Proje tipi: {project_type or '-'}",
            f"Hedef platform: {platform or '-'}",
            f"Tasarim tarzi: {design or '-'}",
            f"Test beklentisi: {test_expectation or '-'}",
        ]
        prefix = "[Sihirbaz Workflow]\n" + "\n".join(f"- {item}" for item in picks)
        for stage in data["stages"]:
            stage["prompt"] = f"{prefix}\n\n{stage['prompt']}"

        self._apply_generated_workflow(
            data,
            detail=f"Sihirbaz workflow hazir: {template['label']}",
            chat_message=(
                "Sihirbaz secimleriyle workflow olusturuldu.\n"
                f"- Sablon: {template['label']}\n"
                + "\n".join(f"- {item}" for item in picks)
            ),
        )
        self.save_request(brief)
        return {
            "ok": True,
            "brief": brief,
            "templateId": template_id,
            "templateLabel": template["label"],
            "status": self.status_payload(),
        }

    def _result_quality_payload(self, stages: list[dict[str, Any]], status: str, error: str) -> dict[str, str]:
        quality = assess_run_quality(self.project_dir, stages, status, error)
        report = self.last_test_result
        report_path = self.project_dir / TEST_REPORT_FILE
        if report is None and report_path.exists():
            try:
                raw = json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    report = raw
            except Exception:
                report = None
        report_current = report_path.exists()
        workflow_path = self.project_dir / GENERATED_WORKFLOW_FILE
        if report_current and workflow_path.exists():
            try:
                report_current = report_path.stat().st_mtime >= workflow_path.stat().st_mtime
            except OSError:
                report_current = True
        if report_current and isinstance(report, dict) and report.get("status") == "failed":
            return {"label": "test gecmedi", "category": "test-gecmedi"}
        return quality

    def _error_workflow_data(self, action: str) -> dict[str, Any]:
        error = self.last_error or "Son hata kaydi yok."
        log_tail = self._recent_log_text()[-3000:]
        context = (
            "[Hata Aksiyonu]\n"
            f"Son durum: {self.status}\n"
            f"Son hata: {error}\n\n"
            "[Log Ozeti]\n"
            f"{log_tail or '-'}"
        )
        if action == "codex_review":
            return {
                "summary": "Codex hata kontrol akisi",
                "project_type": "error-codex-review",
                "brief_hash": hashlib.sha256(context.encode("utf-8", errors="replace")).hexdigest()[:16],
                "stages": [
                    {
                        "name": "Hata Siniflandirma",
                        "agent": "codex",
                        "prompt": f"{context}\n\nistek.md dosyasini oku. Hatayi sebep, etki ve tekrar uretme adimlariyla kontrol.md dosyasina yaz. Kod degistirme.",
                        "reads": [REQUEST_FILE],
                        "writes": ["kontrol.md"],
                        "checkpoint": False,
                        "timeout": 1200,
                        "fallback_agent": "claude",
                    },
                    {
                        "name": "Test Komutlari",
                        "agent": "codex",
                        "prompt": "kontrol.md dosyasini oku. Calistirilmasi gereken yerel test ve smoke komutlarini test_raporu.json dosyasina JSON olarak yaz.",
                        "reads": ["kontrol.md"],
                        "writes": [TEST_REPORT_FILE],
                        "checkpoint": False,
                        "timeout": 1200,
                        "fallback_agent": "claude",
                    },
                    {
                        "name": "Son Kontrol",
                        "agent": "codex",
                        "prompt": "kontrol.md ve test_raporu.json dosyalarini oku. Kullaniciya uygulanabilir kontrol sonucunu kontrol.md dosyasinda netlestir.",
                        "reads": ["kontrol.md", TEST_REPORT_FILE],
                        "writes": ["kontrol.md"],
                        "checkpoint": False,
                        "timeout": 1200,
                        "fallback_agent": "claude",
                    },
                ],
            }
        return {
            "summary": "Claude hata duzeltme akisi",
            "project_type": "error-claude-fix",
            "brief_hash": hashlib.sha256(context.encode("utf-8", errors="replace")).hexdigest()[:16],
            "stages": [
                {
                    "name": "Hata Teshisi",
                    "agent": "codex",
                    "prompt": f"{context}\n\nistek.md dosyasini oku. Duzeltme icin kisa teknik teshisi kontrol.md dosyasina yaz.",
                    "reads": [REQUEST_FILE],
                    "writes": ["kontrol.md"],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Claude Duzeltme",
                    "agent": "claude",
                    "prompt": "istek.md ve kontrol.md dosyalarini oku. Hatayi projede duzelt, gerekiyorsa kodu guncelle. Yapilanlari rapor.md dosyasina yaz.",
                    "reads": [REQUEST_FILE, "kontrol.md"],
                    "writes": ["rapor.md"],
                    "checkpoint": False,
                    "timeout": 1800,
                    "fallback_agent": "codex",
                },
                {
                    "name": "Duzeltme Kontrolu",
                    "agent": "codex",
                    "prompt": "rapor.md dosyasini ve projedeki son degisiklikleri kontrol et. Eksik/risk/test onerilerini kontrol.md dosyasina yaz.",
                    "reads": ["rapor.md"],
                    "writes": ["kontrol.md"],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
            ],
        }

    def error_action_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "")).strip().lower()
        if action in {"run_tests", "rerun_tests"}:
            result = self.run_project_tests(target=str(payload.get("target", "")))
            return {"ok": True, "message": "Testler calisti.", "result": result, "status": self.status_payload()}
        if self.running:
            raise RuntimeError("Akis calisirken hata aksiyonu baslatilamaz.")
        if action == "restore_last_snapshot":
            snapshots = list_snapshots(self.project_dir)
            if not snapshots:
                raise ValueError("Geri donulecek snapshot bulunamadi.")
            snap_id = str(snapshots[0].get("id", ""))
            restore_snapshot(self.project_dir, snap_id)
            self._reset_ready_state(f"Snapshot'a donuldu: {snap_id}")
            append_chat_entry(self.project_dir, "Orkestra", f"Son snapshot'a donuldu: {snap_id}")
            return {"ok": True, "message": f"Snapshot'a donuldu: {snap_id}", "status": self.status_payload()}
        if action not in {"claude_fix", "codex_review"}:
            raise ValueError("Bilinmeyen hata aksiyonu.")

        data = self._error_workflow_data(action)
        label = "Claude duzeltme" if action == "claude_fix" else "Codex kontrol"
        self._apply_generated_workflow(
            data,
            detail=f"{label} workflow hazir",
            chat_message=f"{label} hata aksiyonu icin workflow olusturuldu.",
        )
        if bool(payload.get("autoStart", True)):
            self.start_run(start_idx=1, reset_state=True, use_checkpoints=False)
            return {"ok": True, "message": f"{label} akisi baslatildi.", "status": self.status_payload()}
        return {"ok": True, "message": f"{label} workflow hazir.", "status": self.status_payload()}

    def run_quality_audit(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        target_path = self.project_dir
        target = str(payload.get("target", "")).strip()
        if target:
            candidate = self.safe_file_path(target)
            if candidate.exists() and candidate.is_dir():
                target_path = candidate
        include = set(payload.get("include") or ["lint", "security", "dependency", "deadcode", "acceptance"])
        auto_fix = bool(payload.get("autoFix", False))
        sections: list[dict[str, Any]] = []
        if "lint" in include:
            sections.append(self._lint_format_section(target_path, auto_fix=auto_fix))
        if "security" in include:
            sections.append(self._security_scan_section(target_path))
        if "dependency" in include:
            sections.append(self._dependency_analysis_section())
        if "deadcode" in include:
            sections.append(self._dead_code_section(target_path))
        if "acceptance" in include:
            sections.append(self._acceptance_section())

        flat_rows = [row for section in sections for row in section.get("rows", [])]
        failed = sum(1 for row in flat_rows if row.get("status") == "failed")
        warnings = sum(1 for row in flat_rows if row.get("status") == "warn")
        skipped = sum(1 for row in flat_rows if row.get("status") == "skipped")
        status = "failed" if failed else "warn" if warnings else "success"
        result = {
            "ok": True,
            "ranAt": now_stamp(),
            "target": str(target_path.relative_to(self.project_dir)) if target_path != self.project_dir else ".",
            "status": status,
            "failed": failed,
            "warnings": warnings,
            "skipped": skipped,
            "autoFix": auto_fix,
            "sections": sections,
        }
        (self.project_dir / QUALITY_REPORT_FILE).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self._log(f"Kalite taramasi calisti: {status} ({warnings} uyari, {failed} hata)")
        append_chat_entry(self.project_dir, "Orkestra", f"Kalite taramasi tamamlandi: {status}. Rapor: {QUALITY_REPORT_FILE}")
        return result

    def _quality_row(
        self,
        name: str,
        status: str,
        detail: str,
        *,
        command: str = "",
        file: str = "",
        line: int | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {"name": name, "status": status, "detail": detail}
        if command:
            row["command"] = command
        if file:
            row["file"] = file
        if line:
            row["line"] = line
        return row

    def _section(self, key: str, title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        status = "success"
        if any(row.get("status") == "failed" for row in rows):
            status = "failed"
        elif any(row.get("status") == "warn" for row in rows):
            status = "warn"
        elif rows and all(row.get("status") == "skipped" for row in rows):
            status = "skipped"
        return {"key": key, "title": title, "status": status, "rows": rows}

    def _python_tool_base(self, tool: str, module: str) -> list[str] | None:
        if importlib.util.find_spec(module):
            return [sys.executable, "-m", module]
        found = find_tool(tool)
        if found:
            return [found]
        return None

    def _run_quality_command(self, name: str, cmd: list[str], *, timeout: int = 120) -> dict[str, Any]:
        result = self._run_check(name, cmd, cwd=self.project_dir, timeout=timeout)
        return self._quality_row(
            name,
            result["status"],
            result.get("output", "").strip() or ("Tamam" if result["status"] == "success" else "-"),
            command=result.get("command", " ".join(cmd)),
        )

    def _lint_format_section(self, target_path: Path, *, auto_fix: bool) -> dict[str, Any]:
        rel_target = "." if target_path == self.project_dir else str(target_path.relative_to(self.project_dir))
        rows: list[dict[str, Any]] = []
        ruff = self._python_tool_base("ruff", "ruff")
        if ruff:
            cmd = [*ruff, "check", rel_target]
            if auto_fix:
                cmd.append("--fix")
            rows.append(self._run_quality_command("ruff check", cmd))
            format_cmd = [*ruff, "format", rel_target] if auto_fix else [*ruff, "format", "--check", rel_target]
            rows.append(self._run_quality_command("ruff format", format_cmd))
        else:
            rows.append(self._quality_row("ruff", "skipped", "ruff kurulu degil; Python lint/format atlandi."))

        black = self._python_tool_base("black", "black")
        if black:
            cmd = [*black, rel_target] if auto_fix else [*black, "--check", rel_target]
            rows.append(self._run_quality_command("black", cmd))
        else:
            rows.append(self._quality_row("black", "skipped", "black kurulu degil; alternatif format kontrolu atlandi."))

        package_json = self.project_dir / "package.json"
        npx = find_tool("npx")
        if package_json.exists() and npx:
            rows.append(self._run_quality_command("eslint", [npx, "--no-install", "eslint", rel_target]))
            prettier_cmd = [npx, "--no-install", "prettier", "--write" if auto_fix else "--check", rel_target]
            rows.append(self._run_quality_command("prettier", prettier_cmd))
        elif package_json.exists():
            rows.append(self._quality_row("eslint/prettier", "skipped", "package.json var ama npx bulunamadi."))
        else:
            rows.append(self._quality_row("eslint/prettier", "skipped", "package.json yok; JS lint/format atlandi."))
        return self._section("lint", "Lint / Format", rows)

    def _iter_quality_files(self, root: Path, *, limit: int = 500) -> list[Path]:
        rows: list[Path] = []
        for path in root.rglob("*"):
            if len(rows) >= limit:
                break
            if not path.is_file():
                continue
            try:
                rel_parts = path.relative_to(self.project_dir).parts
            except ValueError:
                continue
            if any(part in SKIP_DIRS for part in rel_parts[:-1]):
                continue
            name = path.name
            if name.startswith(".env") or name in TEXT_FILENAMES or path.suffix.lower() in CODE_EXTS:
                rows.append(path)
        return sorted(rows)

    def _read_small_text(self, path: Path, limit: int = 600_000) -> str:
        try:
            if path.stat().st_size > limit:
                return ""
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _security_scan_section(self, root: Path) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        local_hosts = {"127.0.0.1", "localhost", "::1", None}
        if self.server_host not in local_hosts:
            status = "warn" if self.auth_enabled else "failed"
            detail = "Panel public host uzerinde token ile korunuyor." if self.auth_enabled else "Panel public host uzerinde tokensiz calisiyor."
            rows.append(self._quality_row("Public host", status, detail))

        secret_re = re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|private[_-]?key|access[_-]?key)\b\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{12,})"
        )
        dangerous = [
            (re.compile(r"\beval\s*\("), "eval kullanimi"),
            (re.compile(r"\bexec\s*\("), "exec kullanimi"),
            (re.compile(r"shell\s*=\s*True"), "subprocess shell=True"),
            (re.compile(r"\bpickle\.loads?\s*\("), "pickle load kullanimi"),
            (re.compile(r"\byaml\.load\s*\("), "yaml.load kullanimi"),
        ]
        for path in self._iter_quality_files(root):
            rel = str(path.relative_to(self.project_dir)).replace("\\", "/")
            if rel in {QUALITY_REPORT_FILE, TEST_REPORT_FILE, ACCEPTANCE_REPORT_FILE}:
                continue
            if path.name.startswith(".env") and path.name not in {".env.example", ".env.sample"}:
                rows.append(self._quality_row(".env dosyasi", "warn", "Gercek gizli deger icerebilir; repo/paket disinda tutulmali.", file=rel))
            text = self._read_small_text(path)
            if not text:
                continue
            is_test_file = rel.startswith("tests/")
            for line_no, line in enumerate(text.splitlines(), 1):
                if secret_re.search(line) and not is_test_file and "example" not in rel.lower() and "dummy" not in line.lower():
                    rows.append(self._quality_row("Secret pattern", "warn", "Olası gizli deger bulundu; deger maskelendi.", file=rel, line=line_no))
                    if len(rows) > 80:
                        break
                for regex, label in dangerous:
                    if "re.compile" in line:
                        continue
                    if regex.search(line):
                        rows.append(self._quality_row(label, "warn", "Manuel guvenlik kontrolu gerekli.", file=rel, line=line_no))
                if len(rows) > 100:
                    break
        if not rows:
            rows.append(self._quality_row("Security scan", "success", "Belirgin secret/eval/public-host riski bulunmadi."))
        return self._section("security", "Guvenlik Taramasi", rows)

    def _normalized_package_name(self, value: str) -> str:
        name = re.split(r"[<>=!~;\[\]\s]", value.strip(), maxsplit=1)[0]
        return name.lower().replace("_", "-")

    def _dependency_analysis_section(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        declared: dict[str, str] = {}
        dep_specs: list[tuple[str, str]] = []
        pyproject = self.project_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project = raw.get("project", {})
                for dep in project.get("dependencies", []) or []:
                    dep_specs.append((str(dep), "pyproject.toml"))
                optional = project.get("optional-dependencies", {}) or {}
                for group, deps in optional.items():
                    for dep in deps or []:
                        dep_specs.append((str(dep), f"pyproject.toml[{group}]"))
            except Exception as exc:
                rows.append(self._quality_row("pyproject.toml", "failed", f"Manifest okunamadi: {exc}"))
        for req_path in sorted(self.project_dir.glob("requirements*.txt")):
            for line in req_path.read_text(encoding="utf-8", errors="replace").splitlines():
                clean = line.strip()
                if not clean or clean.startswith(("#", "-")):
                    continue
                dep_specs.append((clean, req_path.name))

        for spec, source in dep_specs:
            name = self._normalized_package_name(spec)
            if not name:
                continue
            declared[name] = source
            if "==" not in spec and "===" not in spec:
                rows.append(self._quality_row("Version pinning", "warn", f"{spec} tam sabitlenmemis.", file=source))
        if not declared:
            rows.append(self._quality_row("Dependency manifest", "warn", "pyproject/requirements icinde dependency bulunamadi."))

        imports = self._collect_python_imports()
        local = self._local_python_modules()
        stdlib = set(getattr(sys, "stdlib_module_names", set()))
        external = {
            item for item in imports
            if item not in local and item not in stdlib and not item.startswith("_")
        }
        declared_imports = {name.replace("-", "_") for name in declared}
        missing = sorted(item for item in external if item.replace("_", "-") not in declared and item not in declared_imports)
        for name in missing[:20]:
            rows.append(self._quality_row("Eksik paket", "warn", f"'{name}' import ediliyor ama manifestte gorunmuyor."))
        unused = sorted(name for name in declared if name.replace("-", "_") not in imports and name not in {"setuptools"})
        for name in unused[:12]:
            rows.append(self._quality_row("Gereksiz paket adayi", "warn", f"'{name}' manifestte var ama importlarda gorunmedi.", file=declared[name]))

        pip_audit = find_tool("pip-audit")
        if pip_audit:
            rows.append(self._run_quality_command("pip-audit", [pip_audit, "--progress-spinner", "off"], timeout=90))
        else:
            rows.append(self._quality_row("pip-audit", "skipped", "pip-audit kurulu degil; Python advisory kontrolu atlandi."))
        if (self.project_dir / "package.json").exists() and find_tool("npm"):
            rows.append(self._run_quality_command("npm audit", [find_tool("npm") or "npm", "audit", "--omit=dev"], timeout=90))
        elif (self.project_dir / "package.json").exists():
            rows.append(self._quality_row("npm audit", "skipped", "npm bulunamadi."))
        return self._section("dependency", "Dependency Analizi", rows)

    def _local_python_modules(self) -> set[str]:
        names = {path.stem for path in self.project_dir.glob("*.py")}
        for path in self.project_dir.iterdir():
            if path.is_dir() and (path / "__init__.py").exists():
                names.add(path.name)
        names.update({"tests"})
        return names

    def _collect_python_imports(self) -> set[str]:
        imports: set[str] = set()
        for path in self._python_files_for_test(self.project_dir):
            text = self._read_small_text(path)
            if not text:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split(".", 1)[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".", 1)[0])
        imports.discard("__future__")
        return imports

    def _dead_code_section(self, root: Path) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        function_defs: dict[str, tuple[str, int]] = {}
        used_names: set[str] = set()
        duplicate_counter: Counter[str] = Counter()
        duplicate_locations: dict[str, list[str]] = {}
        for path in self._iter_quality_files(root):
            rel = str(path.relative_to(self.project_dir)).replace("\\", "/")
            text = self._read_small_text(path)
            if not text:
                continue
            line_count = len(text.splitlines())
            if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx"} and line_count > 800:
                rows.append(self._quality_row("Buyuk dosya", "warn", f"{line_count} satir; bolme/refactor adayi.", file=rel))
            if path.suffix.lower() == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        function_defs.setdefault(node.name, (rel, node.lineno))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        used_names.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        used_names.add(node.attr)
            normalized = [
                line.strip()
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith(("#", "//", "/*", "*"))
            ]
            for idx in range(0, max(0, len(normalized) - 5)):
                chunk = "\n".join(normalized[idx: idx + 6])
                if len(chunk) < 120:
                    continue
                key = hashlib.sha1(chunk.encode("utf-8", errors="replace")).hexdigest()
                duplicate_counter[key] += 1
                duplicate_locations.setdefault(key, []).append(f"{rel}:{idx + 1}")

        keepers = {"main", "create_server", "shutdown_server"}
        for name, (rel, line) in sorted(function_defs.items()):
            if name.startswith("_") or name in keepers:
                continue
            if name not in used_names:
                rows.append(self._quality_row("Dead code adayi", "warn", f"'{name}' referansi bulunamadi.", file=rel, line=line))
                if len(rows) > 60:
                    break
        for key, count in duplicate_counter.most_common(8):
            locations = duplicate_locations.get(key, [])
            if count > 1 and len(set(locations)) > 1:
                rows.append(self._quality_row("Tekrar eden blok", "warn", "Benzer 6 satirlik bloklar: " + ", ".join(locations[:4])))
        if not rows:
            rows.append(self._quality_row("Dead code / buyuk dosya", "success", "Esik ustu buyuk dosya veya belirgin dead-code adayi bulunmadi."))
        return self._section("deadcode", "Dead Code / Buyuk Dosya", rows)

    def _extract_acceptance_criteria(self, request: str) -> list[str]:
        raw_parts = re.split(r"[\n.;]+", request or "")
        criteria: list[str] = []
        for part in raw_parts:
            clean = re.sub(r"^[\s\-*0-9.)]+", "", part).strip()
            if len(clean) < 6:
                continue
            if clean not in criteria:
                criteria.append(clean)
            if len(criteria) >= 8:
                break
        return criteria or ["Kullanici istegi calisan cikti ve raporla karsilanmali."]

    def _load_acceptance_criteria(self) -> list[str]:
        path = self.project_dir / ACCEPTANCE_FILE
        if path.exists():
            rows = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                clean = re.sub(r"^[\s\-*0-9.)\[\]xX]+", "", line).strip()
                if clean and not clean.lower().startswith("#"):
                    rows.append(clean)
            if rows:
                return rows[:12]
        criteria = self._extract_acceptance_criteria(read_user_request(self.project_dir))
        self._write_acceptance_file(criteria)
        return criteria

    def _write_acceptance_file(self, criteria: list[str]) -> None:
        lines = ["# Kabul Kriterleri", ""]
        lines += [f"- [ ] {item}" for item in criteria]
        (self.project_dir / ACCEPTANCE_FILE).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    def run_acceptance_check(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        criteria_payload = payload.get("criteria")
        if isinstance(criteria_payload, list) and criteria_payload:
            criteria = [str(item).strip() for item in criteria_payload if str(item).strip()]
            self._write_acceptance_file(criteria)
        else:
            criteria = self._load_acceptance_criteria()
        evidence_parts = []
        for name in ("plan.md", "tasarim.md", "rapor.md", "kontrol.md", TEST_REPORT_FILE, CHAT_FILE):
            path = self.project_dir / name
            if path.exists():
                evidence_parts.append(path.read_text(encoding="utf-8", errors="replace"))
        evidence = "\n".join(evidence_parts).lower()
        rows = []
        for item in criteria:
            tokens = [token for token in re.findall(r"[a-zA-Z0-9_ğüşöçıİĞÜŞÖÇ]{4,}", item.lower()) if token not in {"kullanici", "istegi", "olsun", "yapilsin"}]
            hits = sum(1 for token in set(tokens) if token in evidence)
            status = "passed" if hits >= min(2, max(1, len(set(tokens)))) else "needs-review"
            rows.append({"criterion": item, "status": status, "matchedKeywords": hits})
        passed = sum(1 for row in rows if row["status"] == "passed")
        report_lines = ["# Kabul Kontrolu", "", f"Durum: {passed}/{len(rows)} kriter kanit buldu.", ""]
        for row in rows:
            mark = "x" if row["status"] == "passed" else " "
            report_lines.append(f"- [{mark}] {row['criterion']} ({row['status']})")
        (self.project_dir / ACCEPTANCE_REPORT_FILE).write_text("\n".join(report_lines).strip() + "\n", encoding="utf-8")
        return {
            "ok": True,
            "ranAt": now_stamp(),
            "status": "success" if passed == len(rows) else "warn",
            "passed": passed,
            "total": len(rows),
            "criteria": rows,
            "report": ACCEPTANCE_REPORT_FILE,
        }

    def _acceptance_section(self) -> dict[str, Any]:
        result = self.run_acceptance_check({})
        rows = [
            self._quality_row(
                "Acceptance criteria",
                "success" if item["status"] == "passed" else "warn",
                item["criterion"],
            )
            for item in result["criteria"]
        ]
        return self._section("acceptance", "Acceptance Criteria", rows)

    def prepare_test_generation_workflow(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if self.running:
            raise RuntimeError("Akis calisirken test uretme workflow'u hazirlanamaz.")
        data = {
            "summary": "Otomatik test uretme akisi",
            "project_type": "quality-test-generation",
            "brief_hash": hashlib.sha256(read_user_request(self.project_dir).encode("utf-8", errors="replace")).hexdigest()[:16],
            "stages": [
                {
                    "name": "Test Kapsami",
                    "agent": "codex",
                    "prompt": f"{REQUEST_FILE}, plan.md, rapor.md ve {ACCEPTANCE_FILE} dosyalarini oku. Test kapsamini ve riskleri plan.md dosyasina ekle.",
                    "reads": [REQUEST_FILE],
                    "writes": ["plan.md"],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Test Kodlama",
                    "agent": "codex",
                    "prompt": "Projeye uygun test dosyalarini veya smoke test scriptlerini ekle. Hangi testleri yazdigini test_raporu.json dosyasina yaz.",
                    "reads": ["plan.md", "rapor.md"],
                    "writes": [TEST_REPORT_FILE],
                    "checkpoint": False,
                    "timeout": 1800,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Test Dogrulama",
                    "agent": "codex",
                    "prompt": f"Yazilan testleri ve kabul kriterlerini kontrol et. Sonucu {ACCEPTANCE_REPORT_FILE} dosyasina yaz.",
                    "reads": [TEST_REPORT_FILE, ACCEPTANCE_FILE],
                    "writes": [ACCEPTANCE_REPORT_FILE],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
            ],
        }
        self._apply_generated_workflow(
            data,
            detail="Test uretme workflow hazir",
            chat_message="Kodlama sonrasi ayri test ajani icin workflow olusturuldu.",
        )
        if bool(payload.get("autoStart", False)):
            self.start_run(start_idx=1, reset_state=True, use_checkpoints=False)
            message = "Test uretme akisi baslatildi."
        else:
            message = "Test uretme workflow hazir."
        return {"ok": True, "message": message, "status": self.status_payload()}

    def prepare_ui_polish_workflow(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if self.running:
            raise RuntimeError("Akis calisirken UI polish workflow'u hazirlanamaz.")
        data = {
            "summary": "Kodlama sonrasi UI polish akisi",
            "project_type": "quality-ui-polish",
            "brief_hash": hashlib.sha256(read_user_request(self.project_dir).encode("utf-8", errors="replace")).hexdigest()[:16],
            "stages": [
                {
                    "name": "UI Audit Hazirligi",
                    "agent": "codex",
                    "prompt": f"{REQUEST_FILE}, tasarim.md, rapor.md ve {ACCEPTANCE_FILE} dosyalarini oku. UI risklerini kontrol.md icin madde madde cikar.",
                    "reads": [REQUEST_FILE, "tasarim.md", "rapor.md", ACCEPTANCE_FILE],
                    "writes": ["kontrol.md"],
                    "checkpoint": False,
                    "timeout": 900,
                    "fallback_agent": "claude",
                },
                {
                    "name": "UI Polish",
                    "agent": "gemini",
                    "prompt": (
                        "Sadece tasarim kalitesi uzerinde calis: spacing, renk/kontrast, responsive gorunum, "
                        "bos/tasan alan, hizli taranabilirlik ve erisilebilirlik. Kapsami buyutmeden kucuk CSS/layout "
                        "duzeltmeleri yap ve kontrol.md dosyasini guncelle."
                    ),
                    "reads": [REQUEST_FILE, "tasarim.md", "rapor.md", "kontrol.md"],
                    "writes": ["kontrol.md"],
                    "checkpoint": False,
                    "timeout": 1500,
                    "fallback_agent": "claude",
                },
                {
                    "name": "Responsive Kontrol",
                    "agent": "codex",
                    "prompt": (
                        f"UI polish sonrasi 375, 768 ve 1440px gorunumlerini kontrol et. "
                        f"Varsa screenshot/console bulgularini {WEB_AUDIT_REPORT_FILE} dosyasina yaz."
                    ),
                    "reads": ["kontrol.md", WEB_AUDIT_REPORT_FILE],
                    "writes": [WEB_AUDIT_REPORT_FILE],
                    "checkpoint": False,
                    "timeout": 1200,
                    "fallback_agent": "claude",
                },
            ],
        }
        self._apply_generated_workflow(
            data,
            detail="UI polish workflow hazir",
            chat_message="Kodlama sonrasi UI polish ajani icin workflow olusturuldu.",
        )
        if bool(payload.get("autoStart", False)):
            self.start_run(start_idx=1, reset_state=True, use_checkpoints=False)
            message = "UI polish akisi baslatildi."
        else:
            message = "UI polish workflow hazir."
        return {"ok": True, "message": message, "status": self.status_payload()}

    def _find_free_port(self, start: int = 5173) -> int:
        for port in range(start, start + 120):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    continue
                return port
        raise RuntimeError("Preview icin bos port bulunamadi.")

    def _candidate_web_roots(self, target: str = "") -> list[Path]:
        roots: list[Path] = []

        def add(path: Path) -> None:
            try:
                resolved = path.resolve()
                resolved.relative_to(self.project_dir)
            except Exception:
                return
            if resolved.is_dir() and resolved not in roots:
                roots.append(resolved)

        if target:
            try:
                add(self.safe_file_path(target))
            except ValueError:
                pass
        add(self.project_dir / "project")
        add(self.project_dir)
        markers = {"package.json", "index.html", "app.py", "main.py"}
        scanned = 0
        for path in self.project_dir.rglob("*"):
            if scanned >= 700:
                break
            scanned += 1
            if not path.is_file() or path.name not in markers:
                continue
            try:
                rel_parts = path.relative_to(self.project_dir).parts
            except ValueError:
                continue
            if any(part in SKIP_DIRS for part in rel_parts[:-1]):
                continue
            add(path.parent)
        return roots

    def _load_package_json(self, root: Path) -> dict[str, Any]:
        try:
            raw = json.loads((root / "package.json").read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _detect_webapp(self, root: Path, port: int) -> dict[str, Any] | None:
        npm = find_tool("npm") or "npm"
        package_json = root / "package.json"
        if package_json.exists():
            package = self._load_package_json(root)
            scripts = {str(key): str(value) for key, value in (package.get("scripts") or {}).items()}
            deps: dict[str, Any] = {}
            for key in ("dependencies", "devDependencies"):
                value = package.get(key)
                if isinstance(value, dict):
                    deps.update(value)
            haystack = " ".join([*scripts.values(), *deps.keys()]).lower()
            stack = "vite" if "vite" in haystack else "next" if "next" in haystack else "react" if "react" in haystack else "node"
            build_cmd = [npm, "run", "build"] if "build" in scripts else []
            env: dict[str, str] = {}
            if "preview" in scripts:
                preview_cmd = [npm, "run", "preview", "--", "--host", "127.0.0.1", "--port", str(port)]
            elif "dev" in scripts and stack == "next":
                preview_cmd = [npm, "run", "dev", "--", "-H", "127.0.0.1", "-p", str(port)]
            elif "dev" in scripts:
                preview_cmd = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)]
            elif "start" in scripts and stack == "next":
                preview_cmd = [npm, "run", "start", "--", "-H", "127.0.0.1", "-p", str(port)]
            elif "start" in scripts:
                preview_cmd = [npm, "start"]
                env = {"HOST": "127.0.0.1", "PORT": str(port), "BROWSER": "none"}
            else:
                return None
            return {
                "root": root,
                "stack": stack,
                "kind": "node",
                "url": f"http://127.0.0.1:{port}",
                "port": port,
                "buildCommand": build_cmd,
                "previewCommand": preview_cmd,
                "env": env,
            }

        for file_name in ("app.py", "main.py"):
            path = root / file_name
            if not path.exists():
                continue
            text = self._read_small_text(path, limit=120_000)
            module = path.stem
            if "FastAPI(" in text or "from fastapi" in text:
                return {
                    "root": root,
                    "stack": "fastapi",
                    "kind": "python",
                    "url": f"http://127.0.0.1:{port}",
                    "port": port,
                    "buildCommand": [],
                    "previewCommand": [sys.executable, "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1", "--port", str(port)],
                    "env": {},
                }
            if "Flask(" in text or "from flask" in text:
                return {
                    "root": root,
                    "stack": "flask",
                    "kind": "python",
                    "url": f"http://127.0.0.1:{port}",
                    "port": port,
                    "buildCommand": [],
                    "previewCommand": [sys.executable, "-m", "flask", "--app", module, "run", "--host", "127.0.0.1", "--port", str(port)],
                    "env": {},
                }

        if (root / "index.html").exists():
            return {
                "root": root,
                "stack": "static",
                "kind": "static",
                "url": f"http://127.0.0.1:{port}",
                "port": port,
                "buildCommand": [],
                "previewCommand": [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                "env": {},
            }
        return None

    def detect_webapp_payload(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        port = int(payload.get("port") or self._find_free_port())
        target = str(payload.get("target", "")).strip()
        candidates: list[dict[str, Any]] = []
        for root in self._candidate_web_roots(target):
            detected = self._detect_webapp(root, port)
            if detected:
                public = {key: value for key, value in detected.items() if key not in {"root", "env"}}
                public["root"] = str(root.relative_to(self.project_dir)).replace("\\", "/") or "."
                candidates.append(public)
        return {"ok": True, "detected": bool(candidates), "candidates": candidates, "selected": candidates[0] if candidates else None}

    def _wait_for_url(self, url: str, timeout: float = 12.0) -> tuple[bool, str]:
        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.5) as response:
                    if response.status < 500:
                        return True, f"HTTP {response.status}"
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    return True, f"HTTP {exc.code}"
                last_error = f"HTTP {exc.code}"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.35)
        return False, last_error or "Preview yanit vermedi."

    def prepare_web_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        port = int(payload.get("port") or self._find_free_port())
        target = str(payload.get("target", "")).strip()
        plan: dict[str, Any] | None = None
        for root in self._candidate_web_roots(target):
            plan = self._detect_webapp(root, port)
            if plan:
                break
        if not plan:
            raise ValueError("Vite/React/Next/Flask/FastAPI veya statik index.html bulunamadi.")

        build_result: dict[str, Any] | None = None
        if bool(payload.get("build", True)) and plan.get("buildCommand"):
            build_result = self._run_check("Web build", plan["buildCommand"], cwd=plan["root"], timeout=int(payload.get("buildTimeout") or 180))
            if build_result["status"] == "failed" and bool(payload.get("failOnBuild", True)):
                return {"ok": False, "message": "Build basarisiz.", "preview": self._public_preview_plan(plan), "build": build_result}

        self.stop_web_preview()
        log_dir = self.project_dir / LOG_DIR
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"web_preview_{plan['port']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        env = process_env()
        env.update({str(key): str(value) for key, value in plan.get("env", {}).items()})
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            proc = subprocess.Popen(
                plan["previewCommand"],
                cwd=plan["root"],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **process_kwargs(),
            )
        self.preview_proc = proc
        self.preview_url = str(plan["url"])
        self.preview_root = plan["root"]
        self.preview_log_path = log_path
        ready, detail = self._wait_for_url(self.preview_url, timeout=float(payload.get("timeout") or 12))
        public = self._public_preview_plan(plan)
        public["pid"] = proc.pid
        public["log"] = str(log_path.relative_to(self.project_dir)).replace("\\", "/")
        public["ready"] = ready
        public["detail"] = detail
        self._log(f"Web preview hazirlandi: {self.preview_url} ({detail})")
        return {"ok": ready, "message": detail, "preview": public, "build": build_result}

    def _public_preview_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "root": str(plan["root"].relative_to(self.project_dir)).replace("\\", "/") or ".",
            "stack": plan.get("stack", ""),
            "kind": plan.get("kind", ""),
            "url": plan.get("url", ""),
            "port": plan.get("port"),
            "buildCommand": plan.get("buildCommand") or [],
            "previewCommand": plan.get("previewCommand") or [],
        }

    def stop_web_preview(self) -> dict[str, Any]:
        proc = self.preview_proc
        stopped = False
        if proc and proc.poll() is None:
            kill_process_tree(proc)
            stopped = True
        self.preview_proc = None
        self.preview_url = ""
        self.preview_root = None
        self.preview_log_path = None
        return {"ok": True, "stopped": stopped, "status": self.status_payload()}

    def webapp_summary_payload(self) -> dict[str, Any]:
        proc = self.preview_proc
        running = bool(proc and proc.poll() is None)
        summary = {
            "previewRunning": running,
            "previewUrl": self.preview_url if running else "",
            "previewRoot": str(self.preview_root.relative_to(self.project_dir)).replace("\\", "/") if running and self.preview_root else "",
            "previewLog": str(self.preview_log_path.relative_to(self.project_dir)).replace("\\", "/") if running and self.preview_log_path else "",
            "report": {"exists": False, "status": "missing"},
        }
        path = self.project_dir / WEB_AUDIT_REPORT_FILE
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                summary["report"] = {
                    "exists": True,
                    "status": raw.get("status", "unknown"),
                    "ranAt": raw.get("ranAt", ""),
                    "failed": raw.get("failed", 0),
                    "warnings": raw.get("warnings", 0),
                    "skipped": raw.get("skipped", 0),
                }
            except Exception:
                summary["report"] = {"exists": True, "status": "failed", "summary": "Web QA raporu okunamadi."}
        return summary

    def run_webapp_audit(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        url = str(payload.get("url") or self.preview_url).strip()
        auto_preview: dict[str, Any] | None = None
        if not url:
            auto_preview = self.prepare_web_preview({"build": bool(payload.get("build", True)), "target": str(payload.get("target", ""))})
            if not auto_preview.get("ok"):
                result = self._write_web_audit_report(
                    "failed",
                    [
                        self._section(
                            "preview",
                            "Build + Preview",
                            [self._quality_row("Preview", "failed", auto_preview.get("message", "Preview baslatilamadi."))],
                        )
                    ],
                    target=".",
                    url="",
                )
                return result
            url = str(auto_preview.get("preview", {}).get("url") or self.preview_url)
        if importlib.util.find_spec("playwright"):
            try:
                result = self._run_playwright_audit(url, payload)
            except Exception as exc:
                result = self._run_static_web_audit(url, payload, skipped_reason=f"playwright calisamadi: {exc}")
        else:
            result = self._run_static_web_audit(url, payload, skipped_reason="playwright kurulu degil; screenshot/console tarayici kontrolu atlandi.")
        if auto_preview:
            result["preview"] = auto_preview.get("preview")
        return result

    def _run_playwright_audit(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore

        viewports = payload.get("viewports") or [
            {"name": "mobile", "width": 375, "height": 812},
            {"name": "tablet", "width": 768, "height": 1024},
            {"name": "desktop", "width": 1440, "height": 900},
        ]
        shot_dir = self.project_dir / ".orkestra" / "web_screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rows: list[dict[str, Any]] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for item in viewports:
                    name = str(item.get("name") or f"{item.get('width')}px")
                    width = int(item.get("width") or 1440)
                    height = int(item.get("height") or 900)
                    page = browser.new_page(viewport={"width": width, "height": height})
                    console_errors: list[str] = []
                    page_errors: list[str] = []
                    page.on("console", lambda msg, errors=console_errors: errors.append(msg.text) if msg.type == "error" else None)
                    page.on("pageerror", lambda exc, errors=page_errors: errors.append(str(exc)))
                    try:
                        page.goto(url, wait_until="networkidle", timeout=20_000)
                        shot_path = shot_dir / f"{stamp}_{name}_{width}.png"
                        page.screenshot(path=str(shot_path), full_page=True)
                        metrics = page.evaluate(
                            """() => {
                              const body = document.body;
                              const text = (body && body.innerText || "").trim();
                              return {
                                textLength: text.length,
                                scrollWidth: document.documentElement.scrollWidth,
                                innerWidth: window.innerWidth,
                                bodyHeight: body ? body.getBoundingClientRect().height : 0
                              };
                            }"""
                        )
                        is_blank = int(metrics.get("textLength") or 0) < 3 and float(metrics.get("bodyHeight") or 0) < 24
                        has_overflow = int(metrics.get("scrollWidth") or 0) > int(metrics.get("innerWidth") or 0) + 4
                        rows.append(self._quality_row(f"{name} screenshot", "failed" if is_blank else "success", "Sayfa bos gorunuyor." if is_blank else str(shot_path.relative_to(self.project_dir)).replace("\\", "/")))
                        rows.append(self._quality_row(f"{name} responsive", "warn" if has_overflow else "success", f"{width}px viewport yatay tasma {'var' if has_overflow else 'yok'}." ))
                        if console_errors or page_errors:
                            detail = "\n".join([*console_errors[:6], *page_errors[:6]])[:900]
                            rows.append(self._quality_row(f"{name} console", "failed", detail))
                        else:
                            rows.append(self._quality_row(f"{name} console", "success", "Console error yakalanmadi."))
                    except Exception as exc:
                        rows.append(self._quality_row(f"{name} audit", "failed", str(exc)))
                    finally:
                        page.close()
            finally:
                browser.close()
        return self._write_web_audit_report("", [self._section("browser", "Screenshot / Console / Responsive", rows)], target=".", url=url)

    def _run_static_web_audit(self, url: str, payload: dict[str, Any], *, skipped_reason: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        try:
            with urllib.request.urlopen(url, timeout=float(payload.get("timeout") or 6)) as response:
                raw = response.read(700_000).decode("utf-8", errors="replace")
            text = re.sub(r"<(script|style)\b.*?</\1>", "", raw, flags=re.IGNORECASE | re.DOTALL)
            visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
            visible = re.sub(r"\s+", " ", visible).strip()
            rows.append(self._quality_row("Preview reachable", "success", f"{url} erisilebilir."))
            rows.append(self._quality_row("Blank page", "warn" if len(visible) < 3 else "success", "Gorunur metin az; manuel kontrol gerekli." if len(visible) < 3 else "Statik icerik bos degil."))
        except Exception as exc:
            rows.append(self._quality_row("Preview reachable", "failed", str(exc)))
        rows.append(self._quality_row("Screenshot", "skipped", skipped_reason))
        rows.append(self._quality_row("Console errors", "skipped", skipped_reason))
        rows.append(self._quality_row("Responsive 375/768/1440", "skipped", skipped_reason))
        return self._write_web_audit_report("", [self._section("browser", "Web/App QA", rows)], target=".", url=url)

    def _write_web_audit_report(self, status: str, sections: list[dict[str, Any]], *, target: str, url: str) -> dict[str, Any]:
        flat_rows = [row for section in sections for row in section.get("rows", [])]
        failed = sum(1 for row in flat_rows if row.get("status") == "failed")
        warnings = sum(1 for row in flat_rows if row.get("status") == "warn")
        skipped = sum(1 for row in flat_rows if row.get("status") == "skipped")
        final_status = status or ("failed" if failed else "warn" if warnings or skipped else "success")
        result = {
            "ok": True,
            "ranAt": now_stamp(),
            "target": target,
            "url": url,
            "status": final_status,
            "failed": failed,
            "warnings": warnings,
            "skipped": skipped,
            "sections": sections,
        }
        (self.project_dir / WEB_AUDIT_REPORT_FILE).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self._log(f"Web/App QA tamamlandi: {final_status} ({warnings} uyari, {failed} hata)")
        append_chat_entry(self.project_dir, "Orkestra", f"Web/App QA tamamlandi: {final_status}. Rapor: {WEB_AUDIT_REPORT_FILE}")
        return result

    def quality_summary_payload(self) -> dict[str, Any]:
        path = self.project_dir / QUALITY_REPORT_FILE
        if not path.exists():
            return {"exists": False, "status": "missing", "summary": "Kalite taramasi yok."}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"exists": True, "status": "failed", "summary": "Kalite raporu okunamadi."}
        return {
            "exists": True,
            "status": raw.get("status", "unknown"),
            "ranAt": raw.get("ranAt", ""),
            "failed": raw.get("failed", 0),
            "warnings": raw.get("warnings", 0),
            "skipped": raw.get("skipped", 0),
        }

    def run_project_tests(self, target: str = "") -> dict[str, Any]:
        target_path = self.project_dir
        if target:
            candidate = self.safe_file_path(target)
            if candidate.exists() and candidate.is_dir():
                target_path = candidate

        checks: list[dict[str, Any]] = []
        py_files = self._python_files_for_test(target_path)
        if py_files:
            checks.append(
                self._run_check(
                    "Python syntax",
                    [sys.executable, "-m", "py_compile", *[str(path) for path in py_files[:80]]],
                    cwd=self.project_dir,
                    timeout=60,
                )
            )
        else:
            checks.append({"name": "Python syntax", "status": "skipped", "command": "", "returnCode": None, "output": "Python dosyasi bulunamadi."})

        test_files = [path for path in target_path.rglob("test_*.py") if self._path_is_testable(path)]
        if test_files:
            checks.append(
                self._run_check(
                    "Pytest",
                    [sys.executable, "-m", "pytest", "-q", str(target_path)],
                    cwd=self.project_dir,
                    timeout=120,
                )
            )
        else:
            checks.append({"name": "Pytest", "status": "skipped", "command": "", "returnCode": None, "output": "test_*.py bulunamadi."})

        mp3_root = self.project_dir / "MP3INDIRICI"
        required = ["main.py", "README.md", "requirements.txt", "run.bat"]
        missing = [name for name in required if not (mp3_root / name).exists()]
        checks.append(
            {
                "name": "MP3 app required files",
                "status": "failed" if mp3_root.exists() and missing else "success" if mp3_root.exists() else "skipped",
                "command": "",
                "returnCode": 1 if mp3_root.exists() and missing else 0,
                "output": "Eksik: " + ", ".join(missing) if missing else "Temel dosyalar hazir." if mp3_root.exists() else "MP3INDIRICI klasoru yok.",
            }
        )

        failed = sum(1 for check in checks if check["status"] == "failed")
        result = {
            "ranAt": now_stamp(),
            "target": str(target_path.relative_to(self.project_dir)) if target_path != self.project_dir else ".",
            "status": "failed" if failed else "success",
            "failed": failed,
            "checks": checks,
        }
        (self.project_dir / TEST_REPORT_FILE).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self._log(f"Yerel test calisti: {result['status']} ({len(checks) - failed}/{len(checks)} basarili)")
        return result

    def _python_files_for_test(self, root: Path) -> list[Path]:
        rows: list[Path] = []
        for path in root.rglob("*.py"):
            if self._path_is_testable(path):
                rows.append(path)
        return sorted(rows)

    def _path_is_testable(self, path: Path) -> bool:
        try:
            rel_parts = path.relative_to(self.project_dir).parts
        except ValueError:
            return False
        return not any(part in SKIP_DIRS for part in rel_parts[:-1])

    def _run_check(self, name: str, cmd: list[str], *, cwd: Path, timeout: int) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=process_env(),
                **process_kwargs(),
            )
            output = proc.stdout or ""
            return {
                "name": name,
                "status": "success" if proc.returncode == 0 else "failed",
                "command": " ".join(cmd),
                "returnCode": proc.returncode,
                "output": output[:MAX_TEST_OUTPUT_CHARS],
            }
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            return {"name": name, "status": "failed", "command": " ".join(cmd), "returnCode": None, "output": f"Timeout ({timeout}sn)\n{output[:MAX_TEST_OUTPUT_CHARS]}"}
        except Exception as exc:
            return {"name": name, "status": "failed", "command": " ".join(cmd), "returnCode": None, "output": str(exc)}

    def _latest_log_path(self) -> Path | None:
        log_dir = self.project_dir / LOG_DIR
        if not log_dir.exists():
            return None
        logs = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        return logs[0] if logs else None

    def _recent_log_text(self) -> str:
        with self.lock:
            current = "\n".join(self.log_lines)
            path = self.log_path
        if current.strip():
            return current
        latest = path if path and path.exists() else self._latest_log_path()
        if not latest or not latest.exists():
            return ""
        try:
            raw = latest.read_bytes()
            return raw[-180_000:].decode("utf-8", errors="replace")
        except OSError:
            return ""

    def snapshot_list(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            return list_snapshots(self.project_dir)[:limit]
        except Exception:
            return []

    def _iter_code_files(self, limit: int = 100) -> list[Path]:
        rows: list[Path] = []
        if not self.project_dir.exists():
            return rows
        for path in self.project_dir.rglob("*"):
            if len(rows) >= limit:
                break
            if not path.is_file() or path.suffix.lower() not in CODE_EXTS:
                continue
            rel_parts = path.relative_to(self.project_dir).parts
            if any(part in SKIP_DIRS for part in rel_parts[:-1]):
                continue
            rows.append(path)
        return sorted(rows)


class MaestroRequestHandler(BaseHTTPRequestHandler):
    server_version = "MaestroWebPanel/1.0"

    @property
    def app(self) -> MaestroWebPanel:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Erisim token'i URL'de tasinabilir; log'a asla sizmasin.
        message = re.sub(r"([?&]token=)[^\s&\"']+", r"\1***", fmt % args)
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), message))

    def _authorized(self) -> bool:
        """Sunucuda auth_token ayarliysa istegi dogrular (Bearer / cookie / ?token=)."""
        token = getattr(self.server, "auth_token", None)
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer ") and secrets.compare_digest(header[7:], token):
            return True
        # Cookie duzgun ayristirilir (alt-dizi eslesmesi 'xmaestro_token' gibi
        # adlari yanlislikla kabul etmesin); karsilastirma sabit-zamanli.
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == "maestro_token" and secrets.compare_digest(value, token):
                return True
        query = parse_qs(urlparse(self.path).query)
        if secrets.compare_digest(query.get("token", [""])[0], token):
            # Ilk giris ?token= ile; sonraki istekler icin cookie birak.
            self._pending_auth_cookie = True
            return True
        return False

    def end_headers(self) -> None:
        if getattr(self, "_pending_auth_cookie", False):
            token = getattr(self.server, "auth_token", None)
            if token:
                self.send_header("Set-Cookie", f"maestro_token={token}; Path=/; HttpOnly; SameSite=Strict")
            self._pending_auth_cookie = False
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            return self._send_error("Yetkisiz erisim. Panele ?token=... ile girin.", HTTPStatus.UNAUTHORIZED)
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_static("index.html")
        if parsed.path.startswith("/static/"):
            return self._send_static(parsed.path.removeprefix("/static/"))
        if parsed.path == "/api/status":
            return self._send_json(self.app.status_payload())
        if parsed.path == "/api/diagnostics":
            return self._send_json(self.app.diagnostics_payload())
        if parsed.path == "/api/task-monitor":
            return self._send_json(self.app.task_monitor_payload())
        if parsed.path == "/api/processes":
            return self._send_json(self.app.processes_payload())
        if parsed.path == "/api/source/tree":
            return self._send_json(self.app.source_tree_payload())
        if parsed.path == "/api/workflow/templates":
            return self._send_json(self.app.workflow_templates_payload())
        if parsed.path == "/api/quality/report":
            return self._send_json({"ok": True, "quality": self.app.quality_summary_payload()})
        if parsed.path == "/api/webapp/status":
            return self._send_json({"ok": True, "webApp": self.app.webapp_summary_payload(), "detected": self.app.detect_webapp_payload({})})
        if parsed.path == "/api/file":
            query = parse_qs(parsed.query)
            name = query.get("name", [""])[0]
            try:
                return self._send_json(self.app.read_file(name))
            except Exception as exc:
                return self._send_error(str(exc), HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/runs":
            return self._send_json({"ok": True, "runs": load_run_records(self.app.project_dir)})
        if parsed.path == "/api/decisions":
            return self._send_json({"ok": True, "decisions": load_decisions(self.app.project_dir)})
        if parsed.path == "/api/events":
            return self._send_json({"ok": True, "events": load_events(self.app.project_dir)})
        if parsed.path == "/api/orchestration":
            return self._send_json({"ok": True, "orchestration": self.app.orchestration_payload()})
        if parsed.path == "/api/roles":
            return self._send_json({"ok": True, "roles": AGENT_ROLES})
        if parsed.path == "/api/packages":
            return self._send_json({"ok": True, "packages": list_delivery_packages(self.app.project_dir)})
        if parsed.path == "/api/package/download":
            query = parse_qs(parsed.query)
            name = query.get("name", [""])[0]
            if name:
                safe_name = Path(name).name
                path = Path(self.app.project_dir) / "packages" / safe_name
                if path.exists() and path.is_file():
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/zip")
                    # Ham 'name' degil dosya-sistemi icin dogrulanan ad kullanilir
                    # (CRLF header enjeksiyonuna kapi acilmasin).
                    self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.end_headers()
                    with path.open("rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
            return self._send_error("Not found", HTTPStatus.NOT_FOUND)
        if parsed.path == "/api/snapshots/files":
            query = parse_qs(parsed.query)
            snap_id = query.get("id", [""])[0]
            if snap_id:
                try:
                    s_dir = snapshot_files_dir(self.app.project_dir, snap_id)
                    files = [str(p.relative_to(s_dir)).replace("\\", "/") for p in s_dir.rglob("*") if p.is_file()]
                    return self._send_json({"ok": True, "files": sorted(files)})
                except Exception as exc:
                    return self._send_error(str(exc), HTTPStatus.BAD_REQUEST)
            return self._send_error("Missing id", HTTPStatus.BAD_REQUEST)
        return self._send_error("Not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            return self._send_error("Yetkisiz erisim. Panele ?token=... ile girin.", HTTPStatus.UNAUTHORIZED)
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/request":
                self.app.save_request(str(payload.get("text", "")))
                return self._send_json({"ok": True, "status": self.app.status_payload()})
            if parsed.path == "/api/chat":
                text = str(payload.get("text", "")).strip()
                if not text:
                    return self._send_error("Mesaj bos olamaz.", HTTPStatus.BAD_REQUEST)
                append_chat_entry(self.app.project_dir, "Kullanici", text)
                return self._send_json({"ok": True})
            if parsed.path == "/api/orchestration/memory":
                result = self.app.append_memory_note(str(payload.get("note", "")))
                return self._send_json({"ok": True, "orchestration": result})
            if parsed.path == "/api/orchestration/context-summary":
                return self._send_json(self.app.create_context_summary_payload())
            if parsed.path == "/api/orchestration/suggest":
                return self._send_json(self.app.suggest_agent_payload(str(payload.get("text", ""))))
            if parsed.path == "/api/orchestration/compare":
                return self._send_json(self.app.compare_agents_payload(payload))
            if parsed.path == "/api/ux/wizard-workflow":
                return self._send_json(self.app.wizard_workflow_payload(payload))
            if parsed.path == "/api/ux/error-action":
                return self._send_json(self.app.error_action_payload(payload))
            if parsed.path == "/api/quality/run":
                result = self.app.run_quality_audit(payload)
                return self._send_json({"ok": True, "result": result, "status": self.app.status_payload()})
            if parsed.path == "/api/quality/acceptance":
                result = self.app.run_acceptance_check(payload)
                return self._send_json({"ok": True, "result": result, "status": self.app.status_payload()})
            if parsed.path == "/api/quality/test-generation":
                return self._send_json(self.app.prepare_test_generation_workflow(payload))
            if parsed.path == "/api/webapp/preview":
                result = self.app.prepare_web_preview(payload)
                return self._send_json({"ok": True, "result": result, "status": self.app.status_payload()})
            if parsed.path == "/api/webapp/audit":
                result = self.app.run_webapp_audit(payload)
                return self._send_json({"ok": True, "result": result, "status": self.app.status_payload()})
            if parsed.path == "/api/webapp/stop-preview":
                return self._send_json(self.app.stop_web_preview())
            if parsed.path == "/api/webapp/ui-polish":
                return self._send_json(self.app.prepare_ui_polish_workflow(payload))
            if parsed.path == "/api/source/scan":
                source_path = str(payload.get("path", ""))
                meta = self.app.scan_source_path(source_path)
                return self._send_json({"ok": True, "source": meta, "status": self.app.status_payload()})
            if parsed.path == "/api/source/upload":
                files = payload.get("files")
                label = str(payload.get("label", "Secilen dosyalar"))
                meta = self.app.scan_uploaded_source(files, label)
                return self._send_json({"ok": True, "source": meta, "status": self.app.status_payload()})
            if parsed.path == "/api/source/clear":
                self.app.clear_source_context()
                return self._send_json({"ok": True, "status": self.app.status_payload()})
            if parsed.path == "/api/source/copy":
                result = self.app.copy_source_to_project()
                return self._send_json({"ok": True, "result": result, "status": self.app.status_payload()})
            if parsed.path == "/api/project/test":
                target = str(payload.get("target", ""))
                result = self.app.run_project_tests(target=target)
                return self._send_json({"ok": True, "result": result, "status": self.app.status_payload()})
            if parsed.path == "/api/workflow/apply-template":
                template_id = str(payload.get("templateId", ""))
                result = self.app.apply_workflow_template(template_id)
                return self._send_json({"ok": True, "templates": result, "status": self.app.status_payload()})
            if parsed.path == "/api/snapshots/diff":
                snap_id = str(payload.get("id", ""))
                rel_file = str(payload.get("file", ""))
                diff = snapshot_diff(self.app.project_dir, snap_id, rel_file)
                return self._send_json({"ok": True, "diff": diff})
            if parsed.path == "/api/snapshots/restore-file":
                snap_id = str(payload.get("id", ""))
                rel_file = str(payload.get("file", ""))
                restore_snapshot_files(self.app.project_dir, snap_id, [rel_file])
                return self._send_json({"ok": True, "status": self.app.status_payload()})
            if parsed.path == "/api/package/create":
                meta = create_delivery_package(self.app.project_dir)
                return self._send_json({"ok": True, "package": meta})
            if parsed.path == "/api/run/start":
                start_idx = int(payload.get("startIndex", 1))
                reset_state = bool(payload.get("resetState", start_idx == 1))
                use_checkpoints = bool(payload.get("useCheckpoints", True))
                request_text = payload.get("request")
                if isinstance(request_text, str):
                    self.app.save_request(request_text)
                self.app.start_run(start_idx=start_idx, reset_state=reset_state, use_checkpoints=use_checkpoints)
                return self._send_json({"ok": True})
            if parsed.path == "/api/run/stop":
                self.app.stop_run()
                return self._send_json({"ok": True})
            if parsed.path == "/api/run/force-complete":
                self.app.force_complete_event.set()
                return self._send_json({"ok": True})
            if parsed.path == "/api/run/force-fallback":
                self.app.force_fallback_event.set()
                return self._send_json({"ok": True})
            if parsed.path == "/api/run/decision":
                self.app.send_decision(str(payload.get("decision", "")))
                return self._send_json({"ok": True})
            if parsed.path == "/api/processes/stop-all":
                self.app.stop_all_processes()
                return self._send_json({"ok": True, "status": self.app.status_payload()})
            if parsed.path == "/api/state/repair":
                return self._send_json(self.app.state_repair_payload())
            if parsed.path == "/api/reset":
                self.app.reset_progress()
                return self._send_json({"ok": True})
            return self._send_error("Not found", HTTPStatus.NOT_FOUND)
        except (ValueError, RuntimeError, WorkflowError) as exc:
            return self._send_error(str(exc), HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            return self._send_error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Gecersiz JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON kok nesnesi sozluk olmali.")
        return data

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_error(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"ok": False, "error": message}, status)

    def _send_static(self, name: str) -> None:
        safe_name = name.strip("/").replace("\\", "/") or "index.html"
        if "/" in safe_name:
            path = (STATIC_DIR / safe_name).resolve()
        else:
            path = (STATIC_DIR / safe_name).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return self._send_error("Not found", HTTPStatus.NOT_FOUND)
        if not path.exists() or not path.is_file():
            return self._send_error("Not found", HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        raw = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(raw)


class MaestroServer(ThreadingHTTPServer):
    app: MaestroWebPanel
    auth_token: str | None = None


def create_server(
    host: str,
    port: int,
    project_dir: str | os.PathLike[str] | None = None,
    auth_token: str | None = None,
) -> MaestroServer:
    app = MaestroWebPanel(project_dir)
    server = MaestroServer((host, port), MaestroRequestHandler)
    server.app = app
    server.auth_token = auth_token
    app.server_host = host
    app.auth_enabled = bool(auth_token)
    app.server_port = server.server_port
    return server


def shutdown_server(server: MaestroServer) -> None:
    try:
        server.app.stop_run()
        server.app.stop_web_preview()
        worker = getattr(server.app, "worker", None)  # hic akis baslamadiysa worker olmayabilir
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=5)
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Maestro web panel")
    parser.add_argument("--host", default="127.0.0.1", help="Dinlenecek host")
    parser.add_argument("--port", type=int, default=8765, help="Dinlenecek port")
    parser.add_argument("--project-dir", default=None, help="Maestro proje klasoru")
    parser.add_argument("--open", action="store_true", help="Tarayicida otomatik ac")
    parser.add_argument("--token", default=None, help="API erisim token'i (yerel olmayan host'ta zorunlu)")
    args = parser.parse_args()

    # Guvenlik: panel yerel olmayan bir adreste dinliyorsa token zorunlu.
    # (Durdurma, snapshot geri yukleme, dosya okuma gibi guclu API'ler var.)
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    auth_token = args.token
    if args.host not in local_hosts and not auth_token:
        auth_token = secrets.token_urlsafe(24)
        print("UYARI: Panel yerel olmayan adreste dinliyor; erisim token'i otomatik uretildi.", flush=True)

    import socket
    import urllib.request
    import urllib.error
    
    url = f"http://{args.host}:{args.port}"
    is_running = False
    try:
        req = urllib.request.Request(f"{url}/api/status")
        with urllib.request.urlopen(req, timeout=1) as response:
            if response.status == 200:
                is_running = True
    except urllib.error.HTTPError:
        # 401 vb. HTTP cevabi geldiyse panel zaten calisiyor demektir.
        is_running = True
    except (urllib.error.URLError, socket.error):
        pass

    if is_running:
        print(f"Zaten calisan bir Maestro paneli bulundu: {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        return

    server = create_server(args.host, args.port, args.project_dir, auth_token=auth_token)
    url = f"http://{args.host}:{server.server_port}"
    if auth_token:
        url += f"/?token={auth_token}"
    print(f"Maestro web panel: {url}", flush=True)
    print(f"Proje: {server.app.project_dir}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor...", flush=True)
    finally:
        shutdown_server(server)


if __name__ == "__main__":
    main()
