# -*- coding: utf-8 -*-
"""runner.run_agent_stage'in dogrudan testleri: timeout, force olaylari,
akis ici fallback tespiti (inceleme #8: runner yollari testsizdi)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import orkestra
from runner import run_agent_stage

FAKE_AGENT = Path(__file__).resolve().parent / "fake_agent.py"


def _patch_agents(monkeypatch):
    fake = [sys.executable, str(FAKE_AGENT), "{prompt}"]
    patched = {"codex": list(fake), "gemini": list(fake), "claude": list(fake)}
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", patched)
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable if tool in patched else None)


def _run(project_dir, stage, **kw):
    return run_agent_stage(
        stage, 1, 1, [stage], project_dir,
        stop_event=kw.pop("stop_event", threading.Event()),
        log=lambda *_: None,
        **kw,
    )


def test_runner_timeout(project_dir, monkeypatch):
    _patch_agents(monkeypatch)
    stage = {"name": "Takilan", "agent": "codex", "prompt": "HANG", "reads": [], "writes": [], "timeout": 1}
    ok, _, reason, _ = _run(project_dir, stage)
    assert not ok and reason == "timeout"


def test_runner_force_complete_event(project_dir, monkeypatch):
    _patch_agents(monkeypatch)
    ev = threading.Event()
    ev.set()  # kullanici "tamamlandi say" demis gibi
    stage = {"name": "Uzun", "agent": "codex", "prompt": "HANG", "reads": [], "writes": [], "timeout": 30}
    ok, _, reason, out = _run(project_dir, stage, force_complete_event=ev)
    assert ok and reason == "ok"
    assert "manuel tamamlandi" in out
    assert not ev.is_set()  # tuketildi


def test_runner_force_fallback_event(project_dir, monkeypatch):
    _patch_agents(monkeypatch)
    ev = threading.Event()
    ev.set()
    stage = {"name": "Uzun", "agent": "codex", "prompt": "HANG", "reads": [], "writes": [], "timeout": 30}
    ok, _, reason, out = _run(project_dir, stage, force_fallback_event=ev)
    assert not ok and reason == "exit"
    assert "fallback tetiklendi" in out


def test_runner_inline_fallback_detection_reports_exit(project_dir, monkeypatch):
    # LIMITFAIL: ajan usage-limit basip cikar; reader fallback tespit eder.
    # Yaris duzeltmesi: sonuc asla ok/basarili raporlanMAmali.
    _patch_agents(monkeypatch)
    stage = {"name": "Limitli", "agent": "claude", "prompt": "LIMITFAIL gorev",
             "reads": [], "writes": [], "timeout": 30, "fallback_agent": "codex"}
    ok, _, reason, _ = _run(project_dir, stage)
    assert not ok and reason == "exit"
    events = [e["event"] for e in orkestra.load_events(project_dir)]
    assert "fallback_detected" in events


def test_web_panel_clears_stale_force_events(project_dir, monkeypatch):
    # Checkpoint sirasinda birikmis force sinyali YENI adimi oldurmemeli.
    from web_panel import MaestroWebPanel
    import time

    _patch_agents(monkeypatch)
    app = MaestroWebPanel(project_dir)
    app.force_complete_event.set()  # bayat sinyal
    stages = [{"name": "Plan", "agent": "codex", "prompt": "WRITE:plan.md",
               "reads": [], "writes": ["plan.md"], "checkpoint": False, "timeout": 20}]
    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    deadline = time.time() + 10
    while time.time() < deadline and app.running:
        time.sleep(0.05)
    assert (project_dir / "plan.md").exists()  # adim GERCEKTEN calisti
    finished = [e for e in orkestra.load_events(project_dir) if e["event"] == "stage_finished"]
    assert finished and finished[-1].get("forced") is False  # zorla degil, normal bitti
