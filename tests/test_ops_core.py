# -*- coding: utf-8 -*-
"""Operasyon cekirdegi testleri: hata siniflandirma, run kayitlari,
workflow versiyonlama, preflight ve dosyadan-toparlama."""

from __future__ import annotations

import sys

import pytest

import orkestra


# ---------------- classify_failure ----------------

@pytest.mark.parametrize(
    ("reason", "output", "expected"),
    [
        ("not-found", "", "eksik-arac"),
        ("timeout", "", "timeout"),
        ("stuck", "", "ajan-sapmasi"),
        ("stopped", "", "durduruldu"),
        ("exit", "You've hit your usage limit", "limit"),
        ("exit", "Error: not logged in. please run /login", "login"),
        ("test failed", "", "test-hatasi"),
        ("missing outputs: rapor.md", "", "eksik-cikti"),
        ("exit", "UnicodeDecodeError: 'charmap' codec", "path-encoding"),
        ("exit", "opak bir hata", "ajan-sapmasi"),
        ("tuhaf-sebep", "", "bilinmiyor"),
    ],
)
def test_classify_failure_categories(reason, output, expected):
    got = orkestra.classify_failure(reason, output)
    assert got["category"] == expected
    assert got["label"] and got["advice"]  # kullaniciya net metin var


# ---------------- run kayitlari ----------------

def test_run_records_roundtrip(project_dir):
    orkestra.append_run_record(project_dir, {"run_id": "r1", "status": "complete", "stages": 3})
    orkestra.append_run_record(project_dir, {"run_id": "r2", "status": "failed", "error": "timeout"})
    rows = orkestra.load_run_records(project_dir)
    assert [r["run_id"] for r in rows] == ["r1", "r2"]
    assert all("timestamp" in r for r in rows)


def test_produced_files_lists_only_existing(project_dir):
    (project_dir / "plan.md").write_text("p", encoding="utf-8")
    stages = [
        {"writes": ["plan.md"]},
        {"writes": ["tasarim.md"]},  # yok
        {"writes": ["plan.md"]},     # tekrar -> tekilles
    ]
    assert orkestra.produced_files(project_dir, stages) == ["plan.md"]


# ---------------- workflow versiyonlama ----------------

def _wf(prompt: str) -> dict:
    return {
        "stages": [
            {"name": "A", "agent": "codex", "prompt": prompt, "writes": ["a.md"]},
            {"name": "B", "agent": "gemini", "prompt": "p2", "reads": ["a.md"]},
            {"name": "C", "agent": "claude", "prompt": "p3"},
        ]
    }


def test_workflow_versioning_and_restore(project_dir):
    orkestra.save_generated_workflow(project_dir, _wf("ilk surum"))
    assert orkestra.list_workflow_versions(project_dir) == []  # ilk kayitta surum yok

    orkestra.save_generated_workflow(project_dir, _wf("ikinci surum"))
    versions = orkestra.list_workflow_versions(project_dir)
    assert len(versions) == 1  # eski surum saklandi

    diff = orkestra.diff_workflow_versions(project_dir, versions[0]["name"])
    assert "ilk surum" in diff and "ikinci surum" in diff

    restored = orkestra.restore_workflow_version(project_dir, versions[0]["name"])
    assert restored["stages"][0]["prompt"] == "ilk surum"
    current = orkestra.load_generated_workflow(project_dir)
    assert current["stages"][0]["prompt"] == "ilk surum"


def test_workflow_same_content_creates_no_version(project_dir):
    orkestra.save_generated_workflow(project_dir, _wf("ayni"))
    orkestra.save_generated_workflow(project_dir, _wf("ayni"))
    assert orkestra.list_workflow_versions(project_dir) == []


# ---------------- preflight ----------------

def _stages() -> list[dict]:
    return [
        {"name": "A", "agent": "codex", "prompt": "p", "reads": ["girdi.md"], "writes": ["a.md"]},
        {"name": "B", "agent": "claude", "prompt": "p", "reads": ["a.md"], "writes": ["b.md"]},
    ]


def test_preflight_reports_missing_tools_and_inputs(project_dir, monkeypatch):
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: None)
    findings = orkestra.preflight_check(project_dir, _stages())
    levels = {f["level"] for f in findings}
    messages = " | ".join(f["mesaj"] for f in findings)
    assert "hata" in levels and "Eksik ajan" in messages
    assert "girdi.md" in messages  # ilk adimin eksik girdisi uyarisi


