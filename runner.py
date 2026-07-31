#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Maestro - Ortak ajan surec kosucusu (runner).

gui.py ve web_panel.py icinde kopyalanmis olan _run_one dongusunun tek kaynagi.
Bir ajan CLI surecini baslatir ve su isleri tek yerden yonetir:
- canli cikti akisi (reader thread) + akis ici limit/kota fallback tespiti
- zaman asimi ve kullanici durdurmasi
- per-ajan sessizlik (stuck) tespiti ve cikti-hazir zarafet suresi (output grace)
- kullanici kaynakli "tamamlandi say" / "fallback tetikle" olaylari (opsiyonel)
- Antigravity transcript ozeti

Donus sozlesmesi her iki arayuzle ayni: (ok, gecen_sure, sebep, cikti_metni).
sebep: "ok" | "not-found" | "stopped" | "timeout" | "stuck" | "exit".
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any, Callable

import workflow as WF
from orkestra import (
    AGENT_STUCK_POLICIES,
    append_event,
    build_command,
    fallback_agent_for,
    find_tool,
    is_antigravity_gemini_stage,
    kill_process_tree,
    latest_antigravity_transcript,
    process_env,
    process_kwargs,
    read_antigravity_transcript_summary,
    resolve_command,
    verify_outputs,
)


