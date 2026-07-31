# -*- coding: utf-8 -*-
"""
Faz 4b - akisin sahte ajanlarla uctan uca testi.

run_stage gercek subprocess akisini kullanir; ajanlar fake_agent.py'ye
yonlendirilir (conftest 'fake_agents' fixture'i). Dosya uzerinden paslasma,
basarisizlik, eksik girdi/cikti, timeout ve fallback senaryolari sinanir.
"""

import os

import pytest

import orkestra


def _run(project_dir, stage, idx=1, total=1, stages=None):
    log_path = project_dir / "logs" / "test_run.log"
    return orkestra.run_stage(
        project_dir, stage, idx, total, False, log_path, stages=stages or [stage]
    )


def test_agent_creates_expected_output(project_dir, fake_agents):
    stage = {"name": "Planlama", "agent": "codex",
             "prompt": "Plani yaz. WRITE:plan.md", "reads": [], "writes": ["plan.md"]}
    assert _run(project_dir, stage) is True
    assert (project_dir / "plan.md").exists()


def test_file_handoff_between_agents(project_dir, fake_agents):
    # Dosya uzerinden paslasma: codex plan.md uretir, gemini onu okuyup tasarim.md uretir.
    s1 = {"name": "Plan", "agent": "codex", "prompt": "WRITE:plan.md", "reads": [], "writes": ["plan.md"]}
    s2 = {"name": "Tasarim", "agent": "gemini", "prompt": "WRITE:tasarim.md",
          "reads": ["plan.md"], "writes": ["tasarim.md"]}
    stages = [s1, s2]
    assert _run(project_dir, s1, 1, 2, stages) is True
    assert _run(project_dir, s2, 2, 2, stages) is True
    assert (project_dir / "tasarim.md").exists()


def test_missing_input_stops_stage(project_dir, fake_agents):
    stage = {"name": "Kodlama", "agent": "claude", "prompt": "WRITE:rapor.md",
             "reads": ["yok.md"], "writes": ["rapor.md"]}
    assert _run(project_dir, stage) is False
    assert not (project_dir / "rapor.md").exists()


def test_agent_failure_returns_false(project_dir, fake_agents):
    stage = {"name": "Kodlama", "agent": "claude", "prompt": "FAILNOW kodla",
             "reads": [], "writes": ["rapor.md"]}
    assert _run(project_dir, stage) is False


def test_missing_output_detected(project_dir, fake_agents):
    # Ajan basariyla biter ama beklenen dosyayi yazmaz -> verify_outputs yakalamali.
    stage = {"name": "Kodlama", "agent": "claude", "prompt": "hicbir sey uretme",
             "reads": [], "writes": ["rapor.md"]}
    assert _run(project_dir, stage) is False


def test_timeout_kills_hanging_agent(project_dir, fake_agents):
    stage = {"name": "Takilan", "agent": "codex", "prompt": "HANG",
             "reads": [], "writes": [], "timeout": 1}
    assert _run(project_dir, stage) is False


def test_utf8_agent_output_does_not_crash(project_dir, fake_agents):
    stage = {"name": "Plan", "agent": "codex", "prompt": "WRITE:plan.md",
             "reads": [], "writes": ["plan.md"]}
    assert _run(project_dir, stage) is True
    log_text = (project_dir / "logs" / "test_run.log").read_text(encoding="utf-8", errors="replace")
    assert "Sahte ajan calisti" in log_text


def test_unknown_executable_returns_false(project_dir, monkeypatch):
    # Arac kurulu degilse: komut PATH'te yok -> FileNotFoundError -> run_stage False donmeli (cokmemeli).
    monkeypatch.setattr(
        orkestra, "AGENT_COMMANDS",
        {"codex": ["kesinlikle_olmayan_arac_xyz", "{prompt}"]},
    )
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: None)
    stage = {"name": "X", "agent": "codex", "prompt": "WRITE:plan.md", "reads": [], "writes": ["plan.md"]}
    log_path = project_dir / "logs" / "t.log"
    assert orkestra.run_stage(project_dir, stage, 1, 1, False, log_path) is False


def test_fallback_agent_takes_over(project_dir, fake_agents):
    # claude 'usage limit' verir -> ayni gorev codex'e devredilir, codex dosyayi yazar.
    stage = {"name": "Kodlama", "agent": "claude",
             "prompt": "LIMITFAIL ama gorevi tamamla WRITE:rapor.md",
             "reads": [], "writes": ["rapor.md"], "fallback_agent": "codex"}
    assert _run(project_dir, stage) is True
    assert (project_dir / "rapor.md").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows PATH shim davranisi")
def test_resolve_tool_skips_broken_windows_npm_shim(tmp_path, monkeypatch):
    broken = tmp_path / "fnm_multishells" / "broken"
    good = tmp_path / "npm"
    broken.mkdir(parents=True)
    good.mkdir()

    wrapper = (
        '@ECHO off\n'
        'GOTO start\n'
        ':find_dp0\n'
        'SET dp0=%~dp0\n'
        'EXIT /b\n'
        ':start\n'
        'SETLOCAL\n'
        'CALL :find_dp0\n'
        '"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\n'
    )
    (broken / "claude.cmd").write_text(wrapper, encoding="utf-8")
    (good / "claude.cmd").write_text(wrapper, encoding="utf-8")
    target = good / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")

    monkeypatch.setenv("PATH", os.pathsep.join([str(broken), str(good)]))
    monkeypatch.setattr(orkestra, "_FNM_ENV_LOADED", True)

    assert orkestra.find_tool("claude") == str(good / "claude.cmd")
    assert orkestra.resolve_command(["claude", "--version"])[0] == str(good / "claude.cmd")
