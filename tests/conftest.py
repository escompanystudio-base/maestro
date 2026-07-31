# -*- coding: utf-8 -*-
"""Ortak test fixture'lari."""

import sys
from pathlib import Path

import pytest

FAKE_AGENT = Path(__file__).resolve().parent / "fake_agent.py"


@pytest.fixture
def project_dir(tmp_path):
    """Her test icin temiz, gecici bir proje klasoru (logs/ dahil)."""
    d = tmp_path / "project"
    d.mkdir()
    (d / "logs").mkdir()
    return d


@pytest.fixture
def fake_agents(monkeypatch):
    """
    codex/gemini/claude komutlarini sahte ajan scriptine yonlendirir.
    Boylece run_stage gercek subprocess akisini (build_command -> Popen ->
    verify_outputs) kullanir; sadece komutun kendisi sahtedir.
    """
    import orkestra

    fake = [sys.executable, str(FAKE_AGENT), "{prompt}"]
    patched = {"codex": list(fake), "gemini": list(fake), "claude": list(fake)}
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", patched)
    # Fallback kapisi find_tool(agent) ile gercek PATH'e bakar; testte araclar
    # kurulu olmayabilir, bu yuzden bilinen ajanlar icin "var" gibi davranalim.
    monkeypatch.setattr(
        orkestra, "find_tool",
        lambda tool: sys.executable if tool in patched else None,
    )
    return patched
