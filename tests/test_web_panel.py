# -*- coding: utf-8 -*-
"""Web panel service tests."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

import orkestra
import web_panel
from web_panel import MaestroWebPanel, create_server, shutdown_server

FAKE_AGENT = Path(__file__).resolve().parent / "fake_agent.py"


def _wait_until_done(app: MaestroWebPanel, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not app.running:
            return
        time.sleep(0.05)
    raise AssertionError("web panel run did not finish")


@pytest.fixture
def web_fake_agents(monkeypatch):
    fake = [sys.executable, str(FAKE_AGENT), "{prompt}"]
    patched = {"codex": list(fake), "gemini": list(fake), "claude": list(fake)}
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", patched)
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable if tool in patched else None)
    return patched


def test_web_panel_rejects_project_escape(project_dir):
    app = MaestroWebPanel(project_dir)
    with pytest.raises(ValueError):
        app.safe_file_path("../secret.txt")


def test_shutdown_server_stops_running_app(project_dir, monkeypatch):
    server = create_server("127.0.0.1", 0, project_dir)
    calls: list[str] = []

    class FakeWorker:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            calls.append(f"join:{timeout}")

    monkeypatch.setattr(server.app, "stop_run", lambda: calls.append("stop"))
    server.app.worker = FakeWorker()  # type: ignore[assignment]

    shutdown_server(server)

    assert calls == ["stop", "join:5"]


def test_web_panel_saves_request(project_dir):
    app = MaestroWebPanel(project_dir)
    app.save_request("Panelden gelen istek")
    assert (project_dir / "istek.md").read_text(encoding="utf-8").strip() == "Panelden gelen istek"
    assert "Panelden gelen istek" in (project_dir / "sohbet.md").read_text(encoding="utf-8")


def test_web_panel_scans_external_source(project_dir, tmp_path):
    source = tmp_path / "old_app"
    source.mkdir()
    (source / "README.md").write_text("# Old App\n\nExisting notes.\n", encoding="utf-8")
    (source / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")

    app = MaestroWebPanel(project_dir)
    meta = app.scan_source_path(str(source))

    context = (project_dir / "kaynak_context.md").read_text(encoding="utf-8")
    assert meta["enabled"] is True
    assert meta["included_files"] == 2
    assert "README.md" in context
    assert "app.py" in context
    assert "node_modules/ignored.js" not in context


def test_web_panel_scans_uploaded_source(project_dir):
    app = MaestroWebPanel(project_dir)
    meta = app.scan_uploaded_source(
        [
            {"name": "README.md", "content": "# Uploaded\n", "size": 11, "modified": "2026-01-01T00:00:00"},
            {"name": "src/app.py", "content": "print('uploaded')\n", "size": 18},
            {"name": "image.png", "content": "not source", "size": 10},
        ],
        "Secilen dosyalar",
    )

    context = (project_dir / "kaynak_context.md").read_text(encoding="utf-8")
    assert meta["enabled"] is True
    assert meta["included_files"] == 2
    assert "README.md" in context
    assert "src/app.py" in context
    assert "image.png" not in context
    assert meta["import_path"].startswith("source_import/")
    assert (project_dir / meta["import_path"] / "src" / "app.py").exists()


def test_web_panel_applies_workflow_template(project_dir):
    app = MaestroWebPanel(project_dir)
    result = app.apply_workflow_template("test-fix")

    assert result["currentType"] == "test-fix"
    assert (project_dir / "workflow_generated.json").exists()
    assert app.active_workflow_data()["project_type"] == "test-fix"


def test_web_panel_diagnostics_report_missing_mp3_files(project_dir):
    app_root = project_dir / "MP3INDIRICI"
    app_root.mkdir()
    (app_root / "app").mkdir()

    app = MaestroWebPanel(project_dir)
    payload = app.diagnostics_payload()

    titles = {issue["title"] for issue in payload["issues"]}
    assert "MP3 uygulamasi iskelet halinde" in titles


def test_web_panel_runs_project_tests(project_dir):
    app_root = project_dir / "MP3INDIRICI"
    app_root.mkdir()
    (app_root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (app_root / "README.md").write_text("# App\n", encoding="utf-8")
    (app_root / "requirements.txt").write_text("", encoding="utf-8")
    (app_root / "run.bat").write_text("@echo off\n", encoding="utf-8")

    app = MaestroWebPanel(project_dir)
    result = app.run_project_tests("MP3INDIRICI")

    assert result["status"] == "success"
    assert (project_dir / "test_raporu.json").exists()


def test_web_panel_adds_source_context_to_run(project_dir, tmp_path, web_fake_agents):
    source = tmp_path / "old_file.py"
    source.write_text("print('source')\n", encoding="utf-8")
    app = MaestroWebPanel(project_dir)
    app.scan_source_path(str(source))
    stages = [
        {
            "name": "Plan",
            "agent": "codex",
            "prompt": "WRITE:plan.md",
            "reads": [],
            "writes": ["plan.md"],
            "checkpoint": False,
            "timeout": 5,
        }
    ]

    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    _wait_until_done(app)

    payload = app.status_payload()
    assert app.status == "complete"
    assert payload["workflow"]["stages"][0]["reads"][0] == "kaynak_context.md"
    assert (project_dir / "plan.md").exists()


def test_web_panel_runs_stage_with_fake_agent(project_dir, web_fake_agents):
    app = MaestroWebPanel(project_dir)
    stages = [
        {
            "name": "Plan",
            "agent": "codex",
            "prompt": "WRITE:plan.md",
            "reads": [],
            "writes": ["plan.md"],
            "checkpoint": False,
            "timeout": 5,
        }
    ]

    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    _wait_until_done(app)

    assert app.status == "complete"
    assert (project_dir / "plan.md").exists()
    payload = app.status_payload()
    assert payload["state"]["completed"] == [1]
    assert payload["workflow"]["stages"][0]["status"] == "done"


def test_web_panel_completes_antigravity_gemini_when_outputs_exist(project_dir, web_fake_agents, monkeypatch):
    monkeypatch.setattr(orkestra, "is_antigravity_gemini_stage", lambda stage: stage.get("agent") == "gemini")
    monkeypatch.setattr(web_panel, "ANTIGRAVITY_OUTPUT_EXIT_GRACE_SECONDS", 0.2)
    app = MaestroWebPanel(project_dir)
    stages = [
        {
            "name": "Tasarim",
            "agent": "gemini",
            "prompt": "WRITE:tasarim.md HANG",
            "reads": [],
            "writes": ["tasarim.md"],
            "checkpoint": False,
            "timeout": 20,
        }
    ]

    app.start_run(start_idx=1, reset_state=True, use_checkpoints=False, stages=stages)
    _wait_until_done(app)

    payload = app.status_payload()
    assert app.status == "complete"
    assert payload["state"]["completed"] == [1]
    assert (project_dir / "tasarim.md").exists()
    # Mesaj artik ajan-bazli ("GEMINI cikti urettikten sonra kapanmadi; ...");
    # ajan adina bagimli olmadan zorunlu-tamamlama mesajini dogrula.
    assert "cikti urettikten sonra kapanmadi" in "\n".join(app.log_lines)


def test_web_panel_checkpoint_decision(project_dir, web_fake_agents):
    app = MaestroWebPanel(project_dir)
    stages = [
        {
            "name": "Plan",
            "agent": "codex",
            "prompt": "WRITE:plan.md",
            "reads": [],
            "writes": ["plan.md"],
            "checkpoint": True,
            "timeout": 5,
        },
        {
            "name": "Rapor",
            "agent": "claude",
            "prompt": "WRITE:rapor.md",
            "reads": ["plan.md"],
            "writes": ["rapor.md"],
            "checkpoint": False,
            "timeout": 5,
        },
    ]

    app.start_run(start_idx=1, reset_state=True, use_checkpoints=True, stages=stages)
    deadline = time.time() + 8
    while time.time() < deadline and not app.waiting_checkpoint:
        time.sleep(0.05)
    assert app.waiting_checkpoint is True

    app.send_decision("continue")
    _wait_until_done(app)

    assert app.status == "complete"
    assert (project_dir / "rapor.md").exists()