def test_preflight_clean_when_ready(project_dir, monkeypatch):
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable)
    (project_dir / "girdi.md").write_text("x", encoding="utf-8")
    findings = orkestra.preflight_check(project_dir, _stages())
    assert findings == []


def test_preflight_warns_about_half_done_run(project_dir, monkeypatch):
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable)
    (project_dir / "girdi.md").write_text("x", encoding="utf-8")
    stages = _stages()
    orkestra.save_state(project_dir, {"completed": [1], "workflow_hash": orkestra.workflow_hash(stages)})
    findings = orkestra.preflight_check(project_dir, stages)
    assert any("yarım iş" in f["mesaj"] for f in findings)


def test_preflight_invalid_workflow_is_fatal(project_dir):
    findings = orkestra.preflight_check(project_dir, [{"name": "X"}])
    assert findings and findings[0]["level"] == "hata"


# ---------------- dosyadan toparlama ----------------

def test_infer_completed_prefix(project_dir):
    stages = [
        {"name": "A", "writes": ["a.md"]},
        {"name": "B", "writes": ["b.md"]},
        {"name": "C", "writes": ["c.md"]},
    ]
    (project_dir / "a.md").write_text("x", encoding="utf-8")
    (project_dir / "b.md").write_text("x", encoding="utf-8")
    assert orkestra.infer_completed_from_outputs(project_dir, stages) == [1, 2]
    # writes'i olmayan adimda guvenli durus
    assert orkestra.infer_completed_from_outputs(project_dir, [{"name": "A"}]) == []


# ---------------- yapisal olay logu ----------------

def test_events_roundtrip(project_dir):
    orkestra.append_event(project_dir, "run_started", run_id="r1", stages=3)
    orkestra.append_event(project_dir, "stage_finished", idx=1, ok=True)
    rows = orkestra.load_events(project_dir)
    assert [r["event"] for r in rows] == ["run_started", "stage_finished"]
    assert all("timestamp" in r for r in rows)
    assert rows[0]["run_id"] == "r1" and rows[1]["ok"] is True


# ---------------- provider/plugin sistemi ----------------

def test_register_provider_and_use_in_workflow(project_dir, tmp_path):
    spec = {"aider": {"command": ["aider", "--message", "{prompt}"], "fallback": "claude"}}
    pfile = tmp_path / "providers.json"
    pfile.write_text(__import__("json").dumps(spec), encoding="utf-8")
    try:
        loaded = orkestra.load_custom_providers(pfile)
        assert loaded == ["aider"]
        assert "aider" in orkestra.AGENT_COMMANDS
        assert orkestra.DEFAULT_FALLBACK_AGENTS["aider"] == "claude"
        # build_command yeni ajanla calisir
        cmd = orkestra.build_command({"name": "X", "agent": "aider", "prompt": "merhaba"})
        assert cmd[0] == "aider" and "merhaba" in " ".join(cmd)
        # workflow dogrulayici yeni ajani tanir
        data = {"stages": [
            {"name": "A", "agent": "aider", "prompt": "p1", "writes": ["a.md"]},
            {"name": "B", "agent": "codex", "prompt": "p2"},
            {"name": "C", "agent": "claude", "prompt": "p3"},
        ]}
        norm = orkestra.validate_generated_workflow(data)
        assert norm["stages"][0]["agent"] == "aider"
    finally:
        orkestra.AGENT_COMMANDS.pop("aider", None)
        orkestra.DEFAULT_FALLBACK_AGENTS.pop("aider", None)


# ---------------- ajan karar kayitlari ----------------

def test_extract_last_handoff_and_decisions(project_dir):
    (project_dir / "sohbet.md").write_text(
        "# Sohbet\n\n"
        "## 2026-07-03T10:00 - CODEX\nilk not\n\n"
        "## 2026-07-03T10:05 - GEMINI\ntasarim bitti\n\n"
        "## 2026-07-03T10:10 - CODEX\nplan.md yazdim; yaklasim: basit MVC\n",
        encoding="utf-8",
    )
    assert "basit MVC" in orkestra.extract_last_handoff(project_dir, "codex")
    assert orkestra.extract_last_handoff(project_dir, "claude") == ""

    stage = {"name": "Plan", "agent": "codex", "reads": ["istek.md"], "writes": ["plan.md"]}
    orkestra.record_stage_decision(project_dir, "r1", 1, stage, ["plan.md"], "plan.md yazdim")
    rows = orkestra.load_decisions(project_dir)
    assert rows[-1]["agent"] == "codex" and rows[-1]["degistirdi"] == ["plan.md"]


