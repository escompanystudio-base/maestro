# -*- coding: utf-8 -*-
"""Faz 4a - state yonetimi, snapshot ve workflow dogrulama birim testleri."""

import pytest

import orkestra


# ---------------- Durum (state) ----------------

def test_state_roundtrip(project_dir):
    orkestra.save_state(project_dir, {"completed": [1, 2], "last_run": None})
    state = orkestra.load_state(project_dir)
    assert state["completed"] == [1, 2]
    assert state["last_run"] is not None  # save_state zaman damgasi koyar


def test_state_corrupt_file_does_not_crash(project_dir):
    (project_dir / orkestra.STATE_FILE).write_text("{bozuk json", encoding="utf-8")
    state = orkestra.load_state(project_dir)  # cokmemeli, varsayilana donmeli
    assert state == {"completed": [], "last_run": None}


def test_state_missing_file_returns_default(project_dir):
    assert orkestra.load_state(project_dir) == {"completed": [], "last_run": None}


# ---------------- Snapshot ----------------

def test_snapshot_create_list_and_restore(project_dir):
    target = project_dir / "plan.md"
    target.write_text("ilk surum", encoding="utf-8")

    stage = {"name": "Planlama", "agent": "codex", "prompt": "x"}
    meta = orkestra.create_snapshot(project_dir, "run_test", 1, stage)
    assert meta["step"] == 1
    assert "/" in meta["id"]

    rows = orkestra.list_snapshots(project_dir)
    assert any(r["id"] == meta["id"] for r in rows)

    # Dosyayi degistir, sonra snapshot'a geri don
    target.write_text("degismis surum", encoding="utf-8")
    orkestra.restore_snapshot(project_dir, meta["id"])
    assert target.read_text(encoding="utf-8") == "ilk surum"


def test_snapshot_diff_shows_change(project_dir):
    target = project_dir / "rapor.md"
    target.write_text("satir1\n", encoding="utf-8")
    meta = orkestra.create_snapshot(project_dir, "run_diff", 1, {"name": "Rapor", "agent": "claude"})
    target.write_text("satir1\nsatir2\n", encoding="utf-8")

    diff = orkestra.snapshot_diff(project_dir, meta["id"], "rapor.md")
    assert "satir2" in diff


def test_snapshot_invalid_id_raises(project_dir):
    with pytest.raises(orkestra.WorkflowError):
        orkestra.snapshot_files_dir(project_dir, "../gizli")


# ---------------- Workflow dogrulama + fallback sabiti (Faz 1b) ----------------

def test_normalize_stage_uses_default_fallback_map():
    # Faz 1b: fallback artik DEFAULT_FALLBACK_AGENTS'ten okunuyor
    gemini = orkestra._normalize_stage({"name": "T", "agent": "gemini", "prompt": "p"}, 1)
    assert gemini["fallback_agent"] == "claude"

    claude = orkestra._normalize_stage({"name": "T", "agent": "claude", "prompt": "p"}, 1)
    assert claude["fallback_agent"] == "codex"

    # codex'in varsayilan fallback'i yok -> alan eklenmemeli
    codex = orkestra._normalize_stage({"name": "T", "agent": "codex", "prompt": "p"}, 1)
    assert "fallback_agent" not in codex


def test_normalize_stage_explicit_fallback_overrides():
    stage = orkestra._normalize_stage(
        {"name": "T", "agent": "gemini", "prompt": "p", "fallback_agent": "codex"}, 1
    )
    assert stage["fallback_agent"] == "codex"


def test_validate_generated_workflow_accepts_valid():
    data = {
        "stages": [
            {"name": "A", "agent": "codex", "prompt": "p1", "writes": ["a.md"]},
            {"name": "B", "agent": "gemini", "prompt": "p2", "reads": ["a.md"], "writes": ["b.md"]},
            {"name": "C", "agent": "claude", "prompt": "p3", "reads": ["b.md"]},
        ]
    }
    norm = orkestra.validate_generated_workflow(data)
    assert len(norm["stages"]) == 3


def test_validate_generated_workflow_rejects_unknown_agent():
    data = {"stages": [{"name": f"S{i}", "agent": "gpt5", "prompt": "p"} for i in range(3)]}
    with pytest.raises(orkestra.WorkflowError):
        orkestra.validate_generated_workflow(data)


# ---------------- Pydantic state modeli (Faz 3a) ----------------

def test_state_model_coerces_bad_data():
    from models import OrkestraState

    m = OrkestraState.from_raw(
        {"completed": ["1", 2, 2, -3, "x"], "last_run": 123, "workflow_hash": "abc"}
    )
    assert m.completed == [1, 2]      # "1"->1, 2 tekil, -3 ve "x" elenir
    assert m.last_run is None          # 123 metin degil -> None
    assert m.workflow_hash == "abc"


def test_state_model_from_non_dict_returns_defaults():
    from models import OrkestraState

    assert OrkestraState.from_raw("bozuk").to_dict() == {
        "completed": [],
        "last_run": None,
        "workflow_hash": None,
    }


# ---------------- Kullanim limiti tespiti (token israfi tanisi) ----------------

def test_usage_limit_detection():
    # Loglardan gercek codex hatasi
    assert orkestra.is_usage_limit_error("ERROR: You've hit your usage limit. Upgrade to Pro")
    assert orkestra.is_usage_limit_error("RESOURCE_EXHAUSTED: quota")
    assert orkestra.is_usage_limit_error("429 Too Many Requests")
    assert not orkestra.is_usage_limit_error("plan.md basariyla yazildi")
    assert not orkestra.is_usage_limit_error("")


def test_usage_limit_notice_message():
    msg = orkestra.usage_limit_notice("codex", "You've hit your usage limit. try again at 11:29 PM.")
    assert msg is not None
    assert "Codex" in msg
    assert "11:29 PM" in msg.replace("  ", " ")
    # Limit yoksa mesaj da yok
    assert orkestra.usage_limit_notice("codex", "her sey yolunda") is None


def test_codex_limit_triggers_fallback_only_when_configured():
    # codex limit + stage'de fallback_agent tanimliysa fallback doner
    stage = {"agent": "codex", "fallback_agent": "claude", "prompt": "p"}
    assert orkestra.fallback_agent_for(stage, "You've hit your usage limit") == "claude"
    # fallback_agent yoksa codex'in varsayilan fallback'i olmadigi icin None (otomatik baska kota yakmaz)
    stage2 = {"agent": "codex", "prompt": "p"}
    assert orkestra.fallback_agent_for(stage2, "You've hit your usage limit") is None
