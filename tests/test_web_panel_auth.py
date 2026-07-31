# -*- coding: utf-8 -*-
"""Web panel guvenlik (token), kapanis ve smoke->kalite-skoru baglanti testleri."""

from __future__ import annotations

import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import orkestra
from web_panel import MaestroWebPanel, create_server, shutdown_server

FAKE_AGENT = Path(__file__).resolve().parent / "fake_agent.py"


def _get_status(url: str, headers: dict | None = None) -> int:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _serve(server) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_auth_token_required_and_accepted(project_dir):
    server = create_server("127.0.0.1", 0, project_dir, auth_token="gizli-token")
    _serve(server)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert _get_status(f"{base}/api/status") == 401
        assert _get_status(f"{base}/api/status", {"Authorization": "Bearer gizli-token"}) == 200
        assert _get_status(f"{base}/api/status?token=gizli-token") == 200
        assert _get_status(f"{base}/api/status", {"Cookie": "maestro_token=gizli-token"}) == 200
        assert _get_status(f"{base}/api/status?token=yanlis") == 401
    finally:
        server.shutdown()
        shutdown_server(server)


def test_auth_disabled_when_no_token(project_dir):
    # Varsayilan yerel kullanim: token yoksa auth devrede degil.
    server = create_server("127.0.0.1", 0, project_dir)
    _serve(server)
    try:
        assert _get_status(f"http://127.0.0.1:{server.server_port}/api/status") == 200
    finally:
        server.shutdown()
        shutdown_server(server)


def test_auth_required_on_post_too(project_dir):
    server = create_server("127.0.0.1", 0, project_dir, auth_token="gizli-token")
    _serve(server)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        req = urllib.request.Request(f"{base}/api/request", data=b'{"text":"x"}', method="POST")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        assert code == 401
    finally:
        server.shutdown()
        shutdown_server(server)


def test_static_traversal_blocked(project_dir):
    server = create_server("127.0.0.1", 0, project_dir)
    _serve(server)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert _get_status(f"{base}/static/../web_panel.py") != 200
        assert _get_status(f"{base}/static/..%2fweb_panel.py") != 200
    finally:
        server.shutdown()
        shutdown_server(server)


def test_token_redacted_in_access_log(project_dir, monkeypatch):
    import io
    import sys as _sys

    server = create_server("127.0.0.1", 0, project_dir, auth_token="cok-gizli-token")
    _serve(server)
    captured = io.StringIO()
    monkeypatch.setattr(_sys, "stderr", captured)
    try:
        assert _get_status(f"http://127.0.0.1:{server.server_port}/api/status?token=cok-gizli-token") == 200
    finally:
        monkeypatch.undo()
        server.shutdown()
        shutdown_server(server)
    log_out = captured.getvalue()
    assert "cok-gizli-token" not in log_out  # token log'a sizmadi
    assert "token=***" in log_out


def test_history_api_endpoints(project_dir):
    # Gozlemlenebilirlik uclari: runs / decisions / events JSON dondurur.
    orkestra.append_run_record(project_dir, {"run_id": "r1", "status": "complete"})
    orkestra.record_stage_decision(project_dir, "r1", 1, {"name": "Plan", "agent": "codex"}, ["plan.md"], "ozet")
    orkestra.append_event(project_dir, "run_started", run_id="r1")
    server = create_server("127.0.0.1", 0, project_dir)
    _serve(server)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        import json as _json
        for endpoint, key in (("/api/runs", "runs"), ("/api/decisions", "decisions"), ("/api/events", "events")):
            with urllib.request.urlopen(f"{base}{endpoint}", timeout=3) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            assert data["ok"] and len(data[key]) >= 1, endpoint
    finally:
        server.shutdown()
        shutdown_server(server)


def test_shutdown_server_before_any_run(project_dir):
    # Hic akis baslatilmadan kapanis AttributeError vermemeli (worker yokken).
    server = create_server("127.0.0.1", 0, project_dir)
    shutdown_server(server)


def test_smoke_test_result_feeds_quality_score(project_dir, monkeypatch):
    # test_command kosulunca sonuc last_test_result'a yazilmali (kalite skoru bunu okur).
    fake = [sys.executable, str(FAKE_AGENT), "{prompt}"]
    patched = {"codex": list(fake), "gemini": list(fake), "claude": list(fake)}
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", patched)
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable if tool in patched else None)

    app = MaestroWebPanel(project_dir)
    stages = [
        {
            "name": "Kodlama",
            "agent": "claude",
            "prompt": "WRITE:rapor.md",
            "reads": [],
            "writes": ["rapor.md"],
            "checkpoint": False,
            "timeout": 20,
            "test_command": "python -c pass",
        }
    ]
    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    deadline = time.time() + 10
    while time.time() < deadline and app.running:
        time.sleep(0.05)
    assert not app.running
    assert app.last_test_result is not None
    assert app.last_test_result["status"] == "success"


def test_default_smoke_runs_for_coding_stage(project_dir, monkeypatch):
    # test_command YOKKEN kodlama adimindan sonra varsayilan compileall smoke kosmali.
    fake = [sys.executable, str(FAKE_AGENT), "{prompt}"]
    patched = {"codex": list(fake), "gemini": list(fake), "claude": list(fake)}
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", patched)
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable if tool in patched else None)

    app = MaestroWebPanel(project_dir)
    # Gecerli bir .py onceden koy: varsayilan smoke (compileall) bunu derler.
    # (Ajanin kendisine .py yazdirmiyoruz; fake agent gecersiz icerik yazar ve
    # smoke onu hakli olarak yakalar - o davranis ayri konu.)
    (project_dir / "main.py").write_text("x = 1\n", encoding="utf-8")
    stages = [
        {
            "name": "Kodlama",
            "agent": "claude",
            "prompt": "WRITE:rapor.md",
            "reads": [],
            "writes": ["rapor.md"],
            "checkpoint": False,
            "timeout": 20,
        }
    ]
    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    deadline = time.time() + 15
    while time.time() < deadline and app.running:
        time.sleep(0.05)
    assert not app.running
    assert app.last_test_result is not None, "varsayilan smoke kosulmali (kodlama adimi + .py mevcut)"
    assert app.last_test_result["status"] == "success"


def test_default_smoke_skipped_for_non_coding_stage(project_dir):
    app = MaestroWebPanel(project_dir)
    assert app._default_test_command({"name": "Planlama", "prompt": "plan cikar"}) is None


def test_run_emits_structured_events(project_dir, monkeypatch):
    # Sahte kosu sonrasi events.jsonl: run_started -> stage_started -> stage_finished -> run_finished.
    fake = [sys.executable, str(FAKE_AGENT), "{prompt}"]
    patched = {"codex": list(fake), "gemini": list(fake), "claude": list(fake)}
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", patched)
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable if tool in patched else None)

    app = MaestroWebPanel(project_dir)
    stages = [{"name": "Plan", "agent": "codex", "prompt": "WRITE:plan.md",
               "reads": [], "writes": ["plan.md"], "checkpoint": False, "timeout": 20}]
    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    deadline = time.time() + 10
    while time.time() < deadline and app.running:
        time.sleep(0.05)
    events = [e["event"] for e in orkestra.load_events(project_dir)]
    assert "run_started" in events
    assert "stage_started" in events and "stage_finished" in events
    assert "run_finished" in events
    finished = [e for e in orkestra.load_events(project_dir) if e["event"] == "stage_finished"]
    assert finished[-1]["ok"] is True