# ---------------- ajan hafizasi ----------------

def test_project_memory_roundtrip_and_cap(project_dir):
    assert orkestra.load_project_memory(project_dir) == ""
    orkestra.append_project_memory(project_dir, "Stack: FastAPI + SQLite")
    orkestra.append_project_memory(project_dir, "Yasak: jQuery kullanma")
    text = orkestra.load_project_memory(project_dir)
    assert "FastAPI" in text and "jQuery" in text
    orkestra.append_project_memory(project_dir, "x" * 5000)
    assert len(orkestra.load_project_memory(project_dir, limit_chars=1500)) <= 1500


def test_memory_injected_into_prompt(project_dir):
    orkestra.append_project_memory(project_dir, "Yasak: Bootstrap")
    stage = {"name": "Kodlama", "agent": "claude", "prompt": "kodla", "reads": [], "writes": []}
    prompt = orkestra.build_stage_prompt(stage, idx=1, total=1, stages=[stage], project_dir=project_dir)
    assert "PROJE HAFIZASI" in prompt and "Bootstrap" in prompt


# ---------------- context sikistirici ----------------

def test_build_context_summary(project_dir):
    (project_dir / "README.md").write_text("# Harika Proje\naciklama", encoding="utf-8")
    (project_dir / "src").mkdir()
    (project_dir / "src" / "main.py").write_text("print('merhaba')\n", encoding="utf-8")
    out = orkestra.build_context_summary(project_dir)
    text = out.read_text(encoding="utf-8")
    assert "Dizin agaci" in text and "src/" in text.replace("\\", "/") or "src" in text
    assert "Harika Proje" in text and "merhaba" in text
    # ozet varken prompt sarmalayicisi ipucu verir
    stage = {"name": "Kodlama", "agent": "claude", "prompt": "kodla", "reads": [], "writes": []}
    prompt = orkestra.build_stage_prompt(stage, idx=1, total=1, stages=[stage], project_dir=project_dir)
    assert orkestra.CONTEXT_SUMMARY_FILE in prompt


# ---------------- otomatik ajan secimi ----------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Arayuz tasarimi ve UI duzeni", "gemini"),
        ("Kodu test et ve kontrol raporu yaz", "codex"),
        ("Backend kodunu refactor et", "claude"),
        ("hicbir anahtar yok", "claude"),
    ],
)
def test_suggest_agent(text, expected):
    assert orkestra.suggest_agent(text) == expected


def test_normalize_stage_resolves_auto_agent():
    stage = orkestra._normalize_stage({"name": "UI Tasarim", "agent": "auto", "prompt": "arayuz ciz"}, 1)
    assert stage["agent"] == "gemini"


# ---------------- retry stratejisi ----------------

@pytest.mark.parametrize(
    ("category", "action"),
    [
        ("limit", "fallback"),
        ("ajan-sapmasi", "fallback"),
        ("timeout", "same"),
        ("eksik-cikti", "fix_prompt"),
        ("test-hatasi", "fix_prompt"),
        ("eksik-arac", "ask"),
        ("login", "ask"),
    ],
)
def test_retry_strategy_actions(category, action):
    strat = orkestra.retry_strategy(category)
    assert strat["action"] == action
    if action == "fix_prompt":
        assert strat["prompt_suffix"]


# ---------------- inceleme bulgusu regresyonlari ----------------

def test_classify_reason_beats_output_markers():
    # Test/eksik-cikti sebebi, cikti icindeki 'limit/429' kelimelerine yenilmemeli.
    assert orkestra.classify_failure("test failed", "output: limit reached")["category"] == "test-hatasi"
    assert orkestra.classify_failure("missing outputs: rapor.md", "HTTP 429")["category"] == "eksik-cikti"


def test_infer_completed_is_contiguous_prefix(project_dir):
    stages = [{"writes": ["a.md"]}, {"writes": ["b.md"]}, {"writes": ["c.md"]}]
    (project_dir / "a.md").write_text("x", encoding="utf-8")
    (project_dir / "c.md").write_text("x", encoding="utf-8")  # b yok!
    # [1,3] donerse resume 2. adimi atlar; onek-guvenli [1] olmali.
    assert orkestra.infer_completed_from_outputs(project_dir, stages) == [1]


