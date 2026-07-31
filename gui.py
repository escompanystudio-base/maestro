#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Orkestra - Masaüstü uygulama (CustomTkinter Modern Tasarım).
Çalıştır: python gui.py  veya  uygulama.bat / uygulama.sh
"""

from __future__ import annotations

import difflib
import ast
import ctypes
import html
import importlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk

try:
    import winsound  # Windows sesli bildirim (stdlib)
except ImportError:  # Windows disi
    winsound = None

import workflow as WF
from constants import BUILTIN_WORKFLOWS, PROJECT_TEMPLATES
from orkestra import (
    BRIEF_QUESTIONS_FILE,
    CHAT_FILE,
    DEFAULT_BRIEF_QUESTIONS,
    GENERATED_WORKFLOW_FILE,
    LOG_DIR,
    STATE_FILE,
    REQUEST_FILE,
    WorkflowError,
    ANTIGRAVITY_OUTPUT_EXIT_GRACE_SECONDS,
    append_chat_entry,
    append_event,
    append_metric,
    append_run_record,
    append_terminal_history,
    assess_run_quality,
    antigravity_outputs_ready,
    app_data_dir,
    brief_hash,
    build_command,
    chat_path,
    check_inputs,
    classify_failure,
    compose_wizard_brief,
    create_delivery_package,
    create_snapshot,
    delete_named_workflow,
    ensure_chat_file,
    extract_last_handoff,
    expected_agent_commands_label,
    fallback_agent_for,
    find_tool,
    infer_completed_from_outputs,
    list_named_workflows,
    list_snapshots,
    load_metrics,
    kill_process_tree,
    load_brief_questions,
    load_generated_workflow,
    load_named_workflow,
    load_prompt_profiles,
    load_decisions,
    load_run_records,
    load_state,
    load_terminal_history,
    missing_required_tools,
    preflight_check,
    process_env,
    process_kwargs,
    produced_files,
    restore_snapshot,
    restore_snapshot_files,
    resolve_command,
    resolve_project_dir,
    read_user_request,
    record_stage_decision,
    retry_strategy,
    save_brief_questions,
    save_generated_workflow,
    save_named_workflow,
    save_prompt_profiles,
    save_state,
    save_structured_brief,
    save_user_request,
    snapshot_diff,
    next_stage_ref,
    stage_ref,
    validate_generated_workflow,
    validate_workflow,
    verify_outputs,
    usage_limit_notice,
    with_fallback_agent,
    workflow_hash,
    workflow_uses_request,
)
from logging_config import get_logger, setup_logging
from runner import run_agent_stage

# Tani amacli (traceback dahil) dosya logu; kullaniciya gosterilen ciktidan ayri.
logger = get_logger("gui")

# CustomTkinter Ayarları
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Tasarım tokenları: claude.ai benzeri AÇIK (light) tema — krem/beyaz zemin, koyu yazı.
BG = "#050609"
SURFACE = "#0B0F17"
SURFACE_2 = "#101622"
SURFACE_3 = "#161E2D"
EDITOR_BG = "#080B11"
BORDER = "#273244"
BORDER_SOFT = "#1A2230"
TEXT = "#F6F8FB"
TEXT_2 = "#D8DEE9"
ACCENT = "#22C55E"
ACCENT_BLUE = "#38BDF8"
WARN = "#F59E0B"
ERR = "#F87171"
PURPLE = "#A78BFA"
SUB = "#A7B0C0"
MUTED = "#6B7586"
HOVER = "#172033"
SELECTED = "#1E293B"

# PROJECT_TEMPLATES ve BUILTIN_WORKFLOWS constants.py modulune tasindi (Faz 2a).
# Yukaridaki import satirindan geliyorlar.

DIFF_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".next", LOG_DIR}
DIFF_SKIP_FILES = {STATE_FILE}
DIFF_TEXT_LIMIT = 500_000
ERROR_FILE = "hata.md"
AUTO_FIX_ATTEMPTS = 3
RUNTIME_CHECK_TIMEOUT = 8

def fmt_seconds(value: float | int | None) -> str:
    if value is None:
        return ""
    seconds = int(max(0, value))
    if seconds < 60:
        return f"{seconds}sn"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}dk {seconds:02d}sn"

class OrkestraApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.project_dir = resolve_project_dir()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        setup_logging(self.project_dir / LOG_DIR)  # tani amacli dosya logu (maestro.log)
        logger.info("GUI baslatildi: proje=%s", self.project_dir)

        self.log_q: queue.Queue[tuple[str, str | None]] = queue.Queue()
        # Worker -> UI cagri kuyrugu: worker thread'leri Tcl'e HIC dokunmaz;
        # ana thread _drain_log pompasi bunlari calistirir (yaris/RuntimeError yok).
        self.ui_q: queue.Queue[tuple[Any, tuple[Any, ...]]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.proc: subprocess.Popen[str] | None = None
        self.proc_lock = threading.Lock()
        self.preview_proc: subprocess.Popen[Any] | None = None
        self.preview_lock = threading.Lock()
        self.terminal_proc: subprocess.Popen[Any] | None = None
        self.terminal_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.decision_event = threading.Event()
        self.decision: str | None = None

        self.running = False
        self.closing = False
        self.running_index: int | None = None
        self.failed_index: int | None = None
        self.step_started_at: float | None = None
        self.stage_durations: dict[int, str] = {}
        self.chat_mtime: float | None = None
        self.files_mtime_token: tuple[Any, ...] | None = None
        self.preview_target: dict[str, Any] | None = None
        self.file_map_baseline: dict[str, tuple[float | None, int]] = {}
        self.file_map_token: tuple[Any, ...] | None = None
        self.metrics_token: tuple[Any, ...] | None = None
        self.snapshot_run_id = time.strftime("run_%Y%m%d_%H%M%S")
        self.active_workflow_data: dict[str, Any] | None = None
        self.pending_brief_questions: list[dict[str, Any]] = []
        self.pending_initial_request = ""
        self.pending_answers: list[dict[str, str]] = []
        self.max_attempts_var = tk.IntVar(value=1)
        self.long_step_warning_var = tk.BooleanVar(value=True)
        self.agent_fallback_var = tk.BooleanVar(value=True)
        self.auto_fix_var = tk.BooleanVar(value=True)

        root.title("AI Orkestra")
        root.geometry("1360x840")
        root.minsize(1180, 720)
        root.configure(fg_color=BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._setup_style()
        self._build_ui()
        self.refresh_stages()
        self.refresh_tools()
        self.root.after(100, self._drain_log)
        self.root.after(500, self._refresh_chat)
        self.root.after(900, self._refresh_files)
        self.root.after(1200, self._refresh_preview_state)
        self.root.after(1400, self._refresh_file_map)
        self.root.after(1700, self._refresh_metrics)
        self.root.after(2100, self._refresh_history)

    # ---------------- UI ----------------
    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Treeview",
            background=SURFACE_2,
            fieldbackground=SURFACE_2,
            foreground=TEXT_2,
            borderwidth=0,
            rowheight=38,
            font=("Segoe UI", 10),
            padding=0,
        )
        style.configure(
            "Treeview.Heading",
            background=SURFACE_3,
            foreground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 10, "bold"),
            padding=(8, 8),
        )
        style.map(
            "Treeview",
            background=[("selected", SELECTED)],
            foreground=[("selected", TEXT)],
        )
        style.configure("Vertical.TScrollbar", troughcolor=SURFACE, background=BORDER, bordercolor=SURFACE)

    def _build_ui(self) -> None:
        self._build_codex_ui()
        return

    def _build_codex_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        topbar = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        topbar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        topbar.columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(topbar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=18, pady=12)
        mark = ctk.CTkFrame(brand, width=30, height=30, fg_color=ACCENT, corner_radius=8)
        mark.pack(side="left", padx=(0, 10))
        mark.pack_propagate(False)
        ctk.CTkLabel(mark, text="M", text_color="#041108", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold")).pack(expand=True)
        ctk.CTkLabel(brand, text="Maestro", text_color=TEXT, font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")).pack(side="left")

        self.project_lbl = ctk.CTkLabel(topbar, text="", text_color=MUTED, font=ctk.CTkFont(family="Segoe UI", size=11))
        self.project_lbl.grid(row=0, column=1, sticky="w", padx=8, pady=12)
        ctk.CTkLabel(
            topbar,
            text="local agent workspace",
            text_color=MUTED,
            font=ctk.CTkFont(family="Consolas", size=12),
        ).grid(row=0, column=2, sticky="e", padx=18, pady=12)
        self._sync_project_dir()

        body = ctk.CTkFrame(self.root, fg_color=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        body.columnconfigure(0, weight=0, minsize=330)
        body.columnconfigure(1, weight=1, minsize=720)
        body.rowconfigure(0, weight=1)

        # Left rail: run timeline and stage inspector.
        left = ctk.CTkFrame(body, fg_color=SURFACE, border_width=1, border_color=BORDER_SOFT, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        ctk.CTkLabel(left, text="Workflow", text_color=TEXT, font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))

        tree_wrap = ctk.CTkFrame(left, fg_color="transparent")
        tree_wrap.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)

        self.stage_tree = ttk.Treeview(
            tree_wrap,
            columns=("status", "step", "agent", "time"),
            displaycolumns=("status", "step"),
            show="headings",
            selectmode="browse",
        )
        for key, text, width, anchor in (
            ("status", "", 42, "center"),
            ("step", "Adim", 245, "w"),
            ("agent", "Ajan", 72, "center"),
            ("time", "Sure", 68, "e"),
        ):
            self.stage_tree.heading(key, text=text)
            self.stage_tree.column(key, width=width, minwidth=width, anchor=anchor, stretch=(key == "step"))
        self.stage_tree.tag_configure("done", foreground=ACCENT)
        self.stage_tree.tag_configure("running", foreground=ACCENT_BLUE)
        self.stage_tree.tag_configure("failed", foreground=ERR)
        self.stage_tree.tag_configure("pending", foreground=SUB)
        self.stage_tree.grid(row=0, column=0, sticky="nsew")

        tree_sb = ttk.Scrollbar(tree_wrap, command=self.stage_tree.yview)
        self.stage_tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.grid(row=0, column=1, sticky="ns")

        self._stage_legend = "Secili adim yok.\nOkur/yazar, fallback ve checkpoint detaylari burada gorunur."
        self.stage_detail_lbl = ctk.CTkLabel(
            left,
            text=self._stage_legend,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=SUB,
            justify="left",
            anchor="w",
            wraplength=270,
        )
        self.stage_detail_lbl.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 14))
        self.stage_tree.bind("<<TreeviewSelect>>", self._on_stage_select)

        # Center: transcript first, composer always visible.
        center = ctk.CTkFrame(body, fg_color=SURFACE, border_width=1, border_color=BORDER_SOFT, corner_radius=12)
        center.grid(row=0, column=1, sticky="nsew", padx=0)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)

        center_head = ctk.CTkFrame(center, fg_color="transparent")
        center_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        center_head.columnconfigure(0, weight=1)
        ctk.CTkLabel(center_head, text="Akis", text_color=TEXT, font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(center_head, text="ajan transcript + kullanici notlari", text_color=MUTED, font=ctk.CTkFont(family="Segoe UI", size=11)).grid(row=1, column=0, sticky="w")

        self.chat = ctk.CTkScrollableFrame(center, fg_color=EDITOR_BG, corner_radius=10, border_width=1, border_color=BORDER_SOFT)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))
        self.chat.columnconfigure(0, weight=1)
        self._chat_cards = []
        self._chat_body_labels = []
        self.chat.bind("<Configure>", self._on_chat_resize)

        composer = ctk.CTkFrame(center, fg_color=SURFACE_2, corner_radius=12, border_width=1, border_color=BORDER_SOFT)
        composer.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))
        composer.columnconfigure(0, weight=1)

        composer_head = ctk.CTkFrame(composer, fg_color="transparent")
        composer_head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        composer_head.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            composer_head,
            text=f"Mesaj / Is Istegi ({REQUEST_FILE})",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        self.b_save_request = ctk.CTkButton(
            composer_head,
            text="Kaydet",
            command=self.on_save_request,
            fg_color="transparent",
            text_color=ACCENT_BLUE,
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            corner_radius=8,
            width=76,
            height=28,
        )
        self.b_save_request.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.b_send_chat = ctk.CTkButton(
            composer_head,
            text="Sohbete ekle",
            command=self.on_send_chat_message,
            fg_color="transparent",
            text_color=ACCENT,
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            corner_radius=8,
            width=112,
            height=28,
        )
        self.b_send_chat.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.request_input = ctk.CTkTextbox(
            composer,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
            height=112,
            fg_color=EDITOR_BG,
            text_color=TEXT_2,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
            undo=True,
        )
        self.request_input.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 8))
        self._load_request_input()

        send_row = ctk.CTkFrame(composer, fg_color="transparent")
        send_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        send_row.columnconfigure(1, weight=1)
        self.template_select = ctk.CTkOptionMenu(
            send_row,
            values=["Sablon sec"] + list(PROJECT_TEMPLATES),
            command=self.on_template_selected,
            fg_color=SURFACE_3,
            button_color=BORDER,
            button_hover_color=HOVER,
            text_color=TEXT_2,
            width=180,
        )
        self.template_select.grid(row=0, column=0, sticky="w")
        self.template_select.set("Sablon sec")
        ctk.CTkLabel(send_row, text="Enter = gonder", text_color=MUTED, font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w", padx=10)
        self.b_send = ctk.CTkButton(
            send_row,
            text="Gonder",
            command=self._on_composer_send,
            fg_color=ACCENT,
            text_color="#041108",
            hover_color="#4ADE80",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            corner_radius=9,
            width=108,
            height=38,
        )
        self.b_send.grid(row=0, column=2, sticky="e")
        self.request_input.bind("<Return>", self._on_composer_send)

        # Sidebar controls: Codex-like, the main canvas stays focused on the thread.
        right = ctk.CTkFrame(left, fg_color=SURFACE_2, border_width=1, border_color=BORDER_SOFT, corner_radius=10)
        right.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Run controls", text_color=TEXT, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        self.status = ctk.CTkLabel(right, text="Sistem hazir.", font=ctk.CTkFont(size=12), text_color=SUB, anchor="w", justify="left", wraplength=280)
        self.status.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))

        progress_box = ctk.CTkFrame(right, fg_color=SURFACE_2, corner_radius=10, border_width=1, border_color=BORDER_SOFT)
        progress_box.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        progress_box.columnconfigure(0, weight=1)
        self.progress_lbl = ctk.CTkLabel(progress_box, text="Hazir", font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_2)
        self.progress_lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.progress = ctk.CTkProgressBar(progress_box, mode="determinate", height=10, corner_radius=5, progress_color=ACCENT_BLUE, fg_color=SURFACE_3)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.checkpoint_var = tk.BooleanVar(value=True)
        self.checkpoint_chk = ctk.CTkSwitch(
            right,
            text="Checkpointlerde dur",
            variable=self.checkpoint_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            progress_color=ACCENT_BLUE,
            text_color=TEXT_2,
        )
        self.checkpoint_chk.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))

        controls = ctk.CTkFrame(right, fg_color="transparent")
        controls.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.b_start = self._btn(controls, "Baslat", self.on_start, ACCENT)
        self.b_wizard = self._btn(controls, "✨ Sihirbaz", self.on_start_wizard, PURPLE)
        self.b_resume = self._btn(controls, "Devam", self.on_resume, ACCENT_BLUE)
        self.b_from = self._btn(controls, "Adimdan", self.on_from, ACCENT_BLUE)
        self.b_recover = self._btn(controls, "Toparla", self.on_recover, WARN)

        tools_row = ctk.CTkFrame(right, fg_color="transparent")
        tools_row.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.b_preview = self._btn(tools_row, "Onizleme", self.on_preview, SUB)
        self.b_tools = self._btn(tools_row, "Araclar", self._open_tools, SUB)
        self.b_limits = self._btn(tools_row, "Limitler", self.on_limit_settings, SUB)

        edit_row = ctk.CTkFrame(right, fg_color="transparent")
        edit_row.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.b_roles = self._btn(edit_row, "Roller", self.on_edit_agent_roles, PURPLE)
        self.b_workflow = self._btn(edit_row, "Workflow", self.on_edit_workflow, PURPLE)
        self.b_reset = self._btn(edit_row, "Sifirla", self.on_reset, WARN)

        self.ctrl = ctk.CTkFrame(right, fg_color=SURFACE_2, corner_radius=10, border_width=1, border_color=BORDER_SOFT)
        self.ctrl.grid(row=7, column=0, sticky="ew", padx=12, pady=(2, 10))
        self.b_continue = self._btn(self.ctrl, "Devam", lambda: self._decide("continue"), ACCENT)
        self.b_retry = self._btn(self.ctrl, "Tekrarla", lambda: self._decide("retry"), WARN)
        self.b_stop = self._btn(self.ctrl, "Durdur", self.on_stop, ERR)
        self._set_ctrl(False)

        self.tools_lbl = ctk.CTkLabel(right, text="", text_color=SUB, font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), anchor="w", justify="left", wraplength=280)
        self.tools_lbl.grid(row=8, column=0, sticky="ew", padx=12, pady=(4, 12))

        # Advanced tools live in a separate window to keep the main surface clean.
        self.tools_win = ctk.CTkToplevel(self.root)
        self.tools_win.title("Araclar")
        self.tools_win.geometry("1120x740")
        self.tools_win.configure(fg_color=BG)
        self.tools_win.withdraw()
        self.tools_win.protocol("WM_DELETE_WINDOW", self.tools_win.withdraw)
        self.tools_win.columnconfigure(0, weight=1)
        self.tools_win.rowconfigure(0, weight=1)
        work_tabs = ctk.CTkTabview(
            self.tools_win,
            corner_radius=12,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER_SOFT,
            segmented_button_fg_color=SURFACE_2,
            segmented_button_selected_color=SELECTED,
            segmented_button_selected_hover_color=HOVER,
            segmented_button_unselected_color=SURFACE_2,
            segmented_button_unselected_hover_color=HOVER,
            text_color=TEXT,
        )
        work_tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.tab_log = work_tabs.add("Teknik Log")
        self.tab_files = work_tabs.add("Dosyalar")
        self.tab_preview = work_tabs.add("Onizleme")
        self.tab_market = work_tabs.add("Marketplace")
        self.tab_metrics = work_tabs.add("Performans")
        self.tab_filemap = work_tabs.add("Dosya Haritasi")
        self.tab_terminal = work_tabs.add("Terminal")
        self.tab_history = work_tabs.add("Gecmis")
        self.tab_kanban = work_tabs.add("İş Kartları")
        self.tab_prompts = work_tabs.add("Promptlar")
        self.tab_setup = work_tabs.add("Kurulum")
        for tab in (
            self.tab_log,
            self.tab_files,
            self.tab_preview,
            self.tab_market,
            self.tab_metrics,
            self.tab_filemap,
            self.tab_terminal,
            self.tab_history,
            self.tab_kanban,
            self.tab_prompts,
            self.tab_setup,
        ):
            tab.columnconfigure(0, weight=1)
            tab.rowconfigure(0, weight=1)

        self.tab_log.rowconfigure(0, weight=1)
        self.log = ctk.CTkTextbox(
            self.tab_log,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
            fg_color=EDITOR_BG,
            text_color=TEXT_2,
            corner_radius=8,
            border_width=1,
            border_color=BORDER_SOFT,
        )
        self.log.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.log.configure(state="disabled")
        self.log.tag_config("ok", foreground=ACCENT)
        self.log.tag_config("warn", foreground=WARN)
        self.log.tag_config("err", foreground=ERR)
        self.log.tag_config("accent", foreground=ACCENT_BLUE)
        self.log.tag_config("sub", foreground=SUB)
        self.log.tag_config("muted", foreground=MUTED)

        self._build_files_tab()
        self._build_preview_tab()
        self._build_marketplace_tab()
        self._build_metrics_tab()
        self._build_file_map_tab()
        self._build_terminal_tab()
        self._build_history_tab()
        self._build_prompts_tab()
        self._build_setup_tab()
        self._build_kanban_tab()

        # Sihirbaz seridi (canli UI): akisin neresinde oldugunu tek bakista gosterir.
        wizard_strip = ctk.CTkFrame(topbar, fg_color="transparent")
        wizard_strip.grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 8))
        self._phase_labels = {}
        for pos, (key, text) in enumerate(
            [
                ("istek", "İstek"),
                ("sorular", "Sorular"),
                ("workflow", "Workflow onayı"),
                ("calistir", "Çalıştır"),
                ("kontrol", "Kontrol"),
                ("teslim", "Teslim"),
            ]
        ):
            if pos:
                ctk.CTkLabel(wizard_strip, text="→", text_color=BORDER, font=ctk.CTkFont(size=12)).pack(side="left", padx=6)
            lbl = ctk.CTkLabel(wizard_strip, text=text, text_color=MUTED, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"))
            lbl.pack(side="left")
            self._phase_labels[key] = lbl
        self.b_package = ctk.CTkButton(
            wizard_strip, text="📦 Teslim paketi", command=self.on_create_package,
            fg_color=ACCENT, text_color="#FFFFFF", hover_color="#15803D",
            corner_radius=8, width=132, height=26, font=ctk.CTkFont(size=12, weight="bold"),
        )
        # Basit / Uzman mod anahtari (kalici: .maestro_ui.json).
        self.expert_var = tk.BooleanVar(value=bool(self._load_ui_config().get("expert", True)))
        ctk.CTkSwitch(
            wizard_strip, text="Uzman modu", variable=self.expert_var,
            command=self.on_toggle_expert, font=ctk.CTkFont(size=11),
            progress_color=ACCENT_BLUE, width=46,
        ).pack(side="left", padx=(28, 0))

        self._set_phase("istek")
        self._apply_ui_mode()

        return

        # HEADER

    def _btn(self, parent: tk.Widget, text: str, cmd: Any, color: str) -> ctk.CTkButton:
        filled = color in (ACCENT, ACCENT_BLUE)
        fg = color if filled else "transparent"
        text_color = BG if filled else color
        border_color = color if not filled else color
        hover = "#16A34A" if color == ACCENT else "#0EA5E9" if color == ACCENT_BLUE else HOVER
        btn = ctk.CTkButton(
            parent, text=text, command=cmd, fg_color=fg,
            text_color=text_color, hover_color=hover, border_width=1.2,
            border_color=border_color, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            corner_radius=7, width=88, height=36
        )
        btn.pack(side="left", padx=4)
        return btn

    def _open_tools(self) -> None:
        try:
            self.tools_win.deiconify()
            self.tools_win.lift()
            self.tools_win.focus_force()
        except Exception as exc:
            logger.debug("Araclar penceresi acilamadi: %s", exc)

    def _notify(self, kind: str) -> None:
        """Is bitti/hata/checkpoint bildirimi: ses + gorev cubugu yanip sonme (stdlib)."""
        try:
            if winsound is not None:
                sound = {
                    "done": winsound.MB_ICONASTERISK,
                    "error": winsound.MB_ICONHAND,
                    "checkpoint": winsound.MB_ICONEXCLAMATION,
                }.get(kind, winsound.MB_OK)
                winsound.MessageBeep(sound)
            if os.name == "nt":
                class _FLASHWINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p),
                        ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                        ("dwTimeout", ctypes.c_uint),
                    ]
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                info = _FLASHWINFO(ctypes.sizeof(_FLASHWINFO), hwnd, 3, 5, 0)  # FLASHW_ALL x5
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception as exc:
            logger.debug("Bildirim verilemedi: %s", exc)

    def _ui_config_path(self) -> Path:
        return Path(__file__).resolve().parent / ".maestro_ui.json"

    def _load_ui_config(self) -> dict[str, Any]:
        try:
            p = self._ui_config_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("UI ayari okunamadi: %s", exc)
        return {}

    def on_toggle_expert(self) -> None:
        self._apply_ui_mode()
        try:
            self._ui_config_path().write_text(
                json.dumps({"expert": bool(self.expert_var.get())}), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("UI ayari yazilamadi: %s", exc)

    def _apply_ui_mode(self) -> None:
        """Basit mod: sadece istek + baslat + sonuc. Uzman mod: tum operasyon butonlari."""
        expert = bool(self.expert_var.get())
        for name in ("b_from", "b_recover", "b_preview", "b_tools", "b_limits", "b_roles", "b_workflow", "b_reset"):
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                if expert:
                    w.pack(side="left", padx=4)
                else:
                    w.pack_forget()
            except Exception as exc:
                logger.debug("Mod uygulanamadi (%s): %s", name, exc)

    def on_start_wizard(self) -> None:
        """Baslangic sihirbazi: tip/platform/tasarim/test secimleriyle istegi zenginlestirip baslatir."""
        if self.running:
            return
        win = ctk.CTkToplevel(self.root)
        win.title("Başlangıç sihirbazı")
        win.geometry("540x430")
        win.configure(fg_color=BG)
        win.grab_set()
        ctk.CTkLabel(win, text="Ne yapmak istiyorsun?", text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=18, pady=(14, 4))
        istek_box = ctk.CTkTextbox(win, height=70, wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        istek_box.pack(fill="x", padx=18)
        mevcut = self.request_input.get("1.0", "end-1c").strip()
        if mevcut:
            istek_box.insert("1.0", mevcut)
        secimler: dict[str, Any] = {}
        for etiket, secenekler in (
            ("Proje tipi", ["Farketmez", "Web uygulaması", "Web sitesi / Landing", "Masaüstü uygulama", "Mobil uygulama", "Oyun", "API / Servis"]),
            ("Hedef platform", ["Farketmez", "Web", "Windows", "Android/iOS", "Terminal/CLI"]),
            ("Tasarım tarzı", ["Farketmez", "Modern-minimal", "Kurumsal", "Renkli / eğlenceli", "Koyu tema"]),
            ("Test beklentisi", ["Farketmez", "Otomatik test istiyorum", "Test gerekmez"]),
        ):
            row = ctk.CTkFrame(win, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=4)
            ctk.CTkLabel(row, text=etiket, text_color=SUB, width=120, anchor="w").pack(side="left")
            menu = ctk.CTkOptionMenu(row, values=secenekler, fg_color=SURFACE_3, button_color=BORDER, button_hover_color=HOVER, text_color=TEXT_2)
            menu.set(secenekler[0])
            menu.pack(side="left", fill="x", expand=True)
            secimler[etiket] = menu

        def basla() -> None:
            istek = istek_box.get("1.0", "end-1c").strip()
            if not istek:
                messagebox.showerror("İstek yok", "Önce ne yapmak istediğini yaz.")
                return
            full = compose_wizard_brief(
                istek,
                proje_tipi=secimler["Proje tipi"].get(),
                platform=secimler["Hedef platform"].get(),
                tasarim=secimler["Tasarım tarzı"].get(),
                test_beklentisi=secimler["Test beklentisi"].get(),
            )
            self.request_input.delete("1.0", "end")
            self.request_input.insert("1.0", full)
            win.destroy()
            self._begin_smart_start()

        ctk.CTkButton(win, text="▶  Workflow oluştur ve başla", command=basla, fg_color=ACCENT, text_color="#FFFFFF", hover_color="#15803D", height=40).pack(fill="x", padx=18, pady=(14, 6))
        ctk.CTkButton(win, text="Vazgeç", command=win.destroy, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=100).pack(pady=(0, 14))

    def _run_adhoc_stage(self, stage: dict[str, Any], aciklama: str) -> None:
        """Ana akisi/state'i BOZMADAN tek seferlik ajan kosusu (hata cozum aksiyonlari)."""
        if self.running:
            messagebox.showinfo("Meşgul", "Önce mevcut akış bitsin veya durdurulsun.")
            return
        self.stop_event.clear()
        self._busy(True)
        self._set_ctrl(True, allow_decide=False)
        self.q(f"\n=== {aciklama} ===", "accent")

        def worker() -> None:
            current: list[Any] = [None]

            def register_proc(p: Any) -> None:
                # Durdur butonu adhoc cocugu da oldurebilsin.
                with self.proc_lock:
                    if p is None:
                        if self.proc is current[0]:
                            self.proc = None
                    else:
                        current[0] = p
                        self.proc = p

            try:
                ok, elapsed, reason, _out = run_agent_stage(
                    stage, 1, 1, [stage], self.project_dir,
                    stop_event=self.stop_event, log=self.q,
                    on_proc=register_proc,
                )
                self.q(("✓ " if ok else "! ") + f"{aciklama} bitti ({fmt_seconds(elapsed)}, {reason}).", "ok" if ok else "err")
                self.ui(self._notify, "done" if ok else "error")
            except Exception as exc:
                logger.exception("Adhoc kosu hatasi")
                self.q(f"! {aciklama} hata verdi: {exc}", "err")
            finally:
                self.ui(self._busy, False)
                self.ui(self._set_ctrl, False)
                self.ui(self._force_refresh_files)

        threading.Thread(target=worker, daemon=True).start()

    def _run_project_checks(self) -> None:
        """Proje icinde compileall + (varsa) pytest kosar; token harcamaz."""
        if self.running:
            messagebox.showinfo("Meşgul", "Önce mevcut akış bitsin.")
            return
        self._busy(True)

        def worker() -> None:
            try:
                komutlar = [["python", "-m", "compileall", "-q", "-x", "(node_modules|venv|__pycache__)", "."]]
                if (self.project_dir / "pytest.ini").exists() or (self.project_dir / "tests").exists():
                    komutlar.append(["python", "-m", "pytest", "-q"])
                for cmd in komutlar:
                    self.q("$ " + " ".join(cmd), "sub")
                    # Popen + kayit: Durdur/Kapat 180sn'lik pytest'i kesebilsin.
                    proc = subprocess.Popen(
                        cmd, cwd=self.project_dir, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        env=process_env(), **process_kwargs(),
                    )
                    with self.proc_lock:
                        self.proc = proc
                    try:
                        out, _ = proc.communicate(timeout=180)
                    except subprocess.TimeoutExpired:
                        kill_process_tree(proc)
                        out, _ = proc.communicate()
                    finally:
                        with self.proc_lock:
                            if self.proc is proc:
                                self.proc = None
                    for line in (out or "").strip().splitlines()[-8:]:
                        self.q("  " + line)
                    if proc.returncode != 0:
                        self.q("! Kontroller başarısız.", "err")
                        self.ui(self._notify, "error")
                        return
                self.q("✓ Kontroller geçti.", "ok")
                self.ui(self._notify, "done")
            except Exception as exc:
                self.q(f"! Kontrol hatası: {exc}", "err")
            finally:
                self.ui(self._busy, False)

        threading.Thread(target=worker, daemon=True).start()

    def _show_error_actions(self, idx: int, stage: dict[str, Any], label: str) -> None:
        """Hata sonrasi hazir cozum aksiyonlari paneli."""
        if self.closing:
            return
        win = ctk.CTkToplevel(self.root)
        win.title("Hata çözüm aksiyonları")
        win.geometry("560x310")
        win.configure(fg_color=BG)
        ctk.CTkLabel(
            win, text=f"{idx}. adım başarısız ({label}). Ne yapalım?",
            text_color=TEXT_2, justify="left",
        ).pack(anchor="w", padx=18, pady=(16, 10))

        def kapat_ve(fn: Any) -> None:
            win.destroy()
            fn()

        def claude_fix() -> None:
            self._run_adhoc_stage(
                {
                    "name": "Hata Düzeltme", "agent": "claude",
                    "prompt": (
                        f"Proje klasöründeki son hatayı düzelt. Önce sohbet.md ve varsa {ERROR_FILE} dosyasını oku; "
                        f"{idx}. adım ({stage.get('name', '')}) '{label}' sebebiyle başarısız oldu. "
                        "Sadece hatayı gider, gereksiz refactor yapma."
                    ),
                    "reads": [], "writes": [], "timeout": 900,
                },
                "Claude ile düzeltme",
            )

        def codex_review() -> None:
            self._run_adhoc_stage(
                {
                    "name": "Kod Kontrolü", "agent": "codex",
                    "prompt": "Projedeki kodu incele; hata, eksik ve riskleri kontrol.md dosyasına madde madde yaz. Kodu değiştirme.",
                    "reads": [], "writes": ["kontrol.md"], "timeout": 900,
                },
                "Codex kontrolü",
            )

        def snapshot_don() -> None:
            rows = list_snapshots(self.project_dir)
            if not rows:
                messagebox.showinfo("Snapshot yok", "Henüz snapshot alınmamış.")
                return
            if messagebox.askyesno("Geri dön", f"Son snapshot'a dönülsün mü?\n{rows[0].get('id')}"):
                restore_snapshot(self.project_dir, str(rows[0].get("id")))
                self._force_refresh_files()
                self.set_status("Snapshot'a dönüldü.", WARN)

        for text, fn, color in (
            ("🛠  Claude ile düzelt", claude_fix, PURPLE),
            ("🔍  Codex'e kontrol ettir", codex_review, ACCENT_BLUE),
            ("⏪  Son snapshot'a dön", snapshot_don, WARN),
            ("🧪  Testleri tekrar çalıştır", self._run_project_checks, ACCENT),
        ):
            ctk.CTkButton(
                win, text=text, command=lambda f=fn: kapat_ve(f),
                fg_color="transparent", border_width=1, border_color=color,
                text_color=color, hover_color=HOVER, height=38, anchor="w",
            ).pack(fill="x", padx=18, pady=4)
        ctk.CTkButton(win, text="Kapat", command=win.destroy, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=90).pack(pady=(8, 12))

    def _build_kanban_tab(self) -> None:
        from ui_tabs import kanban_tab

        kanban_tab.build(self)

    def _refresh_kanban(self) -> None:
        """Is kartlari: adimlar Trello benzeri kolonlarda (bekliyor/calisiyor/kontrol/tamam)."""
        if not hasattr(self, "kanban_cols"):
            return
        try:
            stages = self._current_stages()
            state = load_state(self.project_dir)
            done = set(state.get("completed", [])) if state.get("workflow_hash") == workflow_hash(stages) else set()
            for col in self.kanban_cols.values():
                for w in list(col.winfo_children())[1:]:  # kolon basligi haric
                    w.destroy()
            renkler = {"bekliyor": MUTED, "calisiyor": ACCENT_BLUE, "kontrol": WARN, "tamam": ACCENT}
            for i, s in enumerate(stages, 1):
                if i == self.failed_index:
                    key = "kontrol"
                elif i == self.running_index:
                    key = "calisiyor"
                elif i in done:
                    key = "tamam"
                else:
                    key = "bekliyor"
                kart = ctk.CTkFrame(self.kanban_cols[key], fg_color=SURFACE_2, corner_radius=8, border_width=1, border_color=BORDER_SOFT)
                kart.pack(fill="x", padx=6, pady=4)
                ctk.CTkLabel(kart, text=f"{i}. {s.get('name', '')}", text_color=TEXT_2, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=8, pady=(6, 0))
                sure = self.stage_durations.get(i, "")
                ctk.CTkLabel(kart, text=f"{s.get('agent', '')}  {sure}", text_color=renkler[key], anchor="w", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=8, pady=(0, 6))
        except Exception as exc:
            logger.debug("Kanban yenilenemedi: %s", exc)

    def _set_phase(self, phase: str) -> None:
        """Sihirbaz seridinde aktif fazi vurgular; oncekiler yesil, sonrakiler soluk."""
        order = ["istek", "sorular", "workflow", "calistir", "kontrol", "teslim"]
        if phase not in order:
            return
        labels = getattr(self, "_phase_labels", None)
        if not labels:
            return  # serit bu arayuz varyantinda kurulmadiysa sessizce atla
        current = order.index(phase)
        for i, key in enumerate(order):
            lbl = labels.get(key)
            if lbl is None:
                continue
            if i < current:
                lbl.configure(text_color=ACCENT)
            elif i == current:
                lbl.configure(text_color=ACCENT_BLUE)
            else:
                lbl.configure(text_color=MUTED)
        try:
            if phase == "teslim":
                self.b_package.pack(side="left", padx=(16, 0))
            else:
                self.b_package.pack_forget()
        except Exception as exc:
            logger.debug("Teslim butonu guncellenemedi: %s", exc)

    def on_create_package(self) -> None:
        """Tamamlanan isi tek zip'e paketler (project/packages/ altina)."""
        try:
            meta = create_delivery_package(self.project_dir)
            name = meta.get("name", "paket") if isinstance(meta, dict) else str(meta)
            self.q(f"Teslim paketi olusturuldu: {name}", "ok")
            messagebox.showinfo(
                "Teslim paketi",
                f"Paket hazır: {name}\nKonum: {self.project_dir / 'packages'}",
            )
        except Exception as exc:
            logger.exception("Teslim paketi olusturulamadi")
            messagebox.showerror("Teslim paketi", str(exc))

    def _record_run(self, status: str, stages: list[dict[str, Any]], error: str = "") -> None:
        """Her calistirmayi runs.jsonl'a ozetler (Araclar > Gecmis > Calistirma Gecmisi)."""
        try:
            state = load_state(self.project_dir)
            try:
                # Worker'dan okunur; ana thread ayni anda yeni anahtar eklerse
                # bir kez daha dene (kucuk pencere, kopya yeterli).
                durations = dict(self.stage_durations)
            except RuntimeError:
                durations = dict(self.stage_durations)
            quality = assess_run_quality(self.project_dir, stages, status, error)
            if status == "complete":
                tag = "ok" if quality["category"] == "hazir" else "warn"
                self.q(f"🏷 Sonuç kalite etiketi: {quality['label']}", tag)
            append_run_record(
                self.project_dir,
                {
                    "run_id": self.snapshot_run_id,
                    "status": status,
                    "quality": quality["label"],
                    "error": error,
                    "request": read_user_request(self.project_dir)[:200],
                    "workflow_hash": str(state.get("workflow_hash") or "")[:12],
                    "stages_total": len(stages),
                    "stages_done": len([s for s in state.get("completed", []) if isinstance(s, int)]),
                    "agents": [str(s.get("agent", "?")) for s in stages],
                    "durations": {str(k): v for k, v in durations.items()},
                    "produced": produced_files(self.project_dir, stages),
                },
            )
            append_event(self.project_dir, "run_finished", run_id=self.snapshot_run_id, status=status, error=error)
        except Exception as exc:
            logger.debug("Run kaydi yazilamadi: %s", exc)

    def on_recover(self) -> None:
        """Yarim kalan isi toparlama sihirbazi: 4 kurtarma yolu tek yerde."""
        if self.running:
            return
        stages = self._current_stages()
        try:
            validate_workflow(stages)
        except WorkflowError as exc:
            messagebox.showerror("Workflow hatası", str(exc))
            return
        state = load_state(self.project_dir)
        same = state.get("workflow_hash") == workflow_hash(stages)
        done = [s for s in state.get("completed", []) if isinstance(s, int)] if same else []
        inferred = infer_completed_from_outputs(self.project_dir, stages)
        nxt = min(len(done) + 1, len(stages))

        win = ctk.CTkToplevel(self.root)
        win.title("Yarım işi toparla")
        win.geometry("620x360")
        win.configure(fg_color=BG)
        win.grab_set()
        ctk.CTkLabel(
            win,
            text=(
                f"Kayıtlı ilerleme: {len(done)}/{len(stages)} adım tamamlanmış.\n"
                f"Dosyalara göre tamamlanmış görünen: {len(inferred)}/{len(stages)} adım."
            ),
            text_color=TEXT_2, justify="left",
        ).pack(anchor="w", padx=18, pady=(16, 10))

        def act(fn: Any) -> None:
            win.destroy()
            fn()

        def resume() -> None:
            self._launch(start_idx=max(len(done) + 1, 1), stages=stages, reset_state=False, save_request=False)

        def by_files() -> None:
            save_state(self.project_dir, {"completed": inferred, "workflow_hash": workflow_hash(stages)})
            self.refresh_stages()
            self._launch(start_idx=len(inferred) + 1, stages=stages, reset_state=False, save_request=False)

        def retry_step() -> None:
            idx = self.failed_index or max(len(done), 1)
            st2 = load_state(self.project_dir)
            st2["completed"] = [x for x in st2.get("completed", []) if x != idx]
            save_state(self.project_dir, st2)
            self._launch(start_idx=idx, stages=stages, reset_state=False, save_request=False)

        def with_fallback() -> None:
            idx = nxt
            st = dict(stages[idx - 1])
            fb = self._planned_fallback(st)
            if not fb or not find_tool(fb):
                messagebox.showinfo("Fallback yok", f"{st.get('agent')} için kullanılabilir fallback ajan yok.")
                return
            new_stages = list(stages)
            new_stages[idx - 1] = with_fallback_agent(st, fb)
            self._launch(start_idx=idx, stages=new_stages, reset_state=False, save_request=False)

        for text, fn, color in (
            ("▶  Son başarılı adımdan devam et", resume, ACCENT),
            ("🗂  Dosyalara göre toparla ve devam et", by_files, ACCENT_BLUE),
            ("↺  Sıradaki/başarısız adımı tekrar çalıştır", retry_step, WARN),
            (f"🔀  Sıradaki adımı fallback ajanla çalıştır", with_fallback, PURPLE),
        ):
            ctk.CTkButton(
                win, text=text, command=lambda f=fn: act(f),
                fg_color="transparent", border_width=1, border_color=color,
                text_color=color, hover_color=HOVER, height=40, anchor="w",
            ).pack(fill="x", padx=18, pady=5)
        ctk.CTkButton(
            win, text="Vazgeç", command=win.destroy, fg_color="transparent",
            border_width=1, border_color=SUB, text_color=SUB, width=100,
        ).pack(pady=(10, 14))

    def _on_composer_send(self, event: Any = None) -> str:
        # Enter / Gönder: isteği gönder ve akışı başlat (sohbet hissi).
        # Shift+Enter bu binding'i tetiklemez -> metin kutusuna yeni satır ekler.
        if not self.running:
            self.on_start()
        return "break"

    def _build_files_tab(self) -> None:
        from ui_tabs import files_tab

        files_tab.build(self)

    def _build_preview_tab(self) -> None:
        from ui_tabs import preview_tab

        preview_tab.build(self)

    def _build_marketplace_tab(self) -> None:
        from ui_tabs import marketplace_tab

        marketplace_tab.build(self)

    def _build_metrics_tab(self) -> None:
        from ui_tabs import metrics_tab

        metrics_tab.build(self)

    def _build_file_map_tab(self) -> None:
        from ui_tabs import file_map_tab

        file_map_tab.build(self)

    def _build_terminal_tab(self) -> None:
        from ui_tabs import terminal_tab

        terminal_tab.build(self)

    def _build_history_tab(self) -> None:
        from ui_tabs import history_tab

        history_tab.build(self)

    def _build_prompts_tab(self) -> None:
        from ui_tabs import prompts_tab

        prompts_tab.build(self)

    def _build_setup_tab(self) -> None:
        from ui_tabs import setup_tab

        setup_tab.build(self)

    def on_template_selected(self, value: str) -> None:
        if value not in PROJECT_TEMPLATES:
            return
        current = self._request_text().strip() if hasattr(self, "request_input") else ""
        if current and not messagebox.askyesno("Sablon", "Mevcut istek metni sablonla degissin mi?"):
            self.template_select.set("Sablon sec")
            return
        self.request_input.configure(state="normal")
        self.request_input.delete("1.0", "end")
        self.request_input.insert("1.0", PROJECT_TEMPLATES[value])
        self.template_select.set(value)
        self.set_status(f"{value} sablonu istek alanina yerlestirildi.", ACCENT_BLUE)

    def on_limit_settings(self) -> None:
        win = ctk.CTkToplevel(self.root)
        win.title("Limitler")
        win.geometry("460x320")
        win.minsize(420, 280)
        win.grab_set()
        win.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            win,
            text="Adim Limitleri",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 8))

        win.configure(fg_color=BG)
        body = ctk.CTkFrame(win, corner_radius=10, fg_color=SURFACE, border_width=1, border_color=BORDER_SOFT)
        body.grid(row=1, column=0, sticky="ew", padx=20, pady=8)
        body.columnconfigure(1, weight=1)

        ctk.CTkLabel(body, text="Maksimum deneme").grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))
        attempts_menu = ctk.CTkOptionMenu(
            body,
            values=["1", "2", "3"],
            command=lambda selected: self.max_attempts_var.set(int(selected)),
            width=90,
        )
        attempts_menu.set(str(self._max_attempts()))
        attempts_menu.grid(row=0, column=1, sticky="w", padx=14, pady=(14, 8))

        ctk.CTkSwitch(
            body,
            text="Uzun adim baslamadan uyar",
            variable=self.long_step_warning_var,
            progress_color=ACCENT_BLUE,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=8)
        ctk.CTkSwitch(
            body,
            text="Gemini -> Claude, Claude -> Codex fallback",
            variable=self.agent_fallback_var,
            progress_color=ACCENT_BLUE,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=14, pady=(8, 14))
        ctk.CTkSwitch(
            body,
            text="Kodlama sonrasi hata yakala ve Claude'a duzelttir",
            variable=self.auto_fix_var,
            progress_color=ACCENT_BLUE,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 14))

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 18))
        ctk.CTkButton(bottom, text="Kapat", command=win.destroy, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=110, corner_radius=7).pack(side="right")

    def _format_size(self, size: int | float | None) -> str:
        value = float(size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
            value /= 1024
        return f"{value:.1f}GB"

    def _workflow_payload(self, data: dict[str, Any]) -> str:
        lines = [
            f"Ozet: {data.get('summary', '-')}",
            f"Tip: {data.get('project_type', 'custom')}",
            f"Adim: {len(data.get('stages', []))}",
            "",
        ]
        for idx, stage in enumerate(data.get("stages", []), 1):
            lines.append(f"{idx}. {stage['name']} [{stage['agent']}]")
            lines.append(f"   Okur: {', '.join(stage.get('reads', [])) or '-'}")
            lines.append(f"   Yazar: {', '.join(stage.get('writes', [])) or '-'}")
            lines.append(f"   Checkpoint: {'evet' if stage.get('checkpoint') else 'hayir'}")
            lines.append("")
        return "\n".join(lines)

    def _builtin_workflow_data(self, name: str) -> dict[str, Any]:
        raw = BUILTIN_WORKFLOWS[name]
        data = {
            "summary": raw["summary"],
            "project_type": raw["project_type"],
            "brief_hash": brief_hash(self._saved_or_input_request().strip()),
            "stages": [dict(stage) for stage in raw["stages"]],
        }
        return validate_generated_workflow(data)

    def _activate_workflow_data(self, data: dict[str, Any]) -> None:
        normalized = validate_generated_workflow(data)
        current = self._saved_or_input_request().strip()
        normalized["brief_hash"] = brief_hash(current)
        save_generated_workflow(self.project_dir, normalized)
        self.active_workflow_data = normalized
        state = load_state(self.project_dir)
        new_hash = workflow_hash(normalized["stages"])
        if state.get("workflow_hash") != new_hash:
            state["completed"] = []
            state["workflow_hash"] = new_hash
            save_state(self.project_dir, state)
        self.refresh_stages()
        self._force_refresh_files()

    def _refresh_marketplace(self) -> None:
        if not hasattr(self, "market_select"):
            return
        saved = [f"Kayitli: {item['name']}" for item in list_named_workflows(self.project_dir)]
        values = [f"Hazir: {name}" for name in BUILTIN_WORKFLOWS] + saved
        self.market_select.configure(values=values or ["Workflow yok"])
        current = self.market_select.get()
        if current not in values and values:
            self.market_select.set(values[0])
        selection = self.market_select.get()
        data = None
        if selection.startswith("Hazir: "):
            data = self._builtin_workflow_data(selection.split(": ", 1)[1])
        elif selection.startswith("Kayitli: "):
            data = load_named_workflow(self.project_dir, selection.split(": ", 1)[1])
        self._set_textbox(self.market_text, self._workflow_payload(data) if data else "Workflow sec.")

    def on_load_market_workflow(self) -> None:
        selection = self.market_select.get()
        try:
            if selection.startswith("Hazir: "):
                data = self._builtin_workflow_data(selection.split(": ", 1)[1])
            elif selection.startswith("Kayitli: "):
                data = load_named_workflow(self.project_dir, selection.split(": ", 1)[1])
                if not data:
                    raise WorkflowError("Kayitli workflow okunamadi.")
            else:
                return
            self._activate_workflow_data(data)
            self.set_status("Workflow marketplace'ten yuklendi.", ACCENT)
            self._refresh_marketplace()
        except Exception as exc:
            messagebox.showerror("Marketplace", str(exc))

    def on_save_current_workflow(self) -> None:
        name = simpledialog.askstring("Workflow Kaydet", "Workflow adi:")
        if not name:
            return
        data = self._current_workflow_data() or {
            "summary": "Kaydedilen workflow",
            "project_type": "custom",
            "brief_hash": brief_hash(self._saved_or_input_request().strip()),
            "stages": self._current_stages(),
        }
        try:
            save_named_workflow(self.project_dir, name, data)
            self._refresh_marketplace()
            self.set_status("Workflow kaydedildi.", ACCENT)
        except Exception as exc:
            messagebox.showerror("Marketplace", str(exc))

    def on_delete_saved_workflow(self) -> None:
        selection = self.market_select.get()
        if not selection.startswith("Kayitli: "):
            messagebox.showinfo("Marketplace", "Sadece kayitli workflow silinebilir.")
            return
        name = selection.split(": ", 1)[1]
        if messagebox.askyesno("Marketplace", f"{name} silinsin mi?"):
            delete_named_workflow(self.project_dir, name)
            self._refresh_marketplace()

    def _refresh_metrics(self, schedule: bool = True) -> None:
        if self.closing or not hasattr(self, "metrics_tree"):
            return
        rows = load_metrics(self.project_dir)
        token = (len(rows), rows[-1].get("timestamp") if rows else None)
        if token != self.metrics_token:
            self.metrics_token = token
            by_agent: dict[str, dict[str, Any]] = {}
            for row in rows:
                agent = str(row.get("agent", "?"))
                bucket = by_agent.setdefault(agent, {"runs": 0, "time": 0.0, "errors": 0, "fallbacks": 0, "files": []})
                bucket["runs"] += 1
                bucket["time"] += float(row.get("elapsed", 0) or 0)
                if row.get("status") != "success":
                    bucket["errors"] += 1
                if row.get("fallback_used"):
                    bucket["fallbacks"] += 1
                for item in row.get("outputs", []) or []:
                    if item not in bucket["files"]:
                        bucket["files"].append(item)
            self.metrics_tree.delete(*self.metrics_tree.get_children())
            for agent, data in sorted(by_agent.items()):
                self.metrics_tree.insert("", "end", values=(agent, data["runs"], fmt_seconds(data["time"]), data["errors"], data["fallbacks"], ", ".join(data["files"][-4:])))
            total_time = sum(float(row.get("elapsed", 0) or 0) for row in rows)
            errors = sum(1 for row in rows if row.get("status") != "success")
            fallbacks = sum(1 for row in rows if row.get("fallback_used"))
            self.metrics_summary.configure(text=f"Toplam {len(rows)} adim | sure {fmt_seconds(total_time)} | hata {errors} | fallback {fallbacks}")
        if schedule:
            try:
                self.root.after(2500, self._refresh_metrics)
            except tk.TclError:
                pass

    def _record_metric(
        self,
        stage: dict[str, Any],
        idx: int,
        status: str,
        elapsed: float = 0.0,
        reason: str = "",
        fallback_used: bool = False,
    ) -> None:
        try:
            append_metric(
                self.project_dir,
                {
                    "step": idx,
                    "stage_name": stage.get("name", ""),
                    "agent": stage.get("agent", ""),
                    "status": status,
                    "elapsed": elapsed,
                    "reason": reason,
                    "fallback_used": fallback_used,
                    "outputs": list(stage.get("writes", [])),
                },
            )
            self.metrics_token = None
            self.ui(self._refresh_metrics, False)
        except Exception as exc:
            logger.debug("Metrik yenileme basarisiz: %s", exc)

    def _project_file_facts(self) -> dict[str, tuple[float | None, int]]:
        facts: dict[str, tuple[float | None, int]] = {}
        if not self.project_dir.exists():
            return facts
        for path in self.project_dir.rglob("*"):
            if not path.is_file() or not self._diff_file_allowed(path):
                continue
            rel = path.relative_to(self.project_dir).as_posix()
            try:
                stat = path.stat()
            except OSError:
                continue
            facts[rel] = (stat.st_mtime, stat.st_size)
        return facts

    def on_reset_file_map_baseline(self) -> None:
        self.file_map_baseline = self._project_file_facts()
        self.file_map_token = None
        self._refresh_file_map(schedule=False)
        self.set_status("Dosya haritasi baseline yenilendi.", ACCENT)

    def _refresh_file_map(self, schedule: bool = True) -> None:
        if self.closing or not hasattr(self, "file_map_tree"):
            return
        facts = self._project_file_facts()
        if not self.file_map_baseline:
            self.file_map_baseline = dict(facts)
        token = tuple(sorted(facts.items()))
        if token != self.file_map_token:
            self.file_map_token = token
            self.file_map_tree.delete(*self.file_map_tree.get_children())
            dirs: set[str] = set()
            for rel in sorted(facts):
                parts = rel.split("/")
                parent = ""
                for part in parts[:-1]:
                    path_key = f"{parent}/{part}".strip("/")
                    if path_key not in dirs:
                        dirs.add(path_key)
                        parent_id = parent
                        self.file_map_tree.insert(parent_id, "end", iid=path_key, text=part, values=("", "", ""), tags=("normal",))
                    parent = path_key
                mtime, size = facts[rel]
                base = self.file_map_baseline.get(rel)
                status = "normal"
                tag = "normal"
                if base is None:
                    status, tag = "yeni", "new"
                elif base != (mtime, size):
                    status, tag = "degisti", "changed"
                if size >= 500 * 1024:
                    status, tag = "buyuk", "large"
                ts = time.strftime("%H:%M:%S", time.localtime(mtime)) if mtime else "-"
                parent = "/".join(parts[:-1])
                self.file_map_tree.insert(parent, "end", iid=f"file::{rel}", text=parts[-1], values=(status, self._format_size(size), ts), tags=(tag,))
            changed = sum(1 for rel, fact in facts.items() if self.file_map_baseline.get(rel) not in (None, fact))
            new = sum(1 for rel in facts if rel not in self.file_map_baseline)
            large = sum(1 for _rel, (_mtime, size) in facts.items() if size >= 500 * 1024)
            self.file_map_info.configure(text=f"{len(facts)} dosya | yeni {new} | degisen {changed} | buyuk {large}")
        if schedule:
            try:
                self.root.after(2500, self._refresh_file_map)
            except tk.TclError:
                pass

    def on_file_map_select(self, _event: Any) -> None:
        selection = self.file_map_tree.selection()
        if not selection:
            return
        iid = selection[0]
        if not iid.startswith("file::"):
            return
        rel = iid.split("::", 1)[1]
        self.files_tabs.set("Kod")
        self.selected_code_file = rel
        self.code_select.set(rel if rel in self._list_code_files() else "Kod dosyasi yok")
        self._set_textbox(self.code_text, self._read_project_file(rel))

    def _set_terminal_command(self, command: str) -> None:
        self.terminal_entry.delete(0, "end")
        self.terminal_entry.insert(0, command)

    def _append_terminal_output(self, text: str) -> None:
        if not hasattr(self, "terminal_output"):
            return
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end", text.rstrip() + "\n")
        self.terminal_output.see("end")
        self.terminal_output.configure(state="disabled")

    def on_run_terminal_command(self) -> None:
        command = self.terminal_entry.get().strip()
        if not command:
            return
        with self.terminal_lock:
            if self.terminal_proc is not None and self.terminal_proc.poll() is None:
                messagebox.showinfo("Terminal", "Zaten calisan bir komut var.")
                return
        threading.Thread(target=self._terminal_worker, args=(command,), daemon=True).start()

    def _terminal_worker(self, command: str) -> None:
        self.ui(self._append_terminal_output, f"$ {command}")
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                command,
                cwd=self.project_dir,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=process_env(),
                **process_kwargs(),
            )
            with self.terminal_lock:
                self.terminal_proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                self.ui(self._append_terminal_output, line.rstrip())
            code = proc.wait()
            append_terminal_history(self.project_dir, command, code)
            self.ui(self._append_terminal_output, f"[exit {code}]")
        except Exception as exc:
            append_terminal_history(self.project_dir, command, None)
            self.ui(self._append_terminal_output, f"Terminal hatasi: {exc}")
        finally:
            with self.terminal_lock:
                if self.terminal_proc is proc:
                    self.terminal_proc = None

    def on_stop_terminal_command(self) -> None:
        with self.terminal_lock:
            proc = self.terminal_proc
            self.terminal_proc = None
        if proc and proc.poll() is None:
            kill_process_tree(proc)
            self._append_terminal_output("[durduruldu]")

    def _refresh_history(self, schedule: bool = True) -> None:
        if self.closing or not hasattr(self, "history_tree"):
            return
        rows = list_snapshots(self.project_dir)
        existing = set(self.history_tree.get_children())
        wanted = {str(row.get("id")) for row in rows}
        if existing != wanted:
            self.history_tree.delete(*self.history_tree.get_children())
            for row in rows:
                snap_id = str(row.get("id"))
                self.history_tree.insert("", "end", iid=snap_id, values=(row.get("timestamp", ""), row.get("stage_name", ""), row.get("agent", ""), row.get("file_count", 0), self._format_size(row.get("size", 0))))
            self.history_info.configure(text=f"{len(rows)} snapshot")
        if hasattr(self, "runs_text"):
            runs = load_run_records(self.project_dir, limit=20)
            lines = []
            for r in reversed(runs):
                icon = {"complete": "✓", "stopped": "⏹", "failed": "✗"}.get(str(r.get("status")), "•")
                produced = ", ".join(r.get("produced", [])[:4]) or "-"
                err = f"  |  hata: {r.get('error')}" if r.get("error") else ""
                lines.append(
                    f"{icon} {str(r.get('timestamp', ''))[:16]}  {r.get('run_id', '')}  "
                    f"{r.get('stages_done', 0)}/{r.get('stages_total', 0)} adım  [{r.get('quality', '-')}]  üretilen: {produced}{err}"
                )
            new_text = "\n".join(lines) or "Henüz çalıştırma kaydı yok."
            if new_text != getattr(self, "_runs_cache", None):
                self._runs_cache = new_text
                self._set_textbox(self.runs_text, new_text)
        if hasattr(self, "decisions_text"):
            kararlar = load_decisions(self.project_dir, limit=15)
            klines = []
            for d in reversed(kararlar):
                degisti = ", ".join(d.get("degistirdi", [])[:3]) or "-"
                ozet = (d.get("ozet") or "-").replace("\n", " ")[:110]
                klines.append(
                    f"{str(d.get('timestamp', ''))[:16]}  {d.get('idx', '?')}. {d.get('stage', '')} "
                    f"[{d.get('agent', '')}]  değişti: {degisti}\n    ↳ {ozet}"
                )
            karar_text = "\n".join(klines) or "Henüz karar kaydı yok (adımlar tamamlandıkça dolar)."
            if karar_text != getattr(self, "_decisions_cache", None):
                self._decisions_cache = karar_text
                self._set_textbox(self.decisions_text, karar_text)
        if schedule:
            try:
                self.root.after(3000, self._refresh_history)
            except tk.TclError:
                pass

    def _selected_snapshot_id(self) -> str | None:
        if not hasattr(self, "history_tree"):
            return None
        selection = self.history_tree.selection()
        return selection[0] if selection else None

    def on_restore_snapshot(self) -> None:
        snap_id = self._selected_snapshot_id()
        if not snap_id:
            messagebox.showinfo("Gecmis", "Once snapshot sec.")
            return
        if not messagebox.askyesno("Gecmis", "Proje secili snapshot haline donsun mu?"):
            return
        try:
            restore_snapshot(self.project_dir, snap_id)
            self._force_refresh_files()
            self._refresh_file_map(schedule=False)
            self.set_status("Snapshot geri yuklendi.", ACCENT)
        except Exception as exc:
            messagebox.showerror("Gecmis", str(exc))

    def on_restore_snapshot_file(self) -> None:
        snap_id = self._selected_snapshot_id()
        if not snap_id:
            messagebox.showinfo("Gecmis", "Once snapshot sec.")
            return
        rel = simpledialog.askstring("Dosya Geri Al", "Geri alinacak dosya yolu:")
        if not rel:
            return
        try:
            restore_snapshot_files(self.project_dir, snap_id, [rel])
            self._force_refresh_files()
            self._refresh_file_map(schedule=False)
        except Exception as exc:
            messagebox.showerror("Gecmis", str(exc))

    def on_snapshot_diff(self) -> None:
        snap_id = self._selected_snapshot_id()
        if not snap_id:
            messagebox.showinfo("Gecmis", "Once snapshot sec.")
            return
        rel = simpledialog.askstring("Snapshot Diff", "Diff alinacak dosya yolu:")
        if not rel:
            return
        try:
            before, after = snapshot_diff(self.project_dir, snap_id, rel)
            summary, diff_text = self._build_diff_text({rel: before}, {rel: after})
            self._show_diff_approval({"name": f"Snapshot diff: {rel}", "agent": "Orkestra"}, 0, summary, diff_text)
        except Exception as exc:
            messagebox.showerror("Gecmis", str(exc))

    def _refresh_prompts(self) -> None:
        if not hasattr(self, "prompt_select"):
            return
        profiles = load_prompt_profiles(self.project_dir)
        values = sorted(profiles)
        self.prompt_select.configure(values=values)
        current = self.prompt_select.get()
        if current not in profiles and values:
            current = values[0]
            self.prompt_select.set(current)
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", profiles.get(current, ""))

    def on_prompt_selected(self, value: str) -> None:
        profiles = load_prompt_profiles(self.project_dir)
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", profiles.get(value, ""))

    def on_save_prompt_profile(self) -> None:
        name = simpledialog.askstring("Prompt Profili", "Profil adi:", initialvalue=self.prompt_select.get())
        if not name:
            return
        profiles = load_prompt_profiles(self.project_dir)
        profiles[name.strip()] = self.prompt_text.get("1.0", "end-1c").strip()
        save_prompt_profiles(self.project_dir, profiles)
        self._refresh_prompts()

    def on_delete_prompt_profile(self) -> None:
        name = self.prompt_select.get()
        profiles = load_prompt_profiles(self.project_dir)
        if name in profiles and messagebox.askyesno("Prompt Profili", f"{name} silinsin mi?"):
            profiles.pop(name, None)
            save_prompt_profiles(self.project_dir, profiles)
            self._refresh_prompts()

    def on_apply_prompt_profile(self) -> None:
        profile = self.prompt_text.get("1.0", "end-1c").strip()
        if not profile:
            return
        stages = []
        suffix = f"\n\nAJAN PROFILI:\n{profile}"
        for stage in self._current_stages():
            updated = dict(stage)
            if "AJAN PROFILI:" not in updated["prompt"]:
                updated["prompt"] = updated["prompt"].rstrip() + suffix
            stages.append(updated)
        data = {
            "summary": f"Prompt profili uygulandi: {self.prompt_select.get()}",
            "project_type": "custom",
            "brief_hash": brief_hash(self._saved_or_input_request().strip()),
            "stages": stages,
        }
        try:
            self._activate_workflow_data(data)
            self.set_status("Prompt profili workflow'a uygulandi.", ACCENT)
        except Exception as exc:
            messagebox.showerror("Prompt Profili", str(exc))

    def on_choose_project_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.project_dir))
        if selected:
            self.setup_dir_entry.delete(0, "end")
            self.setup_dir_entry.insert(0, selected)

    def _append_setup_log(self, text: str) -> None:
        self.setup_log.configure(state="normal")
        self.setup_log.insert("end", text.rstrip() + "\n")
        self.setup_log.see("end")
        self.setup_log.configure(state="disabled")

    def _write_file_if_missing(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    def _persist_project_dir(self, path: Path) -> None:
        WF.PROJECT_DIR = str(path)
        wf_path = Path(WF.__file__).resolve()
        try:
            source = wf_path.read_text(encoding="utf-8", errors="replace")
            source = re.sub(r'^PROJECT_DIR\s*=\s*["\'].*?["\']', f'PROJECT_DIR = {json.dumps(str(path))}', source, flags=re.MULTILINE)
            wf_path.write_text(source, encoding="utf-8")
        except Exception as exc:
            logger.warning("workflow dosyasi yazilamadi (%s): %s", wf_path, exc, exc_info=True)

    def on_setup_project(self) -> None:
        target = Path(self.setup_dir_entry.get().strip()).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        stack = self.setup_stack.get()
        try:
            target.mkdir(parents=True, exist_ok=True)
            if stack == "HTML":
                self._write_file_if_missing(target / "index.html", "<!doctype html><html><head><meta charset='utf-8'><title>Maestro App</title><link rel='stylesheet' href='style.css'></head><body><main><h1>Maestro App</h1><p>Hazir HTML proje.</p></main><script src='app.js'></script></body></html>\n")
                self._write_file_if_missing(target / "style.css", "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#020617;color:#f8fafc}main{padding:40px}\n")
                self._write_file_if_missing(target / "app.js", "console.log('Maestro HTML app');\n")
            elif stack == "React":
                self._write_file_if_missing(target / "package.json", json.dumps({"scripts": {"dev": "vite --host 127.0.0.1", "build": "vite build"}, "dependencies": {"@vitejs/plugin-react": "latest", "vite": "latest", "react": "latest", "react-dom": "latest"}, "devDependencies": {}}, indent=2))
                self._write_file_if_missing(target / "index.html", "<div id='root'></div><script type='module' src='/src/main.jsx'></script>\n")
                self._write_file_if_missing(target / "src" / "main.jsx", "import React from 'react';import{createRoot}from'react-dom/client';import'./style.css';\nfunction App(){return <main><h1>Maestro React App</h1><p>Hazir React proje.</p></main>}\ncreateRoot(document.getElementById('root')).render(<App/>);\n")
                self._write_file_if_missing(target / "src" / "style.css", "body{margin:0;background:#020617;color:#f8fafc;font-family:Segoe UI,Arial,sans-serif}main{padding:40px}\n")
            elif stack == "Python":
                self._write_file_if_missing(target / "app.py", "print('Maestro Python app hazir')\n")
            elif stack == "Flask":
                self._write_file_if_missing(target / "app.py", "from flask import Flask\napp=Flask(__name__)\n@app.get('/')\ndef home(): return '<h1>Maestro Flask App</h1>'\nif __name__=='__main__': app.run(debug=True)\n")
            elif stack == "FastAPI":
                self._write_file_if_missing(target / "app.py", "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/')\ndef home(): return {'message':'Maestro FastAPI App'}\n")
            self.project_dir = target
            self._persist_project_dir(target)
            self._sync_project_dir()
            self._load_request_input()
            self._force_refresh_files()
            self._refresh_file_map(schedule=False)
            self._append_setup_log(f"{stack} projesi hazirlandi: {target}")
        except Exception as exc:
            messagebox.showerror("Kurulum", str(exc))

    # ---------------- Genel yardımcılar ----------------
    def _sync_project_dir(self) -> None:
        self.project_dir = resolve_project_dir()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        app_data_dir(self.project_dir)
        self.project_lbl.configure(text=f"Proje klasörü: {self.project_dir}")
        if hasattr(self, "setup_dir_entry"):
            self.setup_dir_entry.delete(0, "end")
            self.setup_dir_entry.insert(0, str(self.project_dir))

    def _load_request_input(self) -> None:
        if not hasattr(self, "request_input"):
            return
        current = read_user_request(self.project_dir)
        self.request_input.configure(state="normal")
        self.request_input.delete("1.0", "end")
        if current:
            self.request_input.insert("1.0", current)

    def _request_text(self) -> str:
        return self.request_input.get("1.0", "end-1c").strip()

    def _saved_or_input_request(self) -> str:
        return self._request_text() or read_user_request(self.project_dir)

    def _load_valid_generated_workflow(self) -> dict[str, Any] | None:
        data = load_generated_workflow(self.project_dir)
        if not data:
            return None
        current = self._saved_or_input_request().strip()
        if current and data.get("brief_hash") != brief_hash(current):
            return None
        return data

    def _current_workflow_data(self) -> dict[str, Any] | None:
        if self.active_workflow_data:
            current = self._saved_or_input_request().strip()
            if current and self.active_workflow_data.get("brief_hash") == brief_hash(current):
                return self.active_workflow_data
            self.active_workflow_data = None
        self.active_workflow_data = self._load_valid_generated_workflow()
        return self.active_workflow_data

    def _current_stages(self) -> list[dict[str, Any]]:
        data = self._current_workflow_data()
        if data:
            return data["stages"]
        return WF.STAGES

    def _max_attempts(self) -> int:
        try:
            value = int(self.max_attempts_var.get())
        except (tk.TclError, TypeError, ValueError):
            value = 1
        return max(1, min(3, value))

    def _fallback_enabled(self) -> bool:
        # Worker'da _launch'in aldigi kopya, ana thread'de canli Var okunur.
        flag = getattr(self, "_opts_agent_fallback", None)
        if flag is not None and threading.current_thread() is not threading.main_thread():
            return bool(flag)
        try:
            return bool(self.agent_fallback_var.get())
        except Exception:
            return bool(flag) if flag is not None else True

    def _fallback_for_output(self, stage: dict[str, Any], output_text: str) -> str | None:
        if not self._fallback_enabled():
            return None
        return fallback_agent_for(stage, output_text)

    def _planned_fallback(self, stage: dict[str, Any]) -> str | None:
        if not self._fallback_enabled():
            return None
        agent = stage.get("agent")
        fallback = stage.get("fallback_agent")
        if isinstance(fallback, str):
            return fallback
        if agent == "gemini":
            return "claude"
        if agent == "claude":
            return "codex"
        return None

    def _stage_start_notice(self, stage: dict[str, Any], idx: int, total: int) -> None:
        timeout = int(stage.get("timeout", WF.DEFAULT_TIMEOUT))
        max_attempts = getattr(self, "_opts_max_attempts", 1)  # worker: Var'a dokunma
        fallback = self._planned_fallback(stage)
        if getattr(self, "_opts_long_step_warning", True) and timeout >= 900:
            self.q(f"! Bu adim uzun surebilir. Maksimum sure: {fmt_seconds(timeout)}.", "warn")
        self.q(
            f"Limit: maksimum sure {fmt_seconds(timeout)}, maksimum deneme {max_attempts}, "
            f"fallback {fallback or '-'}",
            "sub",
        )
        append_chat_entry(
            self.project_dir,
            "Orkestra",
            (
                f"{stage_ref(stage, idx)} icin limitler:\n"
                f"- Maksimum sure: {fmt_seconds(timeout)}\n"
                f"- Maksimum deneme: {max_attempts}\n"
                f"- Fallback: {fallback or '-'}\n"
                f"- Konum: {idx}/{total}"
            ),
        )

    def _diff_file_allowed(self, path: Path) -> bool:
        rel = path.relative_to(self.project_dir)
        if any(part in DIFF_SKIP_DIRS for part in rel.parts):
            return False
        if path.name in DIFF_SKIP_FILES:
            return False
        return path.is_file()

    def _project_snapshot(self) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        if not self.project_dir.exists():
            return snapshot
        for path in self.project_dir.rglob("*"):
            try:
                if not self._diff_file_allowed(path):
                    continue
                rel = path.relative_to(self.project_dir).as_posix()
                size = path.stat().st_size
                if size > DIFF_TEXT_LIMIT:
                    snapshot[rel] = f"<large file: {size} bytes>"
                else:
                    snapshot[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return snapshot

    def _build_diff_text(self, before: dict[str, str], after: dict[str, str]) -> tuple[str, str]:
        before_keys = set(before)
        after_keys = set(after)
        added = sorted(after_keys - before_keys)
        deleted = sorted(before_keys - after_keys)
        modified = sorted(key for key in before_keys & after_keys if before[key] != after[key])
        summary_lines = [
            f"Degisen dosya: {len(added) + len(deleted) + len(modified)}",
            f"Eklenen: {len(added)}",
            f"Silinen: {len(deleted)}",
            f"Degistirilen: {len(modified)}",
        ]
        diff_parts: list[str] = []
        for name in added:
            new_lines = after[name].splitlines()
            summary_lines.append(f"+ {name} ({len(new_lines)} satir)")
            diff_parts.append(f"--- /dev/null\n+++ {name}\n" + "\n".join(f"+{line}" for line in new_lines[:220]))
        for name in deleted:
            old_lines = before[name].splitlines()
            summary_lines.append(f"- {name} ({len(old_lines)} satir)")
            diff_parts.append(f"--- {name}\n+++ /dev/null\n" + "\n".join(f"-{line}" for line in old_lines[:220]))
        for name in modified:
            old_lines = before[name].splitlines()
            new_lines = after[name].splitlines()
            unified = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{name}",
                    tofile=f"b/{name}",
                    lineterm="",
                    n=3,
                )
            )
            added_lines = sum(1 for line in unified if line.startswith("+") and not line.startswith("+++"))
            deleted_lines = sum(1 for line in unified if line.startswith("-") and not line.startswith("---"))
            summary_lines.append(f"~ {name} (+{added_lines} -{deleted_lines})")
            diff_parts.append("\n".join(unified[:260]))
        diff_text = "\n\n".join(part for part in diff_parts if part).strip()
        if len(diff_text) > 30000:
            diff_text = diff_text[:30000] + "\n\n... diff kisaltildi ..."
        return "\n".join(summary_lines), diff_text or "Bu adimda izlenen dosyalarda metinsel fark yok."

    def _stage_needs_diff_approval(self, stage: dict[str, Any], before: dict[str, str], after: dict[str, str]) -> bool:
        if before == after:
            return False
        agent = str(stage.get("agent", "")).lower()
        if agent == "claude":
            return True
        haystack = " ".join(
            [
                str(stage.get("name", "")),
                str(stage.get("prompt", "")),
                " ".join(str(item) for item in stage.get("writes", [])),
            ]
        ).lower()
        needles = ("kod", "code", "frontend", "backend", "uygulama", "app.py", "index.html", "package.json", ".js", ".py")
        return any(needle in haystack for needle in needles)

    def _request_diff_approval(self, stage: dict[str, Any], idx: int, summary: str, diff_text: str) -> str:
        self.decision = None
        self.decision_event.clear()
        self.ui(self._show_diff_approval, stage, idx, summary, diff_text)
        while not self.decision_event.wait(0.1):
            if self.stop_event.is_set():
                return "stop"
        decision = self.decision or "continue"
        self.decision = None
        return decision

    def _show_diff_approval(self, stage: dict[str, Any], idx: int, summary: str, diff_text: str) -> None:
        self.set_status(f"{idx}. adim degisiklik onayi bekliyor.", WARN)
        win = ctk.CTkToplevel(self.root)
        win.title("Degisiklik Onayi")
        win.geometry("960x720")
        win.minsize(780, 560)
        win.grab_set()
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)

        ctk.CTkLabel(
            win,
            text=f"{idx}. {stage['name']} sonrasi dosya farklari",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 6))

        win.configure(fg_color=BG)
        summary_box = ctk.CTkTextbox(win, height=110, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", fg_color=SURFACE_3, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        summary_box.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        summary_box.insert("1.0", summary)
        summary_box.configure(state="disabled")

        diff_box = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Consolas", size=12), wrap="none", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        diff_box.grid(row=2, column=0, sticky="nsew", padx=20, pady=8)
        diff_box.insert("1.0", diff_text)
        diff_box.configure(state="disabled")

        change_box = ctk.CTkTextbox(win, height=74, wrap="word", fg_color=SURFACE_3, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        change_box.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 8))

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=20, pady=(6, 18))

        def finish(decision: str) -> None:
            win.destroy()
            self.decision = decision
            self.decision_event.set()

        def request_change() -> None:
            text = change_box.get("1.0", "end-1c").strip()
            if not text:
                messagebox.showerror("Degisiklik istegi yok", "Tekrar yaptirmak icin istedigin degisikligi yaz.")
                return
            append_chat_entry(self.project_dir, "Kullanici", f"{stage_ref(stage, idx)} icin degisiklik istegi:\n{text}")
            self.chat_mtime = None
            self._refresh_chat()
            finish("retry")

        win.protocol("WM_DELETE_WINDOW", lambda: finish("stop"))
        ctk.CTkButton(bottom, text="Durdur", command=lambda: finish("stop"), fg_color="transparent", border_width=1, border_color=ERR, text_color=ERR, width=100).pack(side="right")
        ctk.CTkButton(bottom, text="Tekrar yaptir", command=lambda: finish("retry"), fg_color="transparent", border_width=1, border_color=WARN, text_color=WARN, width=120).pack(side="right", padx=10)
        ctk.CTkButton(bottom, text="Sunu degistir", command=request_change, fg_color="transparent", border_width=1, border_color=ACCENT_BLUE, text_color=ACCENT_BLUE, width=120).pack(side="right")
        ctk.CTkButton(bottom, text="Onayla", command=lambda: finish("continue"), fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=110, corner_radius=7).pack(side="right", padx=10)

    def _save_request_from_input(self, *, require: bool = False, announce: bool = True) -> bool:
        text = self._request_text()
        existing = read_user_request(self.project_dir)
        if not text and existing:
            text = existing
        if require and not text:
            messagebox.showerror(
                "Is istegi yok",
                "Once alttaki Is Istegi alanina ne yaptirmak istedigini yaz.",
            )
            return False

        if text:
            old = existing.strip()
            save_user_request(self.project_dir, text)
            if announce and text != old:
                append_chat_entry(self.project_dir, "Kullanici", f"Ana is istegi:\n{text}")
            self.chat_mtime = None
        return True

    def _set_textbox(self, box: ctk.CTkTextbox, text: str, tag: str | None = None) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", text, tag or ())
        box.configure(state="disabled")

    def _append_preview_log(self, text: str) -> None:
        if not hasattr(self, "preview_log"):
            return
        self.preview_log.configure(state="normal")
        self.preview_log.insert("end", text.rstrip() + "\n")
        self.preview_log.see("end")
        self.preview_log.configure(state="disabled")

    def _speaker_tag(self, speaker: str) -> str:
        key = speaker.strip().lower()
        if "codex" in key:
            return "codex"
        if "gemini" in key:
            return "gemini"
        if "claude" in key:
            return "claude"
        if "kullanici" in key or "user" in key:
            return "user"
        return "orkestra"

    def _speaker_label(self, speaker: str) -> str:
        tag = self._speaker_tag(speaker)
        return {
            "codex": "Codex",
            "gemini": "Gemini",
            "claude": "Claude",
            "user": "Sen",
            "orkestra": "Orkestra",
        }.get(tag, speaker or "Orkestra")

    def _speaker_color(self, speaker: str) -> str:
        return {
            "codex": ACCENT,
            "gemini": ACCENT_BLUE,
            "claude": PURPLE,
            "user": "#C2410C",
            "orkestra": SUB,
        }.get(self._speaker_tag(speaker), SUB)

    def _parse_chat_entries(self, text: str) -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []
        stamp = ""
        speaker = "Orkestra"
        body: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if body or stamp:
                    entries.append((stamp, speaker, "\n".join(body).strip()))
                raw = line[3:].strip()
                if " - " in raw:
                    stamp, speaker = raw.split(" - ", 1)
                else:
                    stamp, speaker = raw, "Orkestra"
                body = []
            elif not line.startswith("# "):
                body.append(line)
        if body or stamp:
            entries.append((stamp, speaker, "\n".join(body).strip()))
        return entries

    def _render_chat(self, raw_text: str) -> None:
        try:
            at_bottom = self.chat._parent_canvas.yview()[1] >= 0.98
        except Exception:
            at_bottom = True
        for card in self._chat_cards:
            try:
                card.destroy()
            except Exception:
                pass
        self._chat_cards = []
        self._chat_body_labels = []

        entries = self._parse_chat_entries(raw_text)
        if not entries:
            empty = ctk.CTkLabel(
                self.chat,
                text="Akis baslayinca ajan devirleri ve mesajlar burada gorunecek.",
                text_color=MUTED,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                wraplength=460, justify="left", anchor="w",
            )
            empty.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
            self._chat_cards.append(empty)
            return

        try:
            width = max(220, self.chat.winfo_width() - 96)
        except Exception:
            width = 440

        avatar_text = {"user": "Sn", "orkestra": "Or", "codex": "Cx", "gemini": "Gm", "claude": "Cl"}
        avatar_bg = {"user": "#FBEAE0", "orkestra": "#ECEBE3", "codex": "#E2F1E8", "gemini": "#E2EDF7", "claude": "#F0E8FB"}

        for row, (stamp, speaker, body) in enumerate(entries[-80:]):
            tag = self._speaker_tag(speaker)
            color = self._speaker_color(speaker)
            card_bg = "#FBF4EF" if tag == "user" else "#FFFFFF"
            card = ctk.CTkFrame(self.chat, fg_color=card_bg, corner_radius=12)
            card.grid(row=row, column=0, sticky="ew", padx=6, pady=7)
            card.columnconfigure(1, weight=1)
            self._chat_cards.append(card)

            ctk.CTkLabel(
                card, text=avatar_text.get(tag, "•"), width=34, height=34, corner_radius=17,
                fg_color=avatar_bg.get(tag, "#1C2636"), text_color=color,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            ).grid(row=0, column=0, rowspan=2, sticky="n", padx=(12, 10), pady=12)

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(11, 0))
            ctk.CTkLabel(
                header, text=self._speaker_label(speaker), text_color=color,
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            ).pack(side="left")
            if stamp:
                ctk.CTkLabel(
                    header, text=stamp, text_color=MUTED,
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                ).pack(side="right")

            body_lbl = ctk.CTkLabel(
                card, text=(body or "-"), text_color=TEXT_2,
                font=ctk.CTkFont(family="Segoe UI", size=13),
                wraplength=width, justify="left", anchor="w",
            )
            body_lbl.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(2, 12))
            self._chat_body_labels.append(body_lbl)

        if at_bottom:
            try:
                self.chat.after(50, lambda: self.chat._parent_canvas.yview_moveto(1.0))
            except Exception:
                pass

    def _on_chat_resize(self, event: Any) -> None:
        width = max(220, event.width - 96)
        for lbl in getattr(self, "_chat_body_labels", []):
            try:
                lbl.configure(wraplength=width)
            except Exception:
                pass

    def _read_project_file(self, filename: str) -> str:
        path = self.project_dir / filename
        if not path.exists():
            return f"{filename} henuz olusmadi.\n"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"{filename} okunamadi: {exc}\n"
        return text or f"{filename} bos.\n"

    def _list_code_files(self) -> list[str]:
        skip_dirs = {"logs", "__pycache__", "node_modules", ".git", ".venv", "venv", "dist", "build"}
        skip_files = {
            STATE_FILE,
            CHAT_FILE,
            REQUEST_FILE,
            BRIEF_QUESTIONS_FILE,
            GENERATED_WORKFLOW_FILE,
            "plan.md",
            "tasarim.md",
            "rapor.md",
            "kontrol.md",
        }
        code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".md", ".txt", ".yml", ".yaml", ".toml"}
        files: list[str] = []
        if not self.project_dir.exists():
            return files
        for path in self.project_dir.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self.project_dir).parts
            if any(part in skip_dirs for part in rel_parts[:-1]):
                continue
            if path.name in skip_files:
                continue
            if path.suffix.lower() in code_exts:
                files.append(str(path.relative_to(self.project_dir)).replace("\\", "/"))
        return sorted(files)

    def _on_code_file_selected(self, value: str) -> None:
        if not value or value == "Kod dosyasi yok":
            self.selected_code_file = None
            self._set_textbox(self.code_text, "Kod dosyasi yok.\n")
            return
        self.selected_code_file = value
        self._set_textbox(self.code_text, self._read_project_file(value))

    def _file_mtime_token(self) -> tuple[Any, ...]:
        tracked = ["istek.md", "plan.md", "tasarim.md", "rapor.md", "kontrol.md", ERROR_FILE]
        token: list[Any] = []
        for name in tracked:
            path = self.project_dir / name
            token.append((name, path.stat().st_mtime if path.exists() else None))
        for name in self._list_code_files():
            path = self.project_dir / name
            token.append((name, path.stat().st_mtime if path.exists() else None))
        return tuple(token)

    def _force_refresh_files(self) -> None:
        self.files_mtime_token = None
        self._refresh_files(schedule=False)

    def _refresh_files(self, schedule: bool = True) -> None:
        if self.closing or not hasattr(self, "file_textboxes"):
            return
        try:
            token = self._file_mtime_token()
            if token != self.files_mtime_token:
                self.files_mtime_token = token
                for filename, box in self.file_textboxes.items():
                    self._set_textbox(box, self._read_project_file(filename))
                code_files = self._list_code_files()
                values = code_files or ["Kod dosyasi yok"]
                self.code_select.configure(values=values)
                if self.selected_code_file not in code_files:
                    self.selected_code_file = code_files[0] if code_files else None
                    self.code_select.set(self.selected_code_file or "Kod dosyasi yok")
                if self.selected_code_file:
                    self._set_textbox(self.code_text, self._read_project_file(self.selected_code_file))
                else:
                    self._set_textbox(self.code_text, "Kod dosyasi yok.\n")
                self._update_preview_target()
        except Exception as exc:
            if hasattr(self, "code_text"):
                self._set_textbox(self.code_text, f"Dosyalar yenilenemedi: {exc}\n")
        if schedule:
            try:
                self.root.after(1500, self._refresh_files)
            except tk.TclError:
                pass

    def _detect_preview_target(self) -> dict[str, Any] | None:
        package_json = self.project_dir / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:
                logger.debug("package.json okunamadi: %s", exc)
                data = {}
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            dev_script = scripts.get("dev") or scripts.get("start") or ""
            script_name = "dev" if scripts.get("dev") else "start"
            script_text = str(dev_script).lower()
            port = 5173 if "vite" in script_text else 3000
            if "next" in script_text or "react-scripts" in script_text:
                port = 3000
            return {"type": "node", "label": f"Node app: npm run {script_name}", "script": script_name, "url": f"http://localhost:{port}"}

        for html in ("index.html", "app.html"):
            path = self.project_dir / html
            if path.exists():
                return {"type": "html", "label": f"HTML dosyasi: {html}", "path": path, "url": path.resolve().as_uri()}

        for py in ("app.py", "main.py", "server.py"):
            path = self.project_dir / py
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                port = 8501 if "streamlit" in text else 8000 if "fastapi" in text or "uvicorn" in text else 5000 if "flask" in text else 8000
                return {"type": "python", "label": f"Python app: {py}", "path": path, "url": f"http://localhost:{port}"}
        return None

    def _preview_command_for_target(self, target: dict[str, Any]) -> list[str] | None:
        if target["type"] == "html":
            return None
        if target["type"] == "node":
            npm = shutil.which("npm") or shutil.which("npm.cmd")
            if not npm:
                raise RuntimeError("npm bulunamadi")
            return [npm, "run", target.get("script", "dev")]
        if target["type"] == "python":
            path = Path(target["path"])
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            if "streamlit" in text and (shutil.which("streamlit") or shutil.which("streamlit.exe")):
                streamlit = shutil.which("streamlit") or shutil.which("streamlit.exe")
                return [streamlit, "run", str(path.name)]
            if "fastapi" in text and "uvicorn" in text:
                return [sys.executable, "-m", "uvicorn", f"{path.stem}:app", "--reload"]
            return [sys.executable, str(path.name)]
        return None

    def _ensure_node_dependencies(self) -> tuple[bool, str]:
        if (self.project_dir / "node_modules").exists():
            return True, "node_modules hazir"
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            return False, "npm bulunamadi"
        self.q("$ npm install", "sub")
        try:
            result = subprocess.run(
                [npm, "install"],
                cwd=self.project_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return False, f"npm install zaman asimi\n{exc}"
        output = result.stdout or ""
        if result.returncode != 0:
            return False, output[-6000:] or f"npm install exit {result.returncode}"
        return True, output[-2000:] or "npm install tamamlandi"

    def _run_runtime_probe(self, target: dict[str, Any]) -> tuple[bool, str]:
        if target["type"] == "html":
            path = Path(target["path"])
            return (path.exists(), f"HTML dosyasi hazir: {path.name}" if path.exists() else f"HTML dosyasi bulunamadi: {path}")
        if target["type"] == "node":
            ok, details = self._ensure_node_dependencies()
            if not ok:
                return False, details
        try:
            cmd = self._preview_command_for_target(target)
        except Exception as exc:
            return False, str(exc)
        if not cmd:
            return True, target.get("label", "Onizleme hedefi hazir")
        self.q("$ " + " ".join(cmd), "sub")
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=process_env(),
                **process_kwargs(),
            )
            try:
                output, _ = proc.communicate(timeout=RUNTIME_CHECK_TIMEOUT)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc)
                try:
                    output, _ = proc.communicate(timeout=2)
                except Exception as exc:
                    logger.debug("Onizleme komut ciktisi alinamadi (sure dolmus olabilir): %s", exc)
                    output = ""
                return True, (output[-4000:] if output else "Komut calisti; sure dolana kadar crash olmadi.")
            if proc.returncode == 0:
                return True, output[-4000:] if output else "Komut basariyla bitti."
            return False, output[-6000:] if output else f"Komut exit {proc.returncode}"
        except Exception as exc:
            kill_process_tree(proc)
            return False, str(exc)

    def _stage_should_runtime_check(self, stage: dict[str, Any]) -> bool:
        if not getattr(self, "_opts_auto_fix", True):  # worker: Var'a dokunma
            return False
        target = self._detect_preview_target()
        if not target:
            return False
        haystack = " ".join(
            [
                str(stage.get("agent", "")),
                str(stage.get("name", "")),
                str(stage.get("prompt", "")),
                " ".join(str(item) for item in stage.get("writes", [])),
            ]
        ).lower()
        needles = ("claude", "kod", "code", "frontend", "backend", "uygulama", "package.json", "index.html", ".py", ".js", ".tsx", ".jsx")
        return any(needle in haystack for needle in needles)

    def _write_error_report(self, stage: dict[str, Any], idx: int, attempt: int, target: dict[str, Any], details: str) -> None:
        content = (
            "# Otomatik Hata Raporu\n\n"
            f"- Adim: {stage_ref(stage, idx)}\n"
            f"- Deneme: {attempt}/{AUTO_FIX_ATTEMPTS}\n"
            f"- Hedef: {target.get('label', '-')}\n"
            f"- URL: {target.get('url', '-')}\n\n"
            "## Hata / Cikti\n\n"
            "```text\n"
            f"{details[-12000:]}\n"
            "```\n"
        )
        (self.project_dir / ERROR_FILE).write_text(content, encoding="utf-8")
        self.ui(self._force_refresh_files)
        append_chat_entry(self.project_dir, "Orkestra", f"{ERROR_FILE} yazildi. Claude duzeltme denemesi hazirlanacak.")

    def _run_claude_fix_from_error(self, stage: dict[str, Any], idx: int, total: int, stages: list[dict[str, Any]], attempt: int) -> bool:
        if not find_tool("claude"):
            self.q("! Claude komutu bulunamadi; otomatik hata duzeltme yapilamiyor.", "err")
            return False
        fix_stage = {
            "name": f"Hata Duzeltme {attempt}",
            "agent": "claude",
            "prompt": (
                f"{ERROR_FILE} dosyasini oku. Uygulamayi calistirirken yakalanan hatayi duzelt. "
                "Sadece gerekli kod degisikliklerini yap; gereksiz refactor yapma. "
                "istek.md, sohbet.md, plan.md ve varsa ilgili kod dosyalarini incele. "
                f"Duzeltmeden sonra {ERROR_FILE} dosyasina neyi duzelttigini kisa not olarak ekle."
            ),
            "reads": [ERROR_FILE, "istek.md", "sohbet.md"],
            "writes": [ERROR_FILE],
            "checkpoint": False,
            "timeout": 900,
            "fallback_agent": "codex",
        }
        self.q(f"Claude hata duzeltme denemesi basliyor ({attempt}/{AUTO_FIX_ATTEMPTS})...", "warn")
        append_chat_entry(self.project_dir, "Orkestra", f"Claude'a hata duzeltme devredildi. Deneme: {attempt}/{AUTO_FIX_ATTEMPTS}")
        ok, _elapsed, reason, output = self._run_one(fix_stage, idx, total, stages)
        fallback = self._fallback_for_output(fix_stage, output)
        if not ok and reason == "exit" and fallback and find_tool(fallback):
            self.q(f"! Claude duzeltme adimi limit/hata verdi; {fallback.upper()} devraliyor.", "warn")
            ok, _elapsed, reason, _output = self._run_one(with_fallback_agent(fix_stage, fallback), idx, total, stages)
        if not ok:
            self.q(f"! Claude hata duzeltme adimi basarisiz: {reason}", "err")
        return ok

    def _auto_fix_runtime_loop(self, stage: dict[str, Any], idx: int, total: int, stages: list[dict[str, Any]]) -> bool:
        if not self._stage_should_runtime_check(stage):
            return True
        target = self._detect_preview_target()
        if not target:
            return True
        self.q(f"Otomatik calistirma testi: {target.get('label', '-')}", "accent")
        append_chat_entry(self.project_dir, "Orkestra", f"Kodlama sonrasi otomatik calistirma testi basliyor: {target.get('label', '-')}")
        for attempt in range(1, AUTO_FIX_ATTEMPTS + 1):
            ok, details = self._run_runtime_probe(target)
            if ok:
                self.q("✓ Otomatik calistirma testi basarili.", "ok")
                append_chat_entry(self.project_dir, "Orkestra", "Otomatik calistirma testi basarili.")
                return True
            self.q(f"! Otomatik calistirma hatasi yakalandi ({attempt}/{AUTO_FIX_ATTEMPTS}).", "err")
            self._write_error_report(stage, idx, attempt, target, details)
            if attempt >= AUTO_FIX_ATTEMPTS:
                append_chat_entry(self.project_dir, "Orkestra", "Otomatik hata duzeltme denemeleri tukendi. Akis durdu.")
                return False
            if not self._run_claude_fix_from_error(stage, idx, total, stages, attempt):
                return False
            target = self._detect_preview_target() or target
        return False

    def _preview_frame_url(self, target_url: str, mode: str) -> str:
        sizes = {
            "Desktop": (1440, 900),
            "Tablet": (834, 1112),
            "Mobil": (390, 844),
        }
        width, height = sizes.get(mode, sizes["Desktop"])
        frame = app_data_dir(self.project_dir) / "preview_frame.html"
        safe_url = html.escape(target_url, quote=True)
        frame.write_text(
            f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Maestro Preview</title>
<style>
body{{margin:0;background:#020617;color:#f8fafc;font-family:Segoe UI,Arial,sans-serif}}
.bar{{height:54px;display:flex;align-items:center;gap:14px;padding:0 18px;border-bottom:1px solid #1e293b;background:#0b1120}}
.wrap{{display:flex;justify-content:center;align-items:flex-start;padding:24px}}
iframe{{width:{width}px;height:{height}px;border:1px solid #334155;border-radius:12px;background:white;box-shadow:0 24px 80px rgba(0,0,0,.38)}}
a{{color:#38bdf8}}
</style></head><body>
<div class="bar"><strong>{mode}</strong><span>{width}x{height}</span><a href="{safe_url}" target="_blank">Direkt ac</a></div>
<div class="wrap"><iframe src="{safe_url}" title="Maestro preview"></iframe></div>
</body></html>
""",
            encoding="utf-8",
        )
        return frame.resolve().as_uri()

    def _update_preview_target(self) -> None:
        self.preview_target = self._detect_preview_target()
        if not hasattr(self, "preview_info"):
            return
        if not self.preview_target:
            self.preview_info.configure(text="Onizleme hedefi yok. Claude kod uretince package.json, index.html veya app.py algilanir.", text_color=SUB)
            self.b_open_preview.configure(state="disabled")
            return
        self.preview_info.configure(text=f"{self.preview_target['label']}  ->  {self.preview_target.get('url', '')}", text_color=ACCENT_BLUE)
        self.b_open_preview.configure(state="normal")

    def _refresh_preview_state(self) -> None:
        if self.closing:
            return
        try:
            with self.preview_lock:
                proc = self.preview_proc
            if proc is not None and proc.poll() is not None:
                self._append_preview_log(f"Onizleme sureci kapandi (exit {proc.returncode}).")
                with self.preview_lock:
                    if self.preview_proc is proc:
                        self.preview_proc = None
        finally:
            try:
                self.root.after(2000, self._refresh_preview_state)
            except tk.TclError:
                pass

    def ui(self, func: Any, *args: Any) -> None:
        """Worker'dan UI cagrisi: Tcl'e dokunmadan kuyruga birakir.

        root.after'i worker'dan cagirmak threaded-Tcl'de RuntimeError
        firlatabilir ve cagri kaybolur (busy kilidi acilamaz vb.).
        Kuyruk + ana-thread pompasi bu sinifin tamamini yok eder.
        """
        if self.closing:
            return
        self.ui_q.put((func, args))

    def refresh_tools(self) -> None:
        parts = []
        for tool in ("codex", "gemini", "claude"):
            mark = "●" if find_tool(tool) else "○"
            parts.append(f"{mark} {tool}")
        text = "   ".join(parts)
        try:
            missing = missing_required_tools(self._current_stages())
            if missing:
                text += f"     ⚠ bu akış için eksik: {', '.join(missing)}"
        except Exception as exc:
            logger.debug("Risk/araç kontrolü yapılamadı: %s", exc)
        self.tools_lbl.configure(text=text)

    def refresh_stages(self) -> None:
        for item in self.stage_tree.get_children():
            self.stage_tree.delete(item)

        stages = self._current_stages()
        try:
            validate_workflow(stages)
        except WorkflowError as exc:
            self.stage_tree.insert("", "end", values=("✕", str(exc), "-", ""), tags=("failed",))
            return

        state = load_state(self.project_dir)
        current_hash = workflow_hash(stages)
        done = set(state.get("completed", [])) if state.get("workflow_hash") == current_hash else set()
        for i, stage in enumerate(stages, 1):
            if i == self.failed_index:
                status, tag = "✕", "failed"
            elif i == self.running_index:
                status, tag = "▶", "running"
            elif i in done:
                status, tag = "✓", "done"
            else:
                status, tag = "⏸" if stage.get("checkpoint") else "·", "pending"

            agent = stage["agent"]
            duration = self.stage_durations.get(i, "")
            self.stage_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(status, f"{i}. {stage['name']}", agent, duration),
                tags=(tag,),
            )
        self._update_idle_status()
        self._refresh_kanban()

    def _update_idle_status(self) -> None:
        # Akilli Devam: bos zamanda kaldigi yer / sonraki adimi durum cubuguna yaz.
        if self.running:
            return
        try:
            stages = self._current_stages()
            state = load_state(self.project_dir)
            current_hash = workflow_hash(stages)
            done = state.get("completed", []) if state.get("workflow_hash") == current_hash else []
            done_n = len([s for s in done if isinstance(s, int)])
            total = len(stages)
            if done_n == 0:
                self.set_status("Hazır — iş isteğini yaz ve Gönder'e bas.", SUB)
            elif done_n >= total:
                self.set_status(f"Tüm {total} adım tamamlandı. Yeni iş için yaz veya Sıfırla.", ACCENT)
            else:
                nxt = stages[done_n]
                self.set_status(
                    f"Kaldığın yer: {done_n}/{total} bitti · Sonraki: {done_n + 1}. {nxt['name']} [{nxt['agent']}] · 'Devam' ile sürdür.",
                    ACCENT_BLUE,
                )
        except Exception as exc:
            logger.debug("Akilli durum ozeti hesaplanamadi: %s", exc)

    def _on_stage_select(self, _event: Any = None) -> None:
        # Ajan adim detayi: secili adimin okur/yazar/fallback/checkpoint/timeout bilgisi.
        try:
            sel = self.stage_tree.selection()
            if not sel:
                self.stage_detail_lbl.configure(text=self._stage_legend, text_color=MUTED)
                return
            idx = int(sel[0])
            stages = self._current_stages()
            if not (1 <= idx <= len(stages)):
                return
            s = stages[idx - 1]
            reads = ", ".join(s.get("reads", [])) or "-"
            writes = ", ".join(s.get("writes", [])) or "-"
            fb = s.get("fallback_agent") or "yok"
            cp = "var" if s.get("checkpoint") else "yok"
            to = int(s.get("timeout", WF.DEFAULT_TIMEOUT))
            self.stage_detail_lbl.configure(
                text=(
                    f"{idx}. {s['name']} · {s['agent']}\n"
                    f"Okur:  {reads}\n"
                    f"Yazar: {writes}\n"
                    f"Fallback: {fb} · Checkpoint: {cp} · Timeout: {to}sn"
                ),
                text_color=TEXT_2,
            )
        except Exception as exc:
            logger.debug("Adim detayi gosterilemedi: %s", exc)

    def write(self, text: str, tag: str | None = None) -> None:
        at_bottom = True
        try:
            at_bottom = self.log.yview()[1] >= 0.98
        except Exception as exc:
            logger.debug("Log kaydirma durumu okunamadi (pencere kapanmis olabilir): %s", exc)
            return
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        if at_bottom:
            self.log.see("end")
        self.log.configure(state="disabled")

    def q(self, text: str, tag: str | None = None) -> None:
        self.log_q.put((text, tag))

    def set_status(self, text: str, color: str = SUB) -> None:
        self.status.configure(text=text, text_color=color)

    def _drain_log(self) -> None:
        if self.closing:
            return
        try:
            while True:
                text, tag = self.log_q.get_nowait()
                self.write(text, tag)
        except queue.Empty:
            pass
        try:
            while True:
                func, args = self.ui_q.get_nowait()
                try:
                    func(*args)
                except Exception as exc:
                    logger.debug("UI kuyruk cagrisi basarisiz (%s): %s", getattr(func, "__name__", func), exc)
        except queue.Empty:
            pass
        try:
            self.root.after(100, self._drain_log)
        except tk.TclError:
            pass

    def _refresh_chat(self) -> None:
        if self.closing:
            return
        try:
            path = chat_path(self.project_dir)
            if path.exists():
                mtime = path.stat().st_mtime
                if self.chat_mtime != mtime:
                    self.chat_mtime = mtime
                    self._render_chat(path.read_text(encoding="utf-8", errors="replace"))
            else:
                self._render_chat("")
        except Exception as exc:
            logger.debug("Sohbet yenileme basarisiz: %s", exc)
        try:
            self.root.after(1000, self._refresh_chat)
        except tk.TclError:
            pass

    def _tick_elapsed(self) -> None:
        if self.closing or self.running_index is None or self.step_started_at is None:
            return
        self.stage_durations[self.running_index] = fmt_seconds(time.monotonic() - self.step_started_at)
        self.refresh_stages()
        try:
            self.root.after(1000, self._tick_elapsed)
        except tk.TclError:
            pass

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _busy(self, busy: bool) -> None:
        self.running = busy
        state = "disabled" if busy else "normal"
        for btn in (self.b_limits, self.b_start, self.b_resume, self.b_from, self.b_preview, self.b_roles, self.b_workflow, self.b_reset):
            btn.configure(state=state)
        self.b_save_request.configure(state=state)
        self.b_send_chat.configure(state="normal")
        self.request_input.configure(state="normal")
        self.checkpoint_chk.configure(state=state)

    def _set_ctrl(self, show: bool, allow_decide: bool = False) -> None:
        self.b_continue.configure(state="normal" if allow_decide else "disabled")
        self.b_retry.configure(state="normal" if allow_decide else "disabled")
        self.b_stop.configure(state="normal" if show else "disabled")

    def _mark_running(self, index: int, total: int, name: str) -> None:
        self.running_index = index
        self.failed_index = None
        self.step_started_at = time.monotonic()
        val = max(0, index - 1) / total if total > 0 else 0
        self.progress.set(val)
        self.progress_lbl.configure(text=f"Adım {index}/{total}")
        self.set_status(f"Adım {index}/{total}: {name} çalışıyor...", ACCENT_BLUE)
        self.refresh_stages()
        self._tick_elapsed()

    def _mark_done(self, index: int, elapsed: float, total: int) -> None:
        self.stage_durations[index] = fmt_seconds(elapsed)
        self.running_index = None
        self.step_started_at = None
        val = index / total if total > 0 else 0
        self.progress.set(val)
        self.progress_lbl.configure(text=f"{index}/{total} tamam")
        self.refresh_stages()
        self._force_refresh_files()

    def _mark_failed(self, index: int) -> None:
        self.failed_index = index
        self.running_index = None
        self.step_started_at = None
        self.refresh_stages()

    def _brief_questions_prompt(self, initial_request: str) -> str:
        return (
            "AI Orkestra icin baslangic brief sorulari uret. "
            f"CWD icinde sadece {BRIEF_QUESTIONS_FILE} dosyasini yaz.\n"
            "Cevabin dosyada gecerli JSON olsun; markdown kullanma.\n"
            "Sema: {\"questions\":[{\"id\":\"platform\",\"question\":\"...\",\"hint\":\"...\",\"required\":true}]}\n"
            "Kurallar: 3-5 soru uret; id slug biciminde olsun; sorular kisa, net ve Turkce olsun; "
            "uygulama turu, hedef kullanici, platform, tasarim tarzi ve veri saklama eksikse bunlari sor.\n\n"
            f"Kullanici ilk istegi:\n{initial_request}"
        )

    def _workflow_prompt(self, final_brief: str, current_hash: str, repair_error: str | None = None) -> str:
        repair = f"\nOnceki deneme gecersizdi: {repair_error}\nBu kez sadece gecerli JSON dosyasi yaz.\n" if repair_error else ""
        return (
            "AI Orkestra icin kullanici briefine gore otomatik workflow uret. "
            f"CWD icinde sadece {GENERATED_WORKFLOW_FILE} dosyasini yaz.\n"
            "Cevabin dosyada gecerli JSON olsun; markdown kullanma.\n"
            f"{repair}"
            "Sema: {\"summary\":\"Kisa proje ozeti\",\"project_type\":\"web_app|game|admin_panel|desktop_app|custom\","
            f"\"brief_hash\":\"{current_hash}\",\"stages\":["
            "{\"name\":\"Gereksinim Analizi\",\"agent\":\"codex\",\"prompt\":\"istek.md ve sohbet.md oku...\","
            "\"reads\":[\"istek.md\"],\"writes\":[\"plan.md\"],\"checkpoint\":true,\"timeout\":1800}]}\n"
            "Kurallar: 3-8 adim; agent sadece codex, gemini veya claude; her adim net bir dosya uretmeli; "
            "reads/writes guvenli goreli dosya yollari olmali; gemini adimlarina fallback_agent claude, "
            "claude adimlarina fallback_agent codex ekle; kod yazan adimlarda checkpoint true olsun. "
            "Oyun icin konsept/mekanik, asset plani, kodlama, test, dengeleme akisina yakin ol. "
            "Web/admin/SaaS icin gereksinim, UI/UX, kodlama/backend-frontend, kontrol, duzeltme akisina yakin ol. "
            "Belirsiz projelerde analiz, tasarim, uygulama, kontrol, duzeltme kullan.\n\n"
            f"Final brief:\n{final_brief}"
        )

    def _run_codex_file_job(self, prompt: str, label: str, timeout: int = 600) -> tuple[bool, str]:
        cmd = resolve_command(["codex", "exec", "--full-auto", "--skip-git-repo-check", prompt])
        self.q(f"$ codex exec ...  ({label})", "sub")
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=process_env(),
                **process_kwargs(),
            )
        except FileNotFoundError:
            return False, "codex komutu bulunamadi"

        with self.proc_lock:
            self.proc = proc
        output_lines: list[str] = []
        reader_done = threading.Event()

        def reader() -> None:
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if self.stop_event.is_set():
                        break
                    clean = line.rstrip()
                    output_lines.append(clean)
                    self.q("  " + clean)
            finally:
                reader_done.set()

        threading.Thread(target=reader, daemon=True).start()

        try:
            while proc.poll() is None:
                if self.stop_event.is_set():
                    kill_process_tree(proc)
                    return False, "durduruldu"
                if time.monotonic() - start > timeout:
                    kill_process_tree(proc)
                    return False, f"zaman asimi ({timeout}sn)"
                time.sleep(0.1)
        finally:
            reader_done.wait(timeout=1.5)
            with self.proc_lock:
                if self.proc is proc:
                    self.proc = None

        output_text = "\n".join(output_lines)
        if proc.returncode != 0:
            return False, output_text or f"exit {proc.returncode}"
        return True, output_text

    def _begin_smart_start(self) -> None:
        if self.running:
            return
        self._sync_project_dir()
        initial_request = self._request_text().strip()
        if not initial_request:
            messagebox.showerror("Is istegi yok", "Once Is Istegi alanina ne yaptirmak istedigini yaz.")
            return
        self._set_phase("sorular")
        if not find_tool("codex"):
            messagebox.showerror("Eksik ajan komutu", "Akilli brief icin codex komutu kurulu ve PATH icinde olmali.")
            self.refresh_tools()
            return

        self._clear_log()
        self.stop_event.clear()
        self.decision_event.clear()
        self.decision = None
        self.failed_index = None
        self.running_index = None
        self.stage_durations.clear()
        self.progress.set(0)
        self.progress_lbl.configure(text="Brief")
        self._busy(True)
        self._set_ctrl(True, allow_decide=False)
        save_user_request(self.project_dir, initial_request)
        append_chat_entry(self.project_dir, "Kullanici", f"Ilk is istegi:\n{initial_request}")
        self.set_status("Codex netlestirme sorularini hazirliyor...", ACCENT_BLUE)

        self.worker = threading.Thread(target=self._prepare_questions_worker, args=(initial_request,), daemon=True)
        self.worker.start()

    def _prepare_questions_worker(self, initial_request: str) -> None:
        path = self.project_dir / BRIEF_QUESTIONS_FILE
        try:
            if path.exists():
                path.unlink()
            ok, output = self._run_codex_file_job(self._brief_questions_prompt(initial_request), "brief sorulari")
            if not ok:
                self.ui(messagebox.showerror, "Brief sorulari", f"Codex soru uretemedi:\n{output[-1200:]}")
                self.ui(self.set_status, "Brief hazirligi durdu.", ERR)
                self.ui(self._busy, False)
                return
            questions = load_brief_questions(self.project_dir)
            save_brief_questions(self.project_dir, questions)
            self.pending_initial_request = initial_request
            self.pending_brief_questions = questions
            self.pending_answers = []
            self.ui(self._show_brief_questions, questions, initial_request, None)
        except Exception as exc:
            self.ui(messagebox.showerror, "Brief sorulari", str(exc))
            self.ui(self.set_status, "Brief hazirligi hata verdi.", ERR)
            self.ui(self._busy, False)
        finally:
            self.ui(self._set_ctrl, False)
            if self.stop_event.is_set():
                self.ui(self._busy, False)

    def _show_brief_questions(self, questions: list[dict[str, Any]], initial_request: str, prefill: list[dict[str, str]] | None) -> None:
        self.set_status("Netlestirme cevaplarini bekliyorum.", WARN)
        prefill_by_id = {item.get("id", ""): item.get("answer", "") for item in (prefill or [])}
        win = ctk.CTkToplevel(self.root)
        win.title("Netlestirme Sorulari")
        win.geometry("760x620")
        win.minsize(680, 500)
        win.configure(fg_color=BG)
        win.grab_set()
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            win,
            text="Codex baslamadan once su sorulari netlestirmek istiyor.",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 8))

        frame = ctk.CTkScrollableFrame(win, corner_radius=10, fg_color=SURFACE, border_width=1, border_color=BORDER_SOFT)
        frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=8)
        frame.columnconfigure(0, weight=1)

        inputs: list[tuple[dict[str, Any], ctk.CTkTextbox]] = []
        for row, question in enumerate(questions):
            ctk.CTkLabel(
                frame,
                text=question["question"],
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                anchor="w",
                justify="left",
            ).grid(row=row * 3, column=0, sticky="ew", pady=(8, 0))
            hint = question.get("hint", "")
            if hint:
                ctk.CTkLabel(frame, text=hint, text_color=SUB, anchor="w", justify="left").grid(
                    row=row * 3 + 1, column=0, sticky="ew", pady=(2, 4)
                )
            box = ctk.CTkTextbox(frame, height=58, wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
            box.grid(row=row * 3 + 2, column=0, sticky="ew", pady=(0, 8))
            existing = prefill_by_id.get(question["id"], "")
            if existing:
                box.insert("1.0", existing)
            inputs.append((question, box))

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 18))

        def cancel() -> None:
            win.destroy()
            self._busy(False)
            self._set_ctrl(False)
            self.set_status("Brief hazirligi iptal edildi.", WARN)

        def submit() -> None:
            answers: list[dict[str, str]] = []
            missing: list[str] = []
            for question, box in inputs:
                answer = box.get("1.0", "end-1c").strip()
                if question.get("required") and not answer:
                    missing.append(question["question"])
                answers.append({"id": question["id"], "question": question["question"], "answer": answer})
            if missing:
                messagebox.showerror("Eksik cevap", "Zorunlu sorulari cevapla.")
                return
            win.destroy()
            self.pending_answers = answers
            self._start_workflow_generation(initial_request, questions, answers)

        win.protocol("WM_DELETE_WINDOW", cancel)
        ctk.CTkButton(bottom, text="Iptal", command=cancel, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=110).pack(side="right")
        ctk.CTkButton(bottom, text="Workflow Hazirla", command=submit, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=150, corner_radius=7).pack(side="right", padx=10)

    def _start_workflow_generation(self, initial_request: str, questions: list[dict[str, Any]], answers: list[dict[str, str]]) -> None:
        self._busy(True)
        self._set_ctrl(True, allow_decide=False)
        self.set_status("Codex otomatik workflow hazirliyor...", ACCENT_BLUE)
        self.worker = threading.Thread(
            target=self._workflow_generation_worker,
            args=(initial_request, questions, answers),
            daemon=True,
        )
        self.worker.start()

    def _workflow_generation_worker(self, initial_request: str, questions: list[dict[str, Any]], answers: list[dict[str, str]]) -> None:
        try:
            final_brief = save_structured_brief(self.project_dir, initial_request, answers)
            current_hash = brief_hash(final_brief)
            append_chat_entry(self.project_dir, "Kullanici", f"Netlestirilmis final brief kaydedildi. Hash: {current_hash[:12]}")
            last_error = None
            data: dict[str, Any] | None = None
            path = self.project_dir / GENERATED_WORKFLOW_FILE

            for attempt in range(2):
                if path.exists():
                    path.unlink()
                ok, output = self._run_codex_file_job(
                    self._workflow_prompt(final_brief, current_hash, last_error),
                    f"workflow uretimi deneme {attempt + 1}",
                    timeout=900,
                )
                if not ok:
                    last_error = output[-1200:]
                    continue
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    normalized = validate_generated_workflow(raw)
                    if normalized.get("brief_hash") and normalized["brief_hash"] != current_hash:
                        raise WorkflowError("brief_hash final brief ile eslesmiyor")
                    normalized["brief_hash"] = current_hash
                    save_generated_workflow(self.project_dir, normalized)
                    data = normalized
                    break
                except Exception as exc:
                    last_error = str(exc)

            if not data:
                self.ui(messagebox.showerror, "Workflow uretilemedi", f"Codex gecerli workflow JSON uretemedi:\n{last_error}")
                self.ui(self.set_status, "Workflow hazirligi durdu.", ERR)
                self.ui(self._busy, False)
                return

            self.active_workflow_data = data
            self.pending_initial_request = initial_request
            self.pending_brief_questions = questions
            self.pending_answers = answers
            self.ui(self._load_request_input)
            self.ui(self._show_workflow_approval, data)
        except Exception as exc:
            self.ui(messagebox.showerror, "Workflow uretimi", str(exc))
            self.ui(self.set_status, "Workflow hazirligi hata verdi.", ERR)
            self.ui(self._busy, False)
        finally:
            self.ui(self._set_ctrl, False)
            if self.stop_event.is_set():
                self.ui(self._busy, False)

    def _show_workflow_approval(self, data: dict[str, Any]) -> None:
        self._set_phase("workflow")
        stages = data["stages"]
        self.refresh_stages()
        self.set_status("Workflow onayi bekleniyor.", WARN)
        win = ctk.CTkToplevel(self.root)
        win.title("Workflow Onayi")
        win.geometry("880x650")
        win.minsize(760, 520)
        win.configure(fg_color=BG)
        win.grab_set()
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        title = data.get("summary") or "Otomatik workflow hazirlandi"
        ctk.CTkLabel(win, text=title, font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 8)
        )

        text = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        text.grid(row=1, column=0, sticky="nsew", padx=20, pady=8)
        text.insert("end", f"Proje tipi: {data.get('project_type', 'custom')}\n")
        text.insert("end", f"Brief hash: {data.get('brief_hash', '')[:12]}\n\n")
        for i, stage in enumerate(stages, 1):
            text.insert("end", f"{i}. {stage['name']} [{stage['agent']}]\n")
            text.insert("end", f"   Okur: {', '.join(stage.get('reads', [])) or '-'}\n")
            text.insert("end", f"   Yazar: {', '.join(stage.get('writes', [])) or '-'}\n")
            if stage.get("fallback_agent"):
                text.insert("end", f"   Fallback: {stage['fallback_agent']}\n")
            text.insert("end", f"   Gorev: {stage['prompt'][:220]}{'...' if len(stage['prompt']) > 220 else ''}\n\n")
        text.configure(state="disabled")

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 18))

        def cancel() -> None:
            win.destroy()
            self._busy(False)
            self.set_status("Workflow onayi iptal edildi.", WARN)

        def back_to_questions() -> None:
            win.destroy()
            self._busy(True)
            self._show_brief_questions(self.pending_brief_questions, self.pending_initial_request, self.pending_answers)

        def approve() -> None:
            win.destroy()
            self.active_workflow_data = data
            self._busy(False)
            self._launch(start_idx=1, stages=stages, reset_state=True, save_request=False)

        win.protocol("WM_DELETE_WINDOW", cancel)
        ctk.CTkButton(bottom, text="Iptal", command=cancel, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=100).pack(side="right")
        ctk.CTkButton(bottom, text="Sorulara Don", command=back_to_questions, fg_color="transparent", border_width=1, border_color=WARN, text_color=WARN, width=130).pack(side="right", padx=10)
        ctk.CTkButton(bottom, text="Onayla ve Baslat", command=approve, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=150, corner_radius=7).pack(side="right")

    # ---------------- Buton aksiyonları ----------------
    def on_send_chat_message(self) -> None:
        text = self._request_text().strip()
        if not text:
            messagebox.showerror("Mesaj yok", "Sohbete eklemek icin alttaki kutuya bir mesaj yaz.")
            return
        append_chat_entry(self.project_dir, "Kullanici", text)
        self.request_input.configure(state="normal")
        self.request_input.delete("1.0", "end")
        self.chat_mtime = None
        self._refresh_chat()
        self.set_status("Mesaj sohbete eklendi.", ACCENT)

    def on_save_request(self) -> None:
        if self._save_request_from_input(require=True):
            self.set_status(f"{REQUEST_FILE} kaydedildi.", ACCENT)

    def on_start(self) -> None:
        self._begin_smart_start()

    def on_resume(self) -> None:
        data = self._current_workflow_data()
        if not data:
            messagebox.showinfo("Orkestra", "Onayli otomatik workflow yok veya istek degismis. Once Baslat ile brief/workflow hazirla.")
            return
        stages = data["stages"]
        try:
            validate_workflow(stages)
        except WorkflowError as exc:
            messagebox.showerror("Workflow hatasi", str(exc))
            return
        state = load_state(self.project_dir)
        if state.get("workflow_hash") != workflow_hash(stages):
            messagebox.showinfo("Orkestra", "Kayitli ilerleme bu workflow ile eslesmiyor. Baslat ile yeni akisi onayla.")
            return
        start = len(state.get("completed", [])) + 1
        if start > len(stages):
            messagebox.showinfo("Orkestra", "Tum adimlar zaten bitmis. Sifirlayip bastan baslayabilirsin.")
            return
        self._launch(start_idx=start, stages=stages, reset_state=False)
        return

    def on_from(self) -> None:
        stages = self._current_stages()
        try:
            validate_workflow(stages)
        except WorkflowError as exc:
            messagebox.showerror("Workflow hatasi", str(exc))
            return
        n = simpledialog.askinteger("Adimdan basla",
                                    f"Hangi adimdan? (1-{len(stages)})",
                                    minvalue=1, maxvalue=len(stages))
        if n:
            self._launch(start_idx=n, stages=stages, reset_state=(n == 1))
        return

    def on_preview(self) -> None:
        stages = self._current_stages()
        try:
            validate_workflow(stages)
        except WorkflowError as exc:
            messagebox.showerror("Workflow hatası", str(exc))
            return
        self._clear_log()
        request_preview = self._request_text() or read_user_request(self.project_dir)
        if request_preview:
            self.write(f"Kullanici istegi: {request_preview[:220]}{'...' if len(request_preview) > 220 else ''}", "sub")
        self.write("ÖNİZLEME (dry-run) - hiçbir ajan çalıştırılmaz\n", "accent")
        for i, stage in enumerate(stages, 1):
            self.write(f"Adım {i}: {stage['name']}  [{stage['agent']}]", "accent")
            self.write(f"  Görev: {stage['prompt'][:110]}{'...' if len(stage['prompt']) > 110 else ''}", "sub")
            if stage.get("reads"):
                self.write(f"  Okur:  {', '.join(stage['reads'])}", "muted")
            if stage.get("writes"):
                self.write(f"  Yazar: {', '.join(stage['writes'])}", "muted")
        self.set_status("Önizleme gösterildi.")

    def on_reset(self) -> None:
        if messagebox.askyesno("Sıfırla", "İlerleme sıfırlanacak; üretilen dosyalar silinmez. Emin misin?"):
            p = self.project_dir / STATE_FILE
            if p.exists():
                p.unlink()
            self.failed_index = None
            self.running_index = None
            self.stage_durations.clear()
            self.progress.set(0)
            self._set_phase("istek")
            self.progress_lbl.configure(text="Hazır")
            self.refresh_stages()
            self.set_status("Durum sıfırlandı.", WARN)

    def on_open_live_preview(self) -> None:
        self._update_preview_target()
        target = self.preview_target
        if not target:
            messagebox.showinfo("Onizleme", "Onizleme icin package.json, index.html veya app.py bulunamadi.")
            return

        if target["type"] == "html":
            frame_url = self._preview_frame_url(target["url"], self.preview_viewport.get())
            webbrowser.open(frame_url)
            self._append_preview_log(f"HTML viewport acildi: {frame_url}")
            return

            with self.preview_lock:
                if self.preview_proc is not None and self.preview_proc.poll() is None:
                    frame_url = self._preview_frame_url(target.get("url", ""), self.preview_viewport.get())
                    webbrowser.open(frame_url)
                    self._append_preview_log(f"Mevcut onizleme viewport acildi: {frame_url}")
                    return

        self.preview_log.configure(state="normal")
        self.preview_log.delete("1.0", "end")
        self.preview_log.configure(state="disabled")
        threading.Thread(target=self._start_live_preview_worker, args=(target,), daemon=True).start()

    def _start_live_preview_worker(self, target: dict[str, Any]) -> None:
        try:
            if target["type"] == "node":
                npm = shutil.which("npm") or shutil.which("npm.cmd")
                if not npm:
                    self.ui(messagebox.showerror, "Onizleme", "npm bulunamadi.")
                    return
                if not (self.project_dir / "node_modules").exists():
                    self.ui(self._append_preview_log, "npm install basliyor...")
                    install = subprocess.run(
                        [npm, "install"],
                        cwd=self.project_dir,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    self.ui(self._append_preview_log, install.stdout[-4000:] if install.stdout else "npm install bitti.")
                    if install.returncode != 0:
                        self.ui(messagebox.showerror, "Onizleme", "npm install basarisiz oldu. Onizleme loguna bak.")
                        return
                cmd = [npm, "run", target.get("script", "dev")]
            elif target["type"] == "python":
                path = Path(target["path"])
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                if "streamlit" in text and (shutil.which("streamlit") or shutil.which("streamlit.exe")):
                    streamlit = shutil.which("streamlit") or shutil.which("streamlit.exe")
                    cmd = [streamlit, "run", str(path.name)]
                elif "fastapi" in text and "uvicorn" in text:
                    cmd = [sys.executable, "-m", "uvicorn", f"{path.stem}:app", "--reload"]
                else:
                    cmd = [sys.executable, str(path.name)]
            else:
                return

            self.ui(self._append_preview_log, "$ " + " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **process_kwargs(),
            )
            with self.preview_lock:
                self.preview_proc = proc

            def reader() -> None:
                try:
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        self.ui(self._append_preview_log, line.rstrip())
                except Exception as exc:
                    self.ui(self._append_preview_log, f"Log okuma hatasi: {exc}")

            threading.Thread(target=reader, daemon=True).start()
            time.sleep(2.0)
            if target.get("url"):
                frame_url = self._preview_frame_url(target["url"], self.preview_viewport.get())
                webbrowser.open(frame_url)
                self.ui(self._append_preview_log, f"Viewport tarayicida acildi: {frame_url}")
        except Exception as exc:
            self.ui(messagebox.showerror, "Onizleme", str(exc))

    def on_stop_live_preview(self) -> None:
        with self.preview_lock:
            proc = self.preview_proc
            self.preview_proc = None
        if proc and proc.poll() is None:
            kill_process_tree(proc)
            self._append_preview_log("Onizleme sureci durduruldu.")
        else:
            self._append_preview_log("Calisan onizleme yok.")

    def on_stop(self) -> None:
        self.stop_event.set()
        self._kill_current_process()
        self.decision = "stop"
        self.decision_event.set()
        self.set_status("Durduruluyor...", ERR)

    def on_close(self) -> None:
        self.closing = True
        self.stop_event.set()
        self._kill_current_process()
        with self.preview_lock:
            preview_proc = self.preview_proc
            self.preview_proc = None
        kill_process_tree(preview_proc)
        with self.terminal_lock:
            terminal_proc = self.terminal_proc
            self.terminal_proc = None
        kill_process_tree(terminal_proc)
        self.decision = "stop"
        self.decision_event.set()
        # TUM Toplevel'lar (Araclar + acik sihirbaz/aksiyon/diff diyaloglari)
        # root'tan once yok edilsin; yoksa grab/after artiklari TclError verip
        # cikis kodunu kirletir (exit 255) ve worker karar bekleyisinde asili kalir.
        for child in list(self.root.winfo_children()):
            if isinstance(child, ctk.CTkToplevel):
                try:
                    child.destroy()
                except Exception:
                    pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _decide(self, what: str) -> None:
        self.decision = what
        self._set_ctrl(True, allow_decide=False)
        self.decision_event.set()

    def on_edit_agent_roles(self) -> None:
        stages = [dict(stage) for stage in self._current_stages()]
        for stage in stages:
            stage.setdefault("reads", [])
            stage.setdefault("writes", [])
            stage.setdefault("checkpoint", True)
            stage.setdefault("timeout", WF.DEFAULT_TIMEOUT)

        win = ctk.CTkToplevel(self.root)
        win.title("Ajan Rolleri")
        win.geometry("1050x720")
        win.minsize(860, 560)
        win.configure(fg_color=BG)
        win.grab_set()
        win.columnconfigure(0, weight=2)
        win.columnconfigure(1, weight=3)
        win.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            win,
            text="Ajan Rollerini Duzenle",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(18, 8))

        left = ctk.CTkFrame(win, corner_radius=10, fg_color=SURFACE, border_width=1, border_color=BORDER_SOFT)
        left.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=8)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        role_tree = ttk.Treeview(left, columns=("idx", "name", "agent", "checkpoint"), show="headings", selectmode="browse")
        for key, text, width, anchor in (
            ("idx", "#", 42, "center"),
            ("name", "Adim", 210, "w"),
            ("agent", "Ajan", 76, "center"),
            ("checkpoint", "CP", 48, "center"),
        ):
            role_tree.heading(key, text=text)
            role_tree.column(key, width=width, minwidth=width, anchor=anchor, stretch=(key == "name"))
        role_tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        right = ctk.CTkFrame(win, corner_radius=10, fg_color=SURFACE, border_width=1, border_color=BORDER_SOFT)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 20), pady=8)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)

        selected = {"idx": 0}

        name_entry = ctk.CTkEntry(right)
        name_entry.grid(row=0, column=1, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(right, text="Adim adi").grid(row=0, column=0, sticky="w", padx=(12, 4), pady=(12, 6))

        agent_menu = ctk.CTkOptionMenu(right, values=["codex", "gemini", "claude"], width=130)
        agent_menu.grid(row=1, column=1, sticky="w", padx=12, pady=6)
        ctk.CTkLabel(right, text="Ajan").grid(row=1, column=0, sticky="w", padx=(12, 4), pady=6)

        prompt_box = ctk.CTkTextbox(right, wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        prompt_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)

        reads_entry = ctk.CTkEntry(right, placeholder_text="istek.md, sohbet.md")
        reads_entry.grid(row=3, column=1, sticky="ew", padx=12, pady=6)
        ctk.CTkLabel(right, text="Okur").grid(row=3, column=0, sticky="w", padx=(12, 4), pady=6)

        writes_entry = ctk.CTkEntry(right, placeholder_text="plan.md")
        writes_entry.grid(row=4, column=1, sticky="ew", padx=12, pady=6)
        ctk.CTkLabel(right, text="Yazar").grid(row=4, column=0, sticky="w", padx=(12, 4), pady=6)

        lower = ctk.CTkFrame(right, fg_color="transparent")
        lower.grid(row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=6)
        lower.columnconfigure(5, weight=1)
        checkpoint_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(lower, text="Checkpoint", variable=checkpoint_var, progress_color=ACCENT_BLUE).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ctk.CTkLabel(lower, text="Timeout").grid(row=0, column=1, sticky="w", padx=(0, 6))
        timeout_entry = ctk.CTkEntry(lower, width=90)
        timeout_entry.grid(row=0, column=2, sticky="w", padx=(0, 12))
        ctk.CTkLabel(lower, text="Fallback").grid(row=0, column=3, sticky="w", padx=(0, 6))
        fallback_menu = ctk.CTkOptionMenu(lower, values=["-", "codex", "gemini", "claude"], width=110)
        fallback_menu.grid(row=0, column=4, sticky="w")

        status_lbl = ctk.CTkLabel(win, text="Degisiklikleri kaydetmek icin once adimi guncelle, sonra workflow'u kaydet.", text_color=SUB)
        status_lbl.grid(row=2, column=0, columnspan=2, sticky="w", padx=20, pady=(4, 0))

        def csv_items(text: str) -> list[str]:
            return [item.strip().replace("\\", "/") for item in text.split(",") if item.strip()]

        def refresh_role_tree() -> None:
            role_tree.delete(*role_tree.get_children())
            for idx, stage in enumerate(stages):
                role_tree.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(idx + 1, stage.get("name", ""), stage.get("agent", ""), "evet" if stage.get("checkpoint") else "hayir"),
                )

        def load_stage(idx: int) -> None:
            selected["idx"] = max(0, min(idx, len(stages) - 1))
            stage = stages[selected["idx"]]
            name_entry.delete(0, "end")
            name_entry.insert(0, str(stage.get("name", "")))
            agent_menu.set(str(stage.get("agent", "codex")))
            prompt_box.delete("1.0", "end")
            prompt_box.insert("1.0", str(stage.get("prompt", "")))
            reads_entry.delete(0, "end")
            reads_entry.insert(0, ", ".join(stage.get("reads", [])))
            writes_entry.delete(0, "end")
            writes_entry.insert(0, ", ".join(stage.get("writes", [])))
            checkpoint_var.set(bool(stage.get("checkpoint", True)))
            timeout_entry.delete(0, "end")
            timeout_entry.insert(0, str(stage.get("timeout", WF.DEFAULT_TIMEOUT)))
            fallback_menu.set(str(stage.get("fallback_agent") or "-"))
            role_tree.selection_set(str(selected["idx"]))

        def collect_stage() -> dict[str, Any] | None:
            try:
                timeout = int(timeout_entry.get().strip() or WF.DEFAULT_TIMEOUT)
            except ValueError:
                messagebox.showerror("Rol", "Timeout pozitif tam sayi olmali.")
                return None
            fallback = fallback_menu.get().strip()
            stage: dict[str, Any] = {
                "name": name_entry.get().strip(),
                "agent": agent_menu.get().strip(),
                "prompt": prompt_box.get("1.0", "end-1c").strip(),
                "reads": csv_items(reads_entry.get()),
                "writes": csv_items(writes_entry.get()),
                "checkpoint": bool(checkpoint_var.get()),
                "timeout": timeout,
            }
            if fallback and fallback != "-":
                stage["fallback_agent"] = fallback
            try:
                validate_workflow([stage])
            except WorkflowError as exc:
                messagebox.showerror("Rol", str(exc))
                return None
            return stage

        def update_stage() -> bool:
            stage = collect_stage()
            if stage is None:
                return False
            stages[selected["idx"]] = stage
            refresh_role_tree()
            load_stage(selected["idx"])
            status_lbl.configure(text="Adim guncellendi. Workflow'u kaydedebilirsin.", text_color=ACCENT_BLUE)
            return True

        def add_stage() -> None:
            if len(stages) >= 8:
                messagebox.showerror("Rol", "Workflow en fazla 8 adim olabilir.")
                return
            insert_at = selected["idx"] + 1
            stages.insert(
                insert_at,
                {
                    "name": "Yeni Adim",
                    "agent": "codex",
                    "prompt": "istek.md ve sohbet.md dosyalarini oku; bu adimin gorevini tamamla.",
                    "reads": ["istek.md", "sohbet.md"],
                    "writes": ["yeni-adim.md"],
                    "checkpoint": True,
                    "timeout": WF.DEFAULT_TIMEOUT,
                },
            )
            refresh_role_tree()
            load_stage(insert_at)

        def delete_stage() -> None:
            if len(stages) <= 3:
                messagebox.showerror("Rol", "Workflow en az 3 adim kalmali.")
                return
            idx = selected["idx"]
            del stages[idx]
            refresh_role_tree()
            load_stage(max(0, idx - 1))

        def move(delta: int) -> None:
            idx = selected["idx"]
            new_idx = idx + delta
            if not (0 <= new_idx < len(stages)):
                return
            stages[idx], stages[new_idx] = stages[new_idx], stages[idx]
            refresh_role_tree()
            load_stage(new_idx)

        def save_workflow() -> None:
            update_stage()
            current = self._saved_or_input_request().strip()
            current_hash = brief_hash(current)
            data = {
                "summary": "GUI'den duzenlenen ajan rolleri",
                "project_type": "custom",
                "brief_hash": current_hash,
                "stages": stages,
            }
            try:
                normalized = validate_generated_workflow(data)
                save_generated_workflow(self.project_dir, normalized)
                self.active_workflow_data = normalized
                state = load_state(self.project_dir)
                new_hash = workflow_hash(normalized["stages"])
                if state.get("workflow_hash") != new_hash:
                    state["completed"] = []
                    state["workflow_hash"] = new_hash
                    save_state(self.project_dir, state)
                self.refresh_stages()
                self._force_refresh_files()
                status_lbl.configure(text="Ajan rolleri kaydedildi ve aktif workflow yapildi.", text_color=ACCENT)
                self.set_status("Ajan rolleri kaydedildi.", ACCENT)
            except Exception as exc:
                messagebox.showerror("Rol", str(exc))

        def on_select(_event: Any) -> None:
            selection = role_tree.selection()
            if selection:
                load_stage(int(selection[0]))

        role_tree.bind("<<TreeviewSelect>>", on_select)

        controls = ctk.CTkFrame(win, fg_color="transparent")
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 18))
        ctk.CTkButton(controls, text="Kapat", command=win.destroy, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=90).pack(side="right")
        ctk.CTkButton(controls, text="Workflow Kaydet", command=save_workflow, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=140, corner_radius=7).pack(side="right", padx=8)
        ctk.CTkButton(controls, text="Adimi Guncelle", command=update_stage, fg_color=ACCENT_BLUE, text_color=BG, hover_color="#0ea5e9", width=130, corner_radius=7).pack(side="right", padx=8)
        ctk.CTkButton(controls, text="Sil", command=delete_stage, fg_color="transparent", border_width=1, border_color=ERR, text_color=ERR, width=70).pack(side="left")
        ctk.CTkButton(controls, text="Ekle", command=add_stage, fg_color="transparent", border_width=1, border_color=ACCENT, text_color=ACCENT, width=70).pack(side="left", padx=8)
        ctk.CTkButton(controls, text="Yukari", command=lambda: move(-1), fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=80).pack(side="left")
        ctk.CTkButton(controls, text="Asagi", command=lambda: move(1), fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, width=80).pack(side="left", padx=8)

        refresh_role_tree()
        load_stage(0)

    def on_edit_workflow(self) -> None:
        path = Path(WF.__file__).resolve()
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror("Workflow", f"workflow.py okunamadı:\n{exc}")
            return

        win = ctk.CTkToplevel(self.root)
        win.title("workflow.py düzenle")
        win.geometry("900x700")
        win.minsize(740, 520)
        win.configure(fg_color=BG)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        # CTK toplevel Windows üzerinde her zaman en önde kalabilir veya açılınca arkaya düşebilir. Grab set:
        win.grab_set()

        ctk.CTkLabel(win, text=str(path), text_color=SUB, font=ctk.CTkFont(family="Segoe UI", size=12)).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        text_edit = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Consolas", size=13), wrap="none", corner_radius=8, fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT, undo=True)
        text_edit.grid(row=1, column=0, sticky="nsew", padx=20, pady=5)
        text_edit.insert("1.0", source)

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=20, pady=15)
        status_lbl = ctk.CTkLabel(bottom, text="Kaydetmeden önce söz dizimi ve adım alanları kontrol edilir.", text_color=SUB)
        status_lbl.pack(side="left")

        def validate_source(src: str) -> None:
            # Guvenlik: kod CALISTIRILMADAN (exec yok) AST ile dogrulanir.
            # PROJECT_DIR / DEFAULT_TIMEOUT / STAGES yalnizca literal atamalardan okunur.
            tree = ast.parse(src, filename=str(path))
            found: dict[str, Any] = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                    names = [node.target.id]
                    value = node.value
                else:
                    continue
                for name in names:
                    if name in ("PROJECT_DIR", "DEFAULT_TIMEOUT", "STAGES"):
                        try:
                            found[name] = ast.literal_eval(value)
                        except (ValueError, SyntaxError):
                            raise WorkflowError(
                                f"{name} sabit (literal) bir degerle atanmali. "
                                "Guvenlik geregi workflow.py icindeki kod calistirilmadan dogrulanir; "
                                "hesaplama/fonksiyon cagrisi kullanma."
                            )
            project_dir = found.get("PROJECT_DIR")
            if not isinstance(project_dir, str) or not project_dir.strip():
                raise WorkflowError("PROJECT_DIR boş olmayan metin olmalı.")
            default_timeout = found.get("DEFAULT_TIMEOUT", 1800)
            if not isinstance(default_timeout, int) or default_timeout <= 0:
                raise WorkflowError("DEFAULT_TIMEOUT pozitif tam sayı olmalı.")
            validate_workflow(found.get("STAGES"))

        def save() -> None:
            src = text_edit.get("1.0", "end-1c")
            try:
                validate_source(src)
            except SyntaxError as exc:
                messagebox.showerror("Söz dizimi hatası", f"{exc.msg}\nSatır: {exc.lineno}")
                return
            except Exception as exc:
                messagebox.showerror("Workflow hatası", str(exc))
                return

            try:
                path.write_text(src, encoding="utf-8")
                importlib.reload(WF)
                validate_workflow(WF.STAGES)
                self._sync_project_dir()
                self._load_request_input()
                self.refresh_stages()
                self.refresh_tools()
                status_lbl.configure(text="Kaydedildi.", text_color=ACCENT)
                self.set_status("workflow.py kaydedildi.", ACCENT)
            except Exception as exc:
                messagebox.showerror("Kaydetme hatası", str(exc))

        ctk.CTkButton(bottom, text="Kapat", command=win.destroy, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, hover_color=HOVER, width=100).pack(side="right")
        ctk.CTkButton(bottom, text="Kaydet", command=save, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=100, corner_radius=7).pack(side="right", padx=10)

    # ---------------- Çalıştırma ----------------
    def _launch(
        self,
        start_idx: int,
        stages: list[dict[str, Any]] | None = None,
        *,
        reset_state: bool = False,
        save_request: bool = True,
    ) -> None:
        if self.running:
            return
        active_stages = stages or self._current_stages()
        try:
            validate_workflow(active_stages)
        except WorkflowError as exc:
            messagebox.showerror("Workflow hatası", str(exc))
            return
        if start_idx > len(active_stages):
            # Toparla > "dosyalara gore" tum adimlari bitmis sayarsa buraya duser;
            # sahte "TAMAMLANDI" kosusu yerine net bilgi ver.
            messagebox.showinfo("Orkestra", "Tüm adımlar zaten tamamlanmış görünüyor. Yeniden çalıştırmak için 'Sıfırla' kullan.")
            return

        if save_request and not self._save_request_from_input(require=workflow_uses_request(active_stages)):
            return

        # Token korumasi: ayni workflow'da zaten tamamlanmis adim varsa, pahali
        # adimlari (orn. planlama) bosa tekrar kosmamak icin kullaniciya sor.
        if start_idx == 1:
            existing = load_state(self.project_dir)
            done = [s for s in existing.get("completed", []) if isinstance(s, int)]
            if done and existing.get("workflow_hash") == workflow_hash(active_stages):
                choice = messagebox.askyesnocancel(
                    "Tamamlanmış adımlar var",
                    f"Bu akışta zaten {len(done)} adım tamamlanmış görünüyor "
                    "(ör. pahalı planlama adımı).\n\n"
                    "Baştan başlamak bu adımları TEKRAR çalıştırır ve gereksiz "
                    "token / kullanım limiti harcar.\n\n"
                    "• Evet  → Kaldığın yerden devam et (önerilen)\n"
                    "• Hayır → Yine de baştan başla\n"
                    "• İptal → Vazgeç",
                )
                if choice is None:
                    return
                if choice:  # Evet -> kaldigi yerden devam
                    start_idx = len(done) + 1
                    reset_state = False
                    if start_idx > len(active_stages):
                        messagebox.showinfo(
                            "Orkestra",
                            "Tüm adımlar zaten tamamlanmış. Yeniden çalıştırmak için 'Durumu sıfırla' kullan.",
                        )
                        return

        if reset_state or start_idx == 1:
            state_file = self.project_dir / STATE_FILE
            if state_file.exists():
                state_file.unlink()

        missing_tools = missing_required_tools(active_stages[start_idx - 1:])
        if missing_tools:
            messagebox.showerror(
                "Eksik ajan komutu",
                "Gerçek akış başlatılamaz.\n\n"
                f"Kurulması gereken komutlar: {', '.join(missing_tools)}\n\n"
                f"Beklenen gercek komutlar: {expected_agent_commands_label()}",
            )
            self.refresh_tools()
            return

        self._sync_project_dir()
        (self.project_dir / LOG_DIR).mkdir(parents=True, exist_ok=True)
        ensure_chat_file(self.project_dir)
        append_chat_entry(
            self.project_dir,
            "Orkestra",
            f"Akis GUI'den baslatildi. Baslangic adimi: {start_idx}. Checkpoint modu: {'acik' if bool(self.checkpoint_var.get()) else 'kapali'}.",
        )
        self.chat_mtime = None
        self._clear_log()
        self.stop_event.clear()
        self.decision_event.clear()
        self.decision = None
        self.failed_index = None
        self.running_index = None
        self.stage_durations.clear()
        self.progress.set(0)
        self.progress_lbl.configure(text="Başlıyor")

        # Baslamadan saglik kontrolu: engeller varsa goster ve durdur.
        # (busy ANCAK tum kapilardan gecince acilir; yoksa UI kilitli kalirdi.)
        findings = preflight_check(self.project_dir, active_stages, start_idx)
        if start_idx > 1:
            findings = [f for f in findings if "yarım iş" not in f["mesaj"]]
        errors = [f["mesaj"] for f in findings if f["level"] == "hata"]
        warns = [f["mesaj"] for f in findings if f["level"] == "uyari"]
        if errors:
            messagebox.showerror("Başlatılamıyor — sağlık kontrolü", "\n\n".join(errors))
            return
        if warns and not messagebox.askyesno(
            "Sağlık kontrolü uyarıları", "\n\n".join(warns) + "\n\nYine de başlansın mı?"
        ):
            return

        self._busy(True)
        self._set_ctrl(True, allow_decide=False)
        # Worker thread tkinter Var'larina dokunmamali: degerler ANA thread'de
        # simdi kopyalanir, worker yalnizca kopyalari okur (threaded Tcl'de
        # Var.get() 'main thread is not in main loop' ile cokebilir).
        self._opts_max_attempts = self._max_attempts()
        self._opts_agent_fallback = bool(self.agent_fallback_var.get())
        self._opts_long_step_warning = bool(self.long_step_warning_var.get())
        self._opts_auto_fix = bool(self.auto_fix_var.get())
        self._last_fail_reason = ""
        append_event(self.project_dir, "run_started", run_id=self.snapshot_run_id, start_idx=start_idx, stages=len(active_stages))

        self._set_phase("calistir")
        use_checkpoints = bool(self.checkpoint_var.get())
        self.worker = threading.Thread(
            target=self._run_pipeline,
            args=(start_idx, use_checkpoints, active_stages),
            daemon=True,
        )
        self.worker.start()

    def _run_pipeline(self, start_idx: int, use_checkpoints: bool, stages: list[dict[str, Any]]) -> None:
        total = len(stages)
        current_workflow_hash = workflow_hash(stages)
        state = load_state(self.project_dir)
        if state.get("workflow_hash") != current_workflow_hash:
            state["completed"] = []
            state["workflow_hash"] = current_workflow_hash
        i = start_idx
        stopped = False

        try:
            while i <= total and not self.stop_event.is_set():
                stage = stages[i - 1]
                self.ui(self._mark_running, i, total, stage["name"])
                self.q(f"\n=== ADIM {i}/{total}: {stage['name']}  [{stage['agent']}] ===", "accent")
                append_chat_entry(
                    self.project_dir,
                    "Orkestra",
                    (
                        f"Sira {i}/{total}: {stage_ref(stage, i)} basliyor.\n"
                        f"- Bu adimin gorevi: {stage['prompt'][:220]}{'...' if len(stage['prompt']) > 220 else ''}\n"
                        f"- Sonraki devir: {next_stage_ref(stages, i)}"
                    ),
                )

                missing = check_inputs(self.project_dir, stage)
                if missing:
                    self.q(f"! Gereken dosyalar yok: {', '.join(missing)}. Duruyorum.", "err")
                    append_chat_entry(
                        self.project_dir,
                        "Orkestra",
                        f"{stage_ref(stage, i)} baslayamadi. Eksik girdiler: {', '.join(missing)}",
                    )
                    self._record_metric(stage, i, "failed", 0.0, f"missing inputs: {', '.join(missing)}", False)
                    self.ui(self._mark_failed, i)
                    break

                try:
                    meta = create_snapshot(self.project_dir, self.snapshot_run_id, i, stage)
                    self.q(f"Snapshot alindi: {meta.get('id')}", "sub")
                    self.ui(self._refresh_history, False)
                except Exception as exc:
                    self.q(f"! Snapshot alinamadi: {exc}", "warn")

                self._stage_start_notice(stage, i, total)
                before_snapshot = self._project_snapshot()
                max_attempts = self._max_attempts()
                attempt_no = 1
                active_stage = stage
                fallback_used = False
                ok, elapsed, reason, output_text = self._run_one(stage, i, total, stages)
                fallback = self._fallback_for_output(stage, output_text)
                if not ok and reason == "exit" and fallback and find_tool(fallback):
                    fallback_used = True
                    self.q(
                        f"! {stage['agent']} hata verdi; ayni adim {fallback.upper()} ile devraliniyor.",
                        "warn",
                    )
                    append_chat_entry(
                        self.project_dir,
                        "Orkestra",
                        f"{stage_ref(stage, i)} {stage['agent']} ile tamamlanamadi. Ayni gorev {fallback} ajanina devrediliyor.",
                    )
                    active_stage = with_fallback_agent(stage, fallback)
                    ok, elapsed, reason, output_text = self._run_one(active_stage, i, total, stages)
                while not ok and not self.stop_event.is_set() and reason != "stopped" and attempt_no < max_attempts:
                    attempt_no += 1
                    # Retry stratejisi: hata tipine gore kor tekrar yerine akilli hamle.
                    strat = retry_strategy(classify_failure(reason, output_text)["category"])
                    if strat.get("prompt_suffix"):
                        stage = dict(stage)
                        stage["prompt"] += "\n\n" + strat["prompt_suffix"].replace(
                            "{writes}", ", ".join(stage.get("writes", [])) or "-"
                        )
                        self.q(f"Prompt hata tipine gore guclendirildi ({strat.get('not', '')}).", "warn")
                    self.q(f"↺ {i}. adim tekrar deneniyor ({attempt_no}/{max_attempts})...", "warn")
                    append_chat_entry(
                        self.project_dir,
                        "Orkestra",
                        f"{stage_ref(stage, i)} tekrar deneniyor. Deneme: {attempt_no}/{max_attempts}",
                    )
                    active_stage = stage
                    ok, elapsed, reason, output_text = self._run_one(stage, i, total, stages)
                    fallback = self._fallback_for_output(stage, output_text)
                    if not ok and reason == "exit" and fallback and find_tool(fallback):
                        fallback_used = True
                        self.q(f"! {stage['agent']} hata verdi; ayni adim {fallback.upper()} ile devraliniyor.", "warn")
                        append_chat_entry(
                            self.project_dir,
                            "Orkestra",
                            f"{stage_ref(stage, i)} {stage['agent']} ile tamamlanamadi. Ayni gorev {fallback} ajanina devrediliyor.",
                        )
                        active_stage = with_fallback_agent(stage, fallback)
                        ok, elapsed, reason, output_text = self._run_one(active_stage, i, total, stages)
                if self.stop_event.is_set() or reason == "stopped":
                    stopped = True
                    self.q("\nDurduruldu.", "warn")
                    append_chat_entry(self.project_dir, "Orkestra", f"{stage_ref(active_stage, i)} kullanici tarafindan durduruldu.")
                    self._record_metric(active_stage, i, "stopped", elapsed, reason, fallback_used)
                    break
                if not ok:
                    notice = usage_limit_notice(active_stage.get("agent", ""), output_text)
                    if notice:
                        self.q(f"⛔ {notice}", "err")
                        self.ui(messagebox.showwarning, "Kullanım limiti doldu", notice)
                    info = classify_failure(reason, output_text)
                    self._last_fail_reason = f"{info['category']}: {reason}"
                    self.q(f"⛔ Hata türü: {info['label']} — Öneri: {info['advice']}", "err")
                    self.ui(self.set_status, f"Hata: {info['label']}", ERR)
                    self.ui(self._notify, "error")
                    self.ui(self._show_error_actions, i, dict(active_stage), info["label"])
                    self.q(f"! {i}. adım başarısız oldu. Sorunu gider, 'Adımdan' ile {i}'den devam et.", "err")
                    append_chat_entry(
                        self.project_dir,
                        active_stage["agent"].upper(),
                        f"{stage_ref(active_stage, i)} basarisiz oldu. Sebep: {reason}.",
                    )
                    self._record_metric(active_stage, i, "failed", elapsed, reason, fallback_used)
                    self.ui(self._mark_failed, i)
                    break

                miss_out = verify_outputs(self.project_dir, stage)
                if miss_out:
                    self.q(f"! Beklenen dosyalar oluşmamış: {', '.join(miss_out)}", "warn")
                    append_chat_entry(
                        self.project_dir,
                        active_stage["agent"].upper(),
                        f"{stage_ref(active_stage, i)} tamamlandi gibi gorundu ama beklenen ciktılar eksik: {', '.join(miss_out)}",
                    )
                    self.ui(self._mark_failed, i)
                    break

                self.q(f"✓ Ajan komutu bitti. Süre: {fmt_seconds(elapsed)}", "ok")
                after_snapshot = self._project_snapshot()
                if self._stage_needs_diff_approval(active_stage, before_snapshot, after_snapshot):
                    summary, diff_text = self._build_diff_text(before_snapshot, after_snapshot)
                    decision = self._request_diff_approval(active_stage, i, summary, diff_text)
                    if decision == "stop":
                        stopped = True
                        self.q("Degisiklik onayi iptal edildi. Akis durduruldu.", "warn")
                        append_chat_entry(self.project_dir, "Orkestra", f"{stage_ref(active_stage, i)} degisiklik onayinda durduruldu.")
                        break
                    if decision == "retry":
                        self.stage_durations.pop(i, None)
                        self.q(f"↺ {i}. adim degisiklik istegiyle tekrar calisacak.", "warn")
                        continue

                runtime_before = self._project_snapshot()
                if not self._auto_fix_runtime_loop(active_stage, i, total, stages):
                    self._record_metric(active_stage, i, "failed", elapsed, "runtime auto-fix failed", fallback_used)
                    self.ui(self._mark_failed, i)
                    break
                runtime_after = self._project_snapshot()
                if self._stage_needs_diff_approval(active_stage, runtime_before, runtime_after):
                    summary, diff_text = self._build_diff_text(runtime_before, runtime_after)
                    decision = self._request_diff_approval(active_stage, i, summary, diff_text)
                    if decision == "stop":
                        stopped = True
                        self.q("Otomatik duzeltme diff onayi iptal edildi. Akis durduruldu.", "warn")
                        break
                    if decision == "retry":
                        self.stage_durations.pop(i, None)
                        self.q(f"↺ {i}. adim otomatik duzeltme istegiyle tekrar calisacak.", "warn")
                        continue

                produced = ", ".join(stage.get("writes", [])) or "-"
                append_chat_entry(
                    self.project_dir,
                    active_stage["agent"].upper(),
                    (
                        f"{stage_ref(active_stage, i)} tamamlandi.\n"
                        f"- Sure: {fmt_seconds(elapsed)}\n"
                        f"- Uretilen/beklenen ciktılar: {produced}\n"
                        f"- Kanka is sende: {next_stage_ref(stages, i)}\n"
                        "- Checkpoint aciksa kullanici onayi geldikten sonra devam edilecek."
                    ),
                )
                if i not in state["completed"]:
                    state["completed"].append(i)
                save_state(self.project_dir, state)
                self._record_metric(active_stage, i, "success", elapsed, "", fallback_used)
                record_stage_decision(
                    self.project_dir, self.snapshot_run_id, i, active_stage,
                    produced_files(self.project_dir, [active_stage]),
                    extract_last_handoff(self.project_dir, active_stage.get("agent", "")),
                )
                self.ui(self._mark_done, i, elapsed, total)

                if use_checkpoints and stage.get("checkpoint") and i < total:
                    self.q("⏸ Checkpoint: devam edeyim mi, bu adımı tekrarlayayım mı?", "warn")
                    self.ui(self.set_status, f"Adım {i} bitti. Karar bekleniyor...", WARN)
                    self.ui(self._notify, "checkpoint")
                    self.ui(self._set_ctrl, True, True)
                    self.decision_event.clear()
                    while not self.decision_event.wait(0.1):
                        if self.stop_event.is_set():
                            break
                    self.ui(self._set_ctrl, True, False)
                    if self.decision == "stop" or self.stop_event.is_set():
                        stopped = True
                        self.q("Durduruldu.", "warn")
                        break
                    if self.decision == "retry":
                        state["completed"] = [x for x in state["completed"] if x != i]
                        save_state(self.project_dir, state)
                        self.stage_durations.pop(i, None)
                        self.q(f"↺ Adım {i} tekrarlanıyor...", "warn")
                        self.decision = None
                        continue
                    self.decision = None

                i += 1

            if i > total and not self.stop_event.is_set():
                self.q("\n✓✓ TÜM AKIŞ TAMAMLANDI", "ok")
                self.ui(self.set_status, "Tamamlandı. Çıktıları gözden geçir, sonra Teslim paketi oluştur.", ACCENT)
                self.ui(lambda: self.progress_lbl.configure(text=f"{total}/{total} tamam"))
                self.ui(self._set_phase, "teslim")
                self._record_run("complete", stages)
                self.ui(self._notify, "done")
            elif stopped:
                self.ui(self.set_status, "Durduruldu.", WARN)
                self.ui(self._set_phase, "kontrol")
                self._record_run("stopped", stages, error="stopped")
            else:
                self.ui(self.set_status, "Durdu.", WARN)
                self.ui(self._set_phase, "kontrol")
                self._record_run("failed", stages, error=getattr(self, "_last_fail_reason", ""))
                self.ui(self._notify, "error")
        except Exception as exc:
            logger.exception("Pipeline worker beklenmeyen hata")
            self.q(f"! Beklenmeyen hata: {exc}", "err")
            self.ui(self.set_status, "Hata oluştu.", ERR)
        finally:
            with self.proc_lock:
                self.proc = None
            self.ui(self._busy, False)
            self.ui(self._set_ctrl, False)
            self.ui(self.refresh_stages)

    def _run_one(self, stage: dict[str, Any], idx: int, total: int, stages: list[dict[str, Any]]) -> tuple[bool, float, str, str]:
        # Surec kosturma mantigi runner.run_agent_stage'de (web_panel ile ortak kaynak).
        # GUI boylece per-ajan stuck/sessizlik tespiti ve genel output-grace kazanir.
        current: list[Any] = [None]

        def register_proc(p: Any) -> None:
            with self.proc_lock:
                if p is None:
                    if self.proc is current[0]:
                        self.proc = None
                else:
                    current[0] = p
                    self.proc = p

        ok, elapsed, reason, output_text = run_agent_stage(
            stage,
            idx,
            total,
            stages,
            self.project_dir,
            stop_event=self.stop_event,
            log=self.q,
            on_proc=register_proc,
        )
        if reason == "not-found":
            self.q(f"! '{stage['agent']}' bulunamadı. Kurulu mu / PATH'te mi?", "err")
        return ok, elapsed, reason, output_text

    def _kill_current_process(self) -> None:
        with self.proc_lock:
            proc = self.proc
        kill_process_tree(proc)


def main() -> None:
    root = ctk.CTk()
    OrkestraApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