def run_agent_stage(
    stage: dict[str, Any],
    idx: int,
    total: int,
    stages: list[dict[str, Any]],
    project_dir: str | os.PathLike[str],
    *,
    stop_event: threading.Event,
    log: Callable[[str], None],
    force_complete_event: threading.Event | None = None,
    force_fallback_event: threading.Event | None = None,
    on_proc: Callable[[subprocess.Popen[str] | None], None] | None = None,
    on_activity: Callable[[], None] | None = None,
) -> tuple[bool, float, str, str]:
    """Tek adimin ajan surecini kosar; cikti geldikce log(satir) cagirilir.

    on_proc(proc)  -> surec basladiginda; on_proc(None) -> surec sahipligi bitince.
    on_activity()  -> her cikti satirinda (arayuz "son cikti" zamani icin).
    """
    cmd = build_command(stage, idx=idx, total=total, stages=stages, project_dir=project_dir)
    timeout = int(stage.get("timeout", WF.DEFAULT_TIMEOUT))
    preview = " ".join(cmd[:2])
    run_cmd = resolve_command(cmd)
    log(f"$ {preview} ... timeout={timeout}sn")
    append_event(project_dir, "stage_started", idx=idx, agent=str(stage.get("agent", "")), stage=str(stage.get("name", "")))
    start = time.monotonic()
    start_wall = time.time()

    try:
        proc = subprocess.Popen(
            run_cmd,
            cwd=project_dir,
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
        append_event(project_dir, "stage_finished", idx=idx, agent=str(stage.get("agent", "")), ok=False, reason="not-found", elapsed=0)
        return False, 0.0, "not-found", ""

    if on_proc:
        on_proc(proc)

    output_lines: list[str] = []
    fallback_event = threading.Event()
    activity_lock = threading.Lock()
    last_output_at = time.time()
    output_ready_at: float | None = None
    forced_complete = False
    reason = "ok"

    def touch_activity() -> None:
        nonlocal last_output_at
        with activity_lock:
            last_output_at = time.time()
        if on_activity:
            on_activity()

    def reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if stop_event.is_set():
                    break
                touch_activity()
                clean = line.rstrip()
                output_lines.append(clean)
                log("  " + clean)
                recent_output = "\n".join(output_lines[-24:])
                fallback = fallback_agent_for(stage, recent_output)
                if fallback and find_tool(fallback):
                    fallback_event.set()
                    append_event(project_dir, "fallback_detected", idx=idx, agent=str(stage.get("agent", "")), fallback=fallback)
                    log("Fallback tetikleyen ajan limit/kota hatasi algilandi; mevcut surec durduruluyor.")
                    kill_process_tree(proc)
                    break
        except Exception as exc:
            log(f"Log okuma hatasi: {exc}")

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    agent_name = str(stage.get("agent", "default")).lower()
    policy = AGENT_STUCK_POLICIES.get(agent_name, AGENT_STUCK_POLICIES["default"])

    try:
        while proc.poll() is None:
            if fallback_event.is_set():
                reason = "exit"
                kill_process_tree(proc)
                break
            if force_complete_event is not None and force_complete_event.is_set():
                force_complete_event.clear()
                forced_complete = True
                output_lines.append("[Maestro] Kullanici tarafindan islem manuel tamamlandi sayildi.")
                log("Kullanici karari: Tamamlandi say")
                kill_process_tree(proc)
                break
            if force_fallback_event is not None and force_fallback_event.is_set():
                force_fallback_event.clear()
                reason = "exit"
                output_lines.append("[Maestro] Kullanici tarafindan fallback tetiklendi.")
                log("Kullanici karari: Fallback tetikle")
                kill_process_tree(proc)
                break
            if stop_event.is_set():
                reason = "stopped"
                kill_process_tree(proc)
                break
            if time.monotonic() - start > timeout:
                reason = "timeout"
                kill_process_tree(proc)
                log(f"Zaman asimi: {timeout}sn")
                break

            # Cikti-hazir zarafet suresi: beklenen dosyalar olustuysa ve ajan
            # kapanmiyorsa, policy["output_grace"] sonrasi tamamlandi sayilir.
            missing_outputs = verify_outputs(project_dir, stage)
            has_writes = bool(stage.get("writes"))
            if has_writes and not missing_outputs:
                now = time.monotonic()
                if output_ready_at is None:
                    output_ready_at = now
                    log(f"[{agent_name.upper()}] Beklenen tum ciktilar olustu; kapanmasi bekleniyor.")
                elif now - output_ready_at >= policy["output_grace"]:
                    forced_complete = True
                    output_lines.append(f"[Maestro] {agent_name.upper()} cikti urettikten sonra kapanmadi; surec kapatildi.")
                    log(f"{agent_name.upper()} cikti urettikten sonra kapanmadi; adim tamamlandi sayilip surec kapatiliyor.")
                    kill_process_tree(proc)
                    break
            else:
                output_ready_at = None

            # Sessizlik (stuck) tespiti: ajan policy["silent_stuck"] sn cikti
            # uretmezse takildi sayilir ve surec kapatilir.
            with activity_lock:
                silent_for = time.time() - last_output_at
            if silent_for > policy["silent_stuck"]:
                reason = "stuck"
                output_lines.append(f"[Maestro] {agent_name.upper()} cok uzun sure sessiz kaldi ({int(silent_for)}sn). Surec kapatildi.")
                log(f"[{agent_name.upper()}] Cok uzun sure sessiz kaldi ({int(silent_for)}sn). Surec olduruldu.")
                kill_process_tree(proc)
                break
            time.sleep(0.1)
    finally:
        # Istisna/KeyboardInterrupt yolunda cocuk surec yetim kalmasin
        # (normal yollarda surec zaten bitmistir; kill idempotenttir).
        kill_process_tree(proc)
        reader_thread.join(timeout=1.5)
        if on_proc:
            on_proc(None)

    elapsed = time.monotonic() - start
    if fallback_event.is_set() and reason == "ok":
        # Reader fallback tespit edip sureci oldurdu ama poll dongusu bunu
        # goremeden cikti; limit sinyali kaybolmasin.
        reason = "exit"
    if is_antigravity_gemini_stage(stage):
        transcript = latest_antigravity_transcript(start_wall)
        if transcript:
            summary = read_antigravity_transcript_summary(transcript)
            if summary:
                log("Antigravity transcript ozeti:")
                for line in summary.splitlines():
                    log("  " + line)
                output_lines.append(summary)
    output_text = "\n".join(output_lines)
    if forced_complete:
        ok, final_reason = True, "ok"
    elif reason != "ok":
        ok, final_reason = False, reason
    elif proc.returncode != 0:
        log(f"Ajan hata dondurdu: exit {proc.returncode}")
        ok, final_reason = False, "exit"
    else:
        ok, final_reason = True, "ok"
    append_event(
        project_dir, "stage_finished",
        idx=idx, agent=str(stage.get("agent", "")), ok=ok,
        reason=final_reason, elapsed=round(elapsed, 2), forced=forced_complete,
    )
    return ok, elapsed, final_reason, output_text