def test_provider_cannot_override_builtin(tmp_path):
    onceki = list(orkestra.AGENT_COMMANDS["claude"])
    spec = {"claude": {"command": ["kotu", "{prompt}"]}}
    pfile = tmp_path / "providers.json"
    pfile.write_text(__import__("json").dumps(spec), encoding="utf-8")
    loaded = orkestra.load_custom_providers(pfile)
    assert loaded == []
    assert orkestra.AGENT_COMMANDS["claude"] == onceki  # yerlesik degismedi


def test_suggest_agent_tie_uses_priority():
    # 'arayuz' (gemini) + 'test' (codex) esitliginde oncelik codex'te.
    assert orkestra.suggest_agent("arayuz testi") == "codex"


def test_assess_quality_not_fooled_by_test_substring(project_dir):
    got = orkestra.assess_run_quality(project_dir, [], "failed", "latest snapshot missing")
    assert got["category"] == "kontrol-gerekli"  # 'latest' icindeki test yaniltmasin


# ---------------- sonuc kalite etiketi ----------------

def test_assess_run_quality(project_dir):
    stages = [{"writes": ["plan.md"]}, {"writes": ["rapor.md"]}]
    (project_dir / "plan.md").write_text("x", encoding="utf-8")
    # eksik: rapor.md yok
    assert orkestra.assess_run_quality(project_dir, stages, "complete")["category"] == "eksik"
    (project_dir / "rapor.md").write_text("x", encoding="utf-8")
    assert orkestra.assess_run_quality(project_dir, stages, "complete")["category"] == "hazir"
    assert orkestra.assess_run_quality(project_dir, stages, "failed", "test-hatasi: smoke")["category"] == "test-gecmedi"
    assert orkestra.assess_run_quality(project_dir, stages, "stopped")["category"] == "kontrol-gerekli"


# ---------------- baslangic sihirbazi brief'i ----------------

def test_compose_wizard_brief():
    text = orkestra.compose_wizard_brief(
        "Bir e-ticaret sitesi yap",
        proje_tipi="Web uygulaması", platform="Web",
        tasarim="Farketmez", test_beklentisi="Otomatik test istiyorum",
    )
    assert text.startswith("Bir e-ticaret sitesi yap")
    assert "[Sihirbaz Seçimleri]" in text
    assert "- Proje tipi: Web uygulaması" in text
    assert "Farketmez" not in text  # farketmez secimleri yazilmaz
    # hicbir secim yoksa blok da yok
    assert "[Sihirbaz" not in orkestra.compose_wizard_brief("sade istek")


# ---------------- ajan karsilastirma ----------------

def test_run_agent_comparison_with_fake_agents(project_dir, monkeypatch):
    fake = [sys.executable, str(__import__("pathlib").Path(__file__).parent / "fake_agent.py"), "{prompt}"]
    monkeypatch.setattr(orkestra, "AGENT_COMMANDS", {"codex": list(fake), "claude": list(fake)})
    monkeypatch.setattr(orkestra, "find_tool", lambda tool: sys.executable)

    sonuc = orkestra.run_agent_comparison(
        project_dir, "WRITE:cikti.md gorevi yap", agents=["codex", "claude"],
        writes=["cikti.md"], timeout=30, log=lambda *_: None,
    )
    assert {r["agent"] for r in sonuc["results"]} == {"codex", "claude"}
    assert all(r["ok"] for r in sonuc["results"])
    assert (project_dir / "karsilastirma" / "codex" / "cikti.md").exists()
    assert (project_dir / "karsilastirma" / "claude" / "cikti.md").exists()
    rapor = sonuc["report"].read_text(encoding="utf-8")
    assert "codex" in rapor and "claude" in rapor and "basarili" in rapor


def test_provider_rejects_bad_spec(tmp_path):
    bad = {"kirik": {"command": ["prompt-yok"]}, "iyi": {"command": ["x", "{prompt}"]}}
    pfile = tmp_path / "providers.json"
    pfile.write_text(__import__("json").dumps(bad), encoding="utf-8")
    try:
        loaded = orkestra.load_custom_providers(pfile)
        assert loaded == ["iyi"]          # kirik atlandi, uygulama cokmedi
        assert "kirik" not in orkestra.AGENT_COMMANDS
    finally:
        orkestra.AGENT_COMMANDS.pop("iyi", None)
