#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Orkestra - Codex + Gemini + Claude Code'u tek yerden, sırayla çalıştırır.
Ajanlar aynı proje klasöründeki DOSYALAR üzerinden paslaşır.

Kullanım:
    python orkestra.py                # akışı baştan çalıştır
    python orkestra.py --resume       # kaldığı yerden devam et
    python orkestra.py --from 3       # 3. adımdan başlat
    python orkestra.py --yes          # checkpoint'lerde sormadan geç
    python orkestra.py --dry-run      # komutları göster, çalıştırma
"""

from __future__ import annotations

import argparse
import ctypes
import difflib
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import workflow as WF
from logging_config import get_logger, setup_logging
from models import OrkestraState

# Tani amacli (traceback dahil) dosya logu. Kullaniciya gosterilen ciktidan ayri.
logger = get_logger("orkestra")


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = ".orkestra_state.json"
LOG_DIR = "logs"
CHAT_FILE = "sohbet.md"
REQUEST_FILE = "istek.md"
BRIEF_QUESTIONS_FILE = "brief_questions.json"
GENERATED_WORKFLOW_FILE = "workflow_generated.json"
ORKESTRA_DIR = ".orkestra"
WORKFLOWS_DIR = "workflows"
SNAPSHOTS_DIR = "snapshots"
METRICS_FILE = "metrics.jsonl"
RUNS_FILE = "runs.jsonl"
EVENTS_FILE = "events.jsonl"
DECISIONS_FILE = "decisions.jsonl"
HAFIZA_FILE = "hafiza.md"
CONTEXT_SUMMARY_FILE = "proje_ozeti.md"
WORKFLOW_VERSIONS_DIR = "workflow_versions"
PROMPTS_FILE = "prompts.json"
TERMINAL_HISTORY_FILE = "terminal_history.jsonl"
PREVIEW_FRAME_FILE = "preview_frame.html"
QUALITY_REPORT_FILE = "quality_report.json"
PACKAGES_DIR = "packages"
PACKAGE_SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "node_modules",
    ".venv", "venv", LOG_DIR, ORKESTRA_DIR, SNAPSHOTS_DIR,
    "dist", "build", ".next", PACKAGES_DIR,
}
ANTIGRAVITY_CLI_DIR = Path.home() / ".gemini" / "antigravity-cli"
SNAPSHOT_SKIP_DIRS = {ORKESTRA_DIR, LOG_DIR, "node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}
SNAPSHOT_SKIP_FILES = {STATE_FILE}
_FNM_ENV_LOADED = False
DEFAULT_GEMINI_BACKEND = "antigravity"

AGENT_ROLES = {
    "planner": {
        "label": "Planlayici",
        "agent": "codex",
        "prompt_prefix": "Sen bir planlama uzmanisin. Projenin gereksinimlerini analiz et, riskleri belirle ve uygulanabilir bir plan olustur.",
    },
    "designer": {
        "label": "UI/UX Denetci",
        "agent": "claude",
        "prompt_prefix": "Sen bir UI/UX tasarim uzmanisin. Kullanici deneyimini oncelikli tutarak tasarim ve akis kararlari al.",
    },
    "coder": {
        "label": "Kod Yazici",
        "agent": "gemini",
        "prompt_prefix": "Sen bir yazilim gelistiricisin. Temiz, test edilebilir ve iyi yapilandirilmis kod yaz.",
    },
    "tester": {
        "label": "Testci",
        "agent": "codex",
        "prompt_prefix": "Sen bir test uzmanisin. Tum bilesenler icin kapsamli testler yaz ve edge case'leri kontrol et.",
    },
    "refactorer": {
        "label": "Refactor Uzmani",
        "agent": "claude",
        "prompt_prefix": "Sen bir refactoring uzmanisin. Kodu temizle, tekrarlari kaldir ve mimariyi iyilestir.",
    },
    "packager": {
        "label": "Paketleme Uzmani",
        "agent": "codex",
        "prompt_prefix": "Sen bir devops/paketleme uzmanisin. Projeyi dagitima ve kuruluma hazirla.",
    },
    "security": {
        "label": "Guvenlik/Kontrol",
        "agent": "claude",
        "prompt_prefix": "Sen bir guvenlik denetcisisin. Guvenlik aciklari, hata yonetimi ve en iyi pratikleri kontrol et.",
    },
}

AGENT_STUCK_POLICIES = {
    "codex": { "silent_warn": 300, "silent_stuck": 600, "output_grace": 30 },
    "claude": { "silent_warn": 300, "silent_stuck": 600, "output_grace": 30 },
    "gemini": { "silent_warn": 180, "silent_stuck": 420, "output_grace": 5 },
    "default": { "silent_warn": 300, "silent_stuck": 600, "output_grace": 30 }
}

DEFAULT_BRIEF_QUESTIONS = [
    {
        "id": "uygulama_turu",
        "question": "Ne tur bir uygulama istiyorsun?",
        "hint": "Web, masaustu, mobil, oyun, admin panel, SaaS vb.",
        "required": True,
    },
    {
        "id": "hedef_kullanici",
        "question": "Bu uygulamayi kim kullanacak?",
        "hint": "Musteriler, ekip ici kullanicilar, oyuncular, yoneticiler vb.",
        "required": True,
    },
    {
        "id": "platform",
        "question": "Hangi platformda calismali?",
        "hint": "Tarayici, Windows masaustu, mobil, local HTML, Node/Python vb.",
        "required": True,
    },
    {
        "id": "tasarim_tarzi",
        "question": "Tasarim tarzi nasil olsun?",
        "hint": "Modern, sade, dashboard, oyunumsu, koyu tema, kurumsal vb.",
        "required": True,
    },
    {
        "id": "veri_saklama",
        "question": "Veriler nerede saklansin?",
        "hint": "Local dosya, SQLite, tarayici localStorage, veritabani, fark etmez vb.",
        "required": True,
    },
]


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"


class WorkflowError(ValueError):
    """workflow.py içeriği çalıştırılamayacak kadar eksik veya hatalı."""


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Akis UTF-8'e ayarlanamadi (%s): %s", stream, exc)


def enable_ansi() -> None:
    """Windows klasik konsolda ANSI renklerini ve UTF-8 çıktıyı güvenli hale getirir."""
    configure_stdio()
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception as exc:
        logger.debug("Windows ANSI konsol modu acilamadi: %s", exc)


def log(msg: str, color: str = "") -> None:
    configure_stdio()
    text = f"{color}{msg}{C.RESET}"
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe, flush=True)


def banner(text: str) -> None:
    line = "=" * 60
    log(f"\n{line}\n  {text}\n{line}", C.BOLD + C.CYAN)


# Komut şablonları: her ajan için resmi headless komut.
# {prompt} otomatik doldurulur.
AGENT_COMMANDS = {
    "codex": [
        "codex",
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "{prompt}",
    ],
    "gemini": [
        "gemini",
        "-y",
        "-p",
        "{prompt}",
        "--output-format",
        "text",
    ],
    "claude": [
        "claude",
        "-p",
        "{prompt}",
        "--permission-mode",
        "acceptEdits",
    ],
}

GEMINI_BACKEND_ALIASES = {
    "antigravity": "antigravity",
    "agy": "antigravity",
    "antigravity-cli": "antigravity",
    "gemini": "gemini-cli",
    "gemini-cli": "gemini-cli",
    "cli": "gemini-cli",
    "api": "gemini-cli",
}

DEFAULT_FALLBACK_AGENTS = {
    "gemini": "claude",
    "claude": "codex",
}

# ---------------- Provider/plugin sistemi ----------------
# Maestro klasorundeki providers.json ile yeni ajan CLI'lari eklenebilir
# (orn. aider, cursor, yerel LLM). Format:
#   {"aider": {"command": ["aider", "--message", "{prompt}"], "fallback": "claude"}}
PROVIDERS_FILE = "providers.json"


def register_provider(name: str, command: list[str], fallback: str | None = None) -> None:
    """Yeni bir ajan saglayicisi kaydeder; workflow'larda 'agent' olarak kullanilabilir."""
    if not isinstance(name, str) or not name.strip():
        raise WorkflowError("Provider adi bos olamaz.")
    name = name.strip().lower()
    if name in ("codex", "gemini", "claude"):
        # Yerlesik ajan komutlari providers.json ile sessizce ezilemez (guvenlik).
        raise WorkflowError(f"Provider '{name}' yerlesik ajani ezemez; farkli bir ad kullan.")
    if not isinstance(command, list) or not all(isinstance(p, str) for p in command) or not command:
        raise WorkflowError(f"Provider '{name}' icin command metin listesi olmali.")
    if not any("{prompt}" in part for part in command):
        raise WorkflowError(f"Provider '{name}' komutunda '{{prompt}}' yer tutucusu olmali.")
    AGENT_COMMANDS[name] = list(command)
    if fallback:
        DEFAULT_FALLBACK_AGENTS[name] = str(fallback).strip().lower()


def load_custom_providers(path: str | os.PathLike[str] | None = None) -> list[str]:
    """providers.json'dan ozel saglayicilari yukler; hatali girdiler atlanir."""
    p = Path(path) if path is not None else BASE_DIR / PROVIDERS_FILE
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("providers.json okunamadi, atlandi: %s", exc)
        return []
    loaded: list[str] = []
    if isinstance(raw, dict):
        for name, spec in raw.items():
            try:
                if isinstance(spec, dict):
                    register_provider(name, spec.get("command"), spec.get("fallback"))
                    loaded.append(name.strip().lower())
            except WorkflowError as exc:
                logger.warning("Provider '%s' yuklenemedi: %s", name, exc)
    return loaded


# Ozel saglayicilar import sirasinda otomatik yuklenir (gui/web/menu hepsi gorur).
CUSTOM_PROVIDERS = load_custom_providers()

GEMINI_UNSUPPORTED_MARKERS = (
    "IneligibleTierError",
    "UNSUPPORTED_CLIENT",
    "This client is no longer supported for Gemini Code Assist for individuals",
    "RESOURCE_EXHAUSTED",
    "monthly spending cap",
    "Too Many Requests",
    "429",
)

CLAUDE_LIMIT_MARKERS = (
    "rate limit",
    "usage limit",
    "quota",
    "too many requests",
    "429",
    "limit reached",
    "exceeded",
)

# Tum ajanlar (codex/claude/gemini) icin genel "kullanim limiti / kota doldu" gostergeleri.
USAGE_LIMIT_MARKERS = (
    "usage limit",
    "hit your usage limit",
    "rate limit",
    "too many requests",
    "purchase more credits",
    "upgrade to pro",
    "monthly spending cap",
    "resource_exhausted",
    "limit reached",
    "quota",
    "429",
)


def is_usage_limit_error(text: str) -> bool:
    """Ajan ciktisi kullanim limiti / kota dolmasina mi isaret ediyor?"""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in USAGE_LIMIT_MARKERS)


def usage_limit_notice(agent: str, text: str) -> str | None:
    """Limit tespit edilirse kullaniciya gosterilecek net Turkce mesaj; yoksa None."""
    if not is_usage_limit_error(text):
        return None
    label = {"codex": "Codex (ChatGPT)", "claude": "Claude", "gemini": "Gemini"}.get(
        agent, agent or "Ajan"
    )
    when = ""
    match = re.search(r"try again at ([0-9:apmAPM\.\s]+)", text or "")
    if match:
        when = f" Tekrar deneme zamani: {match.group(1).strip()}."
    return (
        f"{label} kullanim limitin dolmus gorunuyor. Ayni anda tekrar tekrar denemek "
        f"limit dolu oldugu icin ise yaramaz ve bos yere token/limit harcar.{when}"
    )


def resolve_project_dir(project_dir: str | os.PathLike[str] | None = None) -> Path:
    raw = Path(project_dir if project_dir is not None else WF.PROJECT_DIR)
    if not raw.is_absolute():
        raw = BASE_DIR / raw
    return raw.resolve()


def _clean_state(raw: Any) -> dict[str, Any]:
    # Faz 3a: dogrulama/temizleme pydantic modeline devredildi (models.OrkestraState).
    # Geri kalan kod state'i dict olarak kullandigi icin sozluk dondururuz.
    return OrkestraState.from_raw(raw).to_dict()


def load_state(project_dir: str | os.PathLike[str], *, warn: bool = False) -> dict[str, Any]:
    p = Path(project_dir) / STATE_FILE
    if not p.exists():
        return {"completed": [], "last_run": None}
    try:
        return _clean_state(json.loads(p.read_text(encoding="utf-8")))
    except Exception as exc:
        if warn:
            log(f"  ! Durum dosyası okunamadı, sıfırdan başlanacak: {exc}", C.YELLOW)
        return {"completed": [], "last_run": None}


def save_state(project_dir: str | os.PathLike[str], state: dict[str, Any]) -> None:
    clean = _clean_state(state)
    clean["last_run"] = datetime.now().isoformat(timespec="seconds")
    p = Path(project_dir) / STATE_FILE
    p.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")


def chat_path(project_dir: str | os.PathLike[str]) -> Path:
    return Path(project_dir) / CHAT_FILE


def request_path(project_dir: str | os.PathLike[str]) -> Path:
    return Path(project_dir) / REQUEST_FILE


def read_user_request(project_dir: str | os.PathLike[str]) -> str:
    path = request_path(project_dir)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def save_user_request(project_dir: str | os.PathLike[str], text: str) -> Path:
    path = request_path(project_dir)
    clean = text.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(clean + ("\n" if clean else ""), encoding="utf-8")
    return path


def brief_questions_path(project_dir: str | os.PathLike[str]) -> Path:
    return Path(project_dir) / BRIEF_QUESTIONS_FILE


def generated_workflow_path(project_dir: str | os.PathLike[str]) -> Path:
    return Path(project_dir) / GENERATED_WORKFLOW_FILE


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def brief_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def workflow_hash(stages: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(stages).encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "soru"


def normalize_brief_questions(data: Any) -> list[dict[str, Any]]:
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or not (3 <= len(questions) <= 5):
        return [dict(item) for item in DEFAULT_BRIEF_QUESTIONS]

    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for item in questions:
        if not isinstance(item, dict):
            return [dict(default) for default in DEFAULT_BRIEF_QUESTIONS]
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            return [dict(default) for default in DEFAULT_BRIEF_QUESTIONS]
        raw_id = item.get("id")
        qid = _slug(raw_id if isinstance(raw_id, str) and raw_id.strip() else question)
        base = qid
        suffix = 2
        while qid in used_ids:
            qid = f"{base}_{suffix}"
            suffix += 1
        used_ids.add(qid)
        hint = item.get("hint")
        normalized.append(
            {
                "id": qid,
                "question": question.strip(),
                "hint": hint.strip() if isinstance(hint, str) else "",
                "required": bool(item.get("required", True)),
            }
        )
    return normalized


def save_brief_questions(project_dir: str | os.PathLike[str], questions: list[dict[str, Any]]) -> Path:
    path = brief_questions_path(project_dir)
    path.write_text(
        json.dumps({"questions": questions}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_brief_questions(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    path = brief_questions_path(project_dir)
    if not path.exists():
        return [dict(item) for item in DEFAULT_BRIEF_QUESTIONS]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Brief sorulari okunamadi, varsayilana donuluyor: %s", exc)
        return [dict(item) for item in DEFAULT_BRIEF_QUESTIONS]
    return normalize_brief_questions(raw)


def save_structured_brief(
    project_dir: str | os.PathLike[str],
    initial_request: str,
    answers: list[dict[str, str]] | dict[str, str],
) -> str:
    initial = initial_request.strip()
    lines = [
        "# Kullanici Istegi",
        "",
        "## Ilk istek",
        initial or "-",
        "",
        "## Netlestirme cevaplari",
    ]

    if isinstance(answers, dict):
        iterable = [{"question": key, "answer": value} for key, value in answers.items()]
    else:
        iterable = answers

    for item in iterable:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question and not answer:
            continue
        lines.append(f"- {question or 'Soru'}: {answer or '-'}")

    final_text = "\n".join(lines).strip() + "\n"
    save_user_request(project_dir, final_text)
    return final_text


def _safe_relative_file(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"Generated workflow icinde '{field}' bos olmayan metin olmali.")
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/") or ":" in raw:
        raise WorkflowError(f"Generated workflow guvensiz dosya yolu iceriyor: {raw}")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise WorkflowError(f"Generated workflow guvensiz dosya yolu iceriyor: {raw}")
    return "/".join(parts)


def _normalize_stage(raw: Any, idx: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError(f"Generated workflow {idx}. adim sozluk olmali.")
    stage: dict[str, Any] = {}
    for key in ("name", "agent", "prompt"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise WorkflowError(f"Generated workflow {idx}. adimda '{key}' bos olmayan metin olmali.")
        stage[key] = value.strip()

    if stage["agent"] == "auto":
        # Otomatik ajan secimi: is turune gore (UI->gemini, test/plan->codex, kod->claude).
        stage["agent"] = suggest_agent(f"{stage['name']} {stage['prompt']}")
    if stage["agent"] not in AGENT_COMMANDS:
        known = ", ".join(AGENT_COMMANDS)
        raise WorkflowError(f"Generated workflow {idx}. adimda gecersiz ajan: {stage['agent']}. Gecerli: {known}")

    for key in ("reads", "writes"):
        values = raw.get(key, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise WorkflowError(f"Generated workflow {idx}. adimda '{key}' liste olmali.")
        stage[key] = [_safe_relative_file(item, field=key) for item in values]

    stage["checkpoint"] = bool(raw.get("checkpoint", idx < 5))
    timeout = raw.get("timeout", WF.DEFAULT_TIMEOUT)
    if not isinstance(timeout, int) or timeout <= 0:
        raise WorkflowError(f"Generated workflow {idx}. adimda timeout pozitif tam sayi olmali.")
    stage["timeout"] = timeout

    test_cmd = raw.get("test_command")
    if test_cmd:
        stage["test_command"] = test_cmd.strip() if isinstance(test_cmd, str) else ""

    fallback = raw.get("fallback_agent")
    if not fallback:
        # Varsayilan yedek ajan haritasi tek yerden okunur (mimari tutarlilik).
        fallback = DEFAULT_FALLBACK_AGENTS.get(stage["agent"])
    if fallback is not None:
        if not isinstance(fallback, str) or fallback not in AGENT_COMMANDS or fallback == stage["agent"]:
            raise WorkflowError(f"Generated workflow {idx}. adimda fallback_agent gecersiz.")
        stage["fallback_agent"] = fallback
    return stage


def validate_generated_workflow(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise WorkflowError("Generated workflow JSON kok nesnesi sozluk olmali.")
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, list) or not (3 <= len(raw_stages) <= 8):
        raise WorkflowError("Generated workflow 3 ile 8 arasinda adim icermeli.")
    stages = [_normalize_stage(stage, idx) for idx, stage in enumerate(raw_stages, 1)]
    validate_workflow(stages)
    summary = data.get("summary")
    project_type = data.get("project_type")
    current_brief_hash = data.get("brief_hash")
    test_command = data.get("test_command")
    return {
        "summary": summary.strip() if isinstance(summary, str) else "",
        "project_type": project_type.strip() if isinstance(project_type, str) else "custom",
        "brief_hash": current_brief_hash.strip() if isinstance(current_brief_hash, str) else "",
        "test_command": test_command.strip() if isinstance(test_command, str) else "",
        "stages": stages,
    }


def workflow_versions_dir(project_dir: str | os.PathLike[str]) -> Path:
    path = app_data_dir(project_dir) / WORKFLOW_VERSIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_generated_workflow(project_dir: str | os.PathLike[str], data: dict[str, Any]) -> Path:
    normalized = validate_generated_workflow(data)
    path = generated_workflow_path(project_dir)
    new_text = json.dumps(normalized, indent=2, ensure_ascii=False)
    # Versiyonlama: mevcut workflow degisiyorsa eski surumu sakla (geri donulebilir).
    if path.exists():
        old_text = path.read_text(encoding="utf-8")
        if old_text.strip() != new_text.strip():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (workflow_versions_dir(project_dir) / f"workflow_{stamp}.json").write_text(
                old_text, encoding="utf-8"
            )
    path.write_text(new_text, encoding="utf-8")
    return path


def list_workflow_versions(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vpath in sorted(workflow_versions_dir(project_dir).glob("workflow_*.json"), reverse=True):
        summary = ""
        try:
            raw = json.loads(vpath.read_text(encoding="utf-8"))
            summary = str(raw.get("summary", ""))[:120]
        except Exception as exc:
            logger.debug("Workflow surumu okunamadi (%s): %s", vpath, exc)
        rows.append({"name": vpath.stem, "path": str(vpath), "summary": summary})
    return rows


def restore_workflow_version(project_dir: str | os.PathLike[str], name: str) -> dict[str, Any]:
    """Eski workflow surumune doner; mevcut olan once versiyonlanir."""
    safe = Path(name).name
    vpath = workflow_versions_dir(project_dir) / f"{safe}.json"
    if not vpath.exists():
        raise WorkflowError(f"Workflow surumu bulunamadi: {safe}")
    data = validate_generated_workflow(json.loads(vpath.read_text(encoding="utf-8")))
    save_generated_workflow(project_dir, data)
    return data


def diff_workflow_versions(project_dir: str | os.PathLike[str], name: str) -> str:
    """Verilen surum ile MEVCUT workflow arasindaki birlesik farki dondurur."""
    safe = Path(name).name
    vpath = workflow_versions_dir(project_dir) / f"{safe}.json"
    current = generated_workflow_path(project_dir)
    old = vpath.read_text(encoding="utf-8") if vpath.exists() else ""
    new = current.read_text(encoding="utf-8") if current.exists() else ""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=safe,
            tofile="mevcut",
        )
    )


def load_generated_workflow(project_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    path = generated_workflow_path(project_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return validate_generated_workflow(raw)
    except Exception as exc:
        logger.debug("Uretilmis workflow okunamadi (%s): %s", path, exc)
        return None


def app_data_dir(project_dir: str | os.PathLike[str]) -> Path:
    path = Path(project_dir) / ORKESTRA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def workflow_store_dir(project_dir: str | os.PathLike[str]) -> Path:
    path = app_data_dir(project_dir) / WORKFLOWS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_store_dir(project_dir: str | os.PathLike[str]) -> Path:
    path = app_data_dir(project_dir) / SNAPSHOTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_named_workflow(project_dir: str | os.PathLike[str], name: str, data: dict[str, Any]) -> Path:
    normalized = validate_generated_workflow(data)
    slug = _slug(name)
    path = workflow_store_dir(project_dir) / f"{slug}.json"
    payload = dict(normalized)
    payload["saved_name"] = name.strip() or slug
    payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_named_workflow(project_dir: str | os.PathLike[str], name: str) -> dict[str, Any] | None:
    path = workflow_store_dir(project_dir) / f"{_slug(name)}.json"
    if not path.exists():
        return None
    try:
        return validate_generated_workflow(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        logger.debug("Kayitli workflow okunamadi (%s): %s", path, exc)
        return None


def delete_named_workflow(project_dir: str | os.PathLike[str], name: str) -> bool:
    path = workflow_store_dir(project_dir) / f"{_slug(name)}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def list_named_workflows(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(workflow_store_dir(project_dir).glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = validate_generated_workflow(raw)
        except Exception as exc:
            logger.debug("Kayitli workflow atlandi (%s): %s", path, exc)
            continue
        items.append(
            {
                "key": path.stem,
                "name": str(raw.get("saved_name") or path.stem),
                "summary": data.get("summary", ""),
                "project_type": data.get("project_type", "custom"),
                "stages": len(data.get("stages", [])),
                "mtime": path.stat().st_mtime,
            }
        )
    return items


def append_metric(project_dir: str | os.PathLike[str], entry: dict[str, Any]) -> None:
    path = app_data_dir(project_dir) / METRICS_FILE
    payload = dict(entry)
    payload.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    _locked_append(path, json.dumps(payload, ensure_ascii=False) + "\n")


# ---------------- Calistirma (run) kayitlari ----------------

def append_run_record(project_dir: str | os.PathLike[str], record: dict[str, Any]) -> None:
    """Her calistirmayi tek satir JSON olarak runs.jsonl'a ekler ("bu iste ne oldu?")."""
    path = app_data_dir(project_dir) / RUNS_FILE
    payload = dict(record)
    payload.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    _locked_append(path, json.dumps(payload, ensure_ascii=False) + "\n")


def load_run_records(project_dir: str | os.PathLike[str], limit: int = 50) -> list[dict[str, Any]]:
    path = app_data_dir(project_dir) / RUNS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception as exc:
            logger.debug("Bozuk run kaydi atlandi: %s", exc)
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-limit:]


def produced_files(project_dir: str | os.PathLike[str], stages: list[dict[str, Any]]) -> list[str]:
    """Workflow'un 'writes' listelerinden gercekten olusmus dosyalari dondurur."""
    seen: list[str] = []
    for stage in stages:
        for rel in stage.get("writes", []):
            if rel not in seen and (Path(project_dir) / rel).exists():
                seen.append(rel)
    return seen


# ---------------- Yapisal olay logu (makine okunur) ----------------

def _locked_append(path: Path, line: str) -> None:
    """JSONL'a surecler-arasi guvenli ekleme.

    GUI ve web panel ayni projeyi ayni anda yazabilir; kilitsiz iki 'a' modu
    yazma satirlari ic ice gecirebilir. Bayt-0 kilidi mutex olarak kullanilir.
    """
    with path.open("a", encoding="utf-8", errors="replace") as fh:
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    locked = True
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                    locked = True
                except OSError:
                    pass
            fh.seek(0, os.SEEK_END)
            fh.write(line)
            fh.flush()
        finally:
            if locked:
                try:
                    if os.name == "nt":
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def append_event(project_dir: str | os.PathLike[str], event: str, **fields: Any) -> None:
    """Makine okunur olay kaydi (events.jsonl): run_started, stage_started,
    stage_finished, fallback_detected, test_failed, run_finished...
    Kullanici logundan ayridir; sonradan analiz/izleme icindir."""
    try:
        path = app_data_dir(project_dir) / EVENTS_FILE
        row = {"event": event, "timestamp": datetime.now().isoformat(timespec="seconds"), **fields}
        _locked_append(path, json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("Olay kaydi yazilamadi (%s): %s", event, exc)


def load_events(project_dir: str | os.PathLike[str], limit: int = 200) -> list[dict[str, Any]]:
    path = app_data_dir(project_dir) / EVENTS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception as exc:
            logger.debug("Bozuk olay satiri atlandi: %s", exc)
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-limit:]


# ---------------- Ajan karar kayitlari ----------------

def extract_last_handoff(project_dir: str | os.PathLike[str], agent: str) -> str:
    """sohbet.md'den ilgili ajanin SON devir notunu cikarir (karar ozeti)."""
    path = chat_path(project_dir)
    if not path.exists():
        return ""
    agent_key = (agent or "").strip().lower()
    body: list[str] = []
    found = ""
    header = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            if header and agent_key and agent_key in header.lower():
                found = "\n".join(body).strip()
            header = line[3:]
            body = []
        elif not line.startswith("# "):
            body.append(line)
    if header and agent_key and agent_key in header.lower():
        found = "\n".join(body).strip()
    return found[:500]


def record_stage_decision(
    project_dir: str | os.PathLike[str],
    run_id: str,
    idx: int,
    stage: dict[str, Any],
    changed_files: list[str],
    summary: str,
) -> None:
    """Adim karari: kim, neye bakti, neyi degistirdi, kisa ozet (decisions.jsonl)."""
    try:
        path = app_data_dir(project_dir) / DECISIONS_FILE
        row = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id,
            "idx": idx,
            "stage": str(stage.get("name", "")),
            "agent": str(stage.get("agent", "")),
            "okudu": stage.get("reads", []),
            "degistirdi": changed_files,
            "ozet": summary[:500],
        }
        _locked_append(path, json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("Karar kaydi yazilamadi: %s", exc)


def load_decisions(project_dir: str | os.PathLike[str], limit: int = 100) -> list[dict[str, Any]]:
    path = app_data_dir(project_dir) / DECISIONS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-limit:]


# ---------------- Ajan hafizasi (proje bazli) ----------------

def memory_path(project_dir: str | os.PathLike[str]) -> Path:
    return app_data_dir(project_dir) / HAFIZA_FILE


def load_project_memory(project_dir: str | os.PathLike[str], limit_chars: int = 1500) -> str:
    """Proje hafizasini (stack, kararlar, yasakli tercihler) dondurur; son kismi alinir."""
    path = memory_path(project_dir)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[-limit_chars:] if len(text) > limit_chars else text


def append_project_memory(project_dir: str | os.PathLike[str], note: str) -> None:
    note = (note or "").strip()
    if not note:
        return
    path = memory_path(project_dir)
    stamp = datetime.now().strftime("%Y-%m-%d")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{stamp}] {note}\n")


# ---------------- Context sikistirici (buyuk proje ozeti) ----------------

_IMPORTANT_FILE_NAMES = (
    "readme.md", "package.json", "pyproject.toml", "requirements.txt",
    "main.py", "app.py", "index.html", "index.js", "index.ts", "manage.py",
)


def build_context_summary(
    project_dir: str | os.PathLike[str],
    max_files: int = 15,
    head_lines: int = 30,
    max_chars: int = 16000,
) -> Path:
    """Buyuk projede ajanlara tum dosyalar yerine kisa bir ozet verir:
    dizin agaci + onemli/en guncel dosyalarin ilk satirlari -> proje_ozeti.md."""
    root = Path(project_dir).resolve()
    skip = set(SNAPSHOT_SKIP_DIRS) | {"karsilastirma"}
    tree_lines: list[str] = []
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in skip or part.startswith(".") for part in rel.parts):
            continue
        if len(rel.parts) <= 3 and len(tree_lines) < 200:
            marker = "/" if path.is_dir() else ""
            tree_lines.append("  " * (len(rel.parts) - 1) + f"- {rel.parts[-1]}{marker}")
        if path.is_file() and path.suffix.lower() in (".py", ".js", ".ts", ".tsx", ".html", ".css", ".md", ".json", ".toml", ".yaml", ".yml"):
            candidates.append(path)

    def rank(p: Path) -> tuple[int, float]:
        important = 0 if p.name.lower() in _IMPORTANT_FILE_NAMES else 1
        return (important, -p.stat().st_mtime)

    chosen = sorted(candidates, key=rank)[:max_files]
    parts = [
        "# Proje Ozeti (otomatik)",
        "",
        "Ajanlar icin sikistirilmis baglam: once bunu oku, gerekirse ilgili dosyayi ac.",
        "",
        "## Dizin agaci",
        *tree_lines,
        "",
        "## Onemli dosyalarin basi",
    ]
    for p in chosen:
        rel = p.relative_to(root)
        try:
            head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:head_lines])
        except OSError:
            continue
        parts += ["", f"### {rel}", "```", head, "```"]
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (ozet kirpildi)"
    out = root / CONTEXT_SUMMARY_FILE
    out.write_text(text, encoding="utf-8")
    return out


# ---------------- Sonuc kalite etiketi ----------------

def assess_run_quality(
    project_dir: str | os.PathLike[str],
    stages: list[dict[str, Any]],
    status: str,
    error: str = "",
) -> dict[str, str]:
    """Calistirma sonucuna kalite etiketi basar:
    hazir / eksik / test gecmedi / kontrol gerekli."""
    err = (error or "").lower()
    # Genis "test" substring'i yerine siniflandirici kategorisiyle esles
    # ("latest", "test_data" gibi alakasiz metinler yanlis etiketlemesin).
    if "test-hatasi" in err or err.startswith("test"):
        return {"label": "test geçmedi", "category": "test-gecmedi"}
    if status == "complete":
        missing = [
            w for s in stages for w in s.get("writes", [])
            if not (Path(project_dir) / w).exists()
        ]
        if missing:
            return {"label": f"eksik ({', '.join(missing[:3])})", "category": "eksik"}
        return {"label": "hazır", "category": "hazir"}
    return {"label": "kontrol gerekli", "category": "kontrol-gerekli"}


# ---------------- Baslangic sihirbazi brief'i ----------------

def compose_wizard_brief(
    request: str,
    proje_tipi: str = "",
    platform: str = "",
    tasarim: str = "",
    test_beklentisi: str = "",
) -> str:
    """Sihirbaz secimlerini istek metnine yapisal blok olarak ekler."""
    lines = [request.strip()]
    picks = [
        ("Proje tipi", proje_tipi),
        ("Hedef platform", platform),
        ("Tasarım tarzı", tasarim),
        ("Test beklentisi", test_beklentisi),
    ]
    chosen = [(k, v) for k, v in picks if v and v.lower() not in ("farketmez", "seçilmedi", "secilmedi")]
    if chosen:
        lines += ["", "[Sihirbaz Seçimleri]"]
        lines += [f"- {k}: {v}" for k, v in chosen]
    return "\n".join(lines).strip()


# ---------------- Otomatik ajan secimi ----------------

AGENT_SPECIALTIES: dict[str, tuple[str, ...]] = {
    "gemini": ("ui", "tasarim", "tasarım", "arayuz", "arayüz", "design", "gorsel", "görsel", "ux", "frontend", "stil"),
    "codex": ("test", "kontrol", "plan", "analiz", "gereksinim", "review", "dogrula", "doğrula"),
    "claude": ("kod", "code", "refactor", "implement", "duzelt", "düzelt", "fix", "backend", "gelistir", "geliştir"),
}


def suggest_agent(text: str) -> str:
    """Is turune gore ajan onerir (UI->gemini, test/plan->codex, kod/refactor->claude)."""
    lowered = (text or "").lower()
    scores = {agent: sum(1 for kw in kws if kw in lowered) for agent, kws in AGENT_SPECIALTIES.items()}
    # Esitlikte belirsiz sozluk sirasina degil, acik onceliğe gore sec.
    priority = {"claude": 3, "codex": 2, "gemini": 1}
    best = max(scores, key=lambda a: (scores[a], priority.get(a, 0)))
    return best if scores[best] > 0 else "claude"


# ---------------- Retry stratejisi (hata tipine gore) ----------------

def retry_strategy(category: str) -> dict[str, str]:
    """Hata kategorisine gore sonraki hamle: same / fallback / fix_prompt / ask.

    fix_prompt icin prompt_suffix, cagiran tarafindan {writes} ile doldurulur.
    """
    table: dict[str, dict[str, str]] = {
        "limit": {"action": "fallback", "not": "Kota doldu; ayni ajani tekrar denemek bosa harcar."},
        "ajan-sapmasi": {"action": "fallback", "not": "Ajan sapti/takildi; taze ajan daha iyi sonuc verir."},
        "timeout": {"action": "same", "not": "Zaman asimi; ayni ajan bir kez daha denesin."},
        "bilinmiyor": {"action": "same", "not": "Sebep belirsiz; bir kez daha dene."},
        "eksik-cikti": {
            "action": "fix_prompt",
            "not": "Cikti dosyasi olusmadi; talimat netlestirilerek tekrar.",
            "prompt_suffix": "[ONEMLI] Su dosyalari MUTLAKA olustur ve icini doldur: {writes}. Baska hicbir sey yapmadan once bu dosyalari yaz.",
        },
        "test-hatasi": {
            "action": "fix_prompt",
            "not": "Test kirildi; hata ciktisi prompt'a eklenerek duzelttirilir.",
            "prompt_suffix": "[ONEMLI] Onceki deneme testte kirildi. hata.md / test ciktisini oku ve once hatayi duzelt.",
        },
        "eksik-arac": {"action": "ask", "not": "CLI kurulu degil; kullanici kurmadan devam edilemez."},
        "login": {"action": "ask", "not": "Oturum sorunu; kullanicinin login olmasi gerekir."},
        "path-encoding": {"action": "ask", "not": "Yol/encoding sorunu; kullanici mudahalesi gerekebilir."},
        "durduruldu": {"action": "ask", "not": "Kullanici durdurdu."},
    }
    return table.get(category, {"action": "same", "not": ""})


# ---------------- Ajan karsilastirma modu ----------------

def run_agent_comparison(
    project_dir: str | os.PathLike[str],
    prompt: str,
    agents: list[str] | None = None,
    writes: list[str] | None = None,
    timeout: int = 600,
    log: Any = print,
) -> dict[str, Any]:
    """Ayni gorevi secilen ajanlara AYRI klasorlerde yaptirir ve kiyas raporu yazar.

    DIKKAT: her ajan ayri kosar -> token/limit tuketimi ajan sayisi kadar katlanir.
    """
    from runner import run_agent_stage  # dongusel import olmasin diye gec import

    root = Path(project_dir).resolve()
    agents = agents or [a for a in ("codex", "gemini", "claude") if find_tool(a)]
    if not agents:
        raise WorkflowError("Karsilastirma icin kurulu ajan bulunamadi.")
    results: list[dict[str, Any]] = []
    for agent in agents:
        wd = root / "karsilastirma" / agent
        wd.mkdir(parents=True, exist_ok=True)
        stage = {
            "name": f"Karsilastirma-{agent}", "agent": agent, "prompt": prompt,
            "reads": [], "writes": list(writes or []), "timeout": timeout,
        }
        log(f"[karsilastirma] {agent} basliyor (klasor: {wd})")
        ok, elapsed, reason, output = run_agent_stage(
            stage, 1, 1, [stage], wd, stop_event=threading.Event(), log=log,
        )
        results.append({
            "agent": agent, "ok": ok, "reason": reason, "elapsed": round(elapsed, 1),
            "produced": produced_files(wd, [stage]),
            "output_tail": output[-400:],
        })
    lines = [
        "# Ajan Karsilastirma Raporu", "",
        f"Gorev: {prompt[:300]}", "",
        "| Ajan | Sonuc | Sure | Uretilen dosyalar |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        durum = "basarili" if r["ok"] else f"basarisiz ({r['reason']})"
        lines.append(f"| {r['agent']} | {durum} | {r['elapsed']}sn | {', '.join(r['produced']) or '-'} |")
    lines += ["", "Ciktilar `karsilastirma/<ajan>/` klasorlerinde; en begendigini projeye tasi."]
    report = root / "karsilastirma.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return {"results": results, "report": report}


# ---------------- Otomatik hata siniflandirma ----------------

_FAILURE_LOGIN_MARKERS = (
    "not logged in",
    "please log in",
    "please login",
    "/login",
    "unauthorized",
    "401",
    "invalid api key",
    "api key not",
    "credential",
    "oauth",
)

_FAILURE_PATH_ENCODING_MARKERS = (
    "unicodedecodeerror",
    "unicodeencodeerror",
    "charmap",
    "cp125",
    "filenotfounderror",
    "no such file or directory",
    "cannot find the path",
    "is not recognized as an internal",
    "permission denied",
    "erisim engellendi",
)


def classify_failure(reason: str, output_text: str = "") -> dict[str, str]:
    """Hata sebebini kategoriye ayirir; kullaniciya net Turkce oneri verir.

    Kategoriler: limit, eksik-arac, login, timeout, eksik-cikti, test-hatasi,
    path-encoding, ajan-sapmasi, durduruldu, bilinmiyor.
    """
    reason = (reason or "").lower()
    lowered = (output_text or "").lower()

    def result(category: str, label: str, advice: str) -> dict[str, str]:
        return {"category": category, "label": label, "advice": advice}

    if reason == "not-found":
        return result("eksik-arac", "Araç kurulu değil",
                      "Gerekli CLI PATH'te yok. Kurulum: npm install -g ... (README'ye bak).")
    if reason == "timeout":
        return result("timeout", "Zaman aşımı",
                      "Adım süre sınırını aştı. Timeout'u artır veya görevi küçült.")
    if reason == "stuck":
        return result("ajan-sapmasi", "Ajan takıldı/sessiz kaldı",
                      "Ajan uzun süre çıktı üretmedi. Adımı tekrar dene; olmuyorsa fallback ajana devret.")
    if reason == "stopped":
        return result("durduruldu", "Kullanıcı durdurdu",
                      "Akış elle durduruldu. 'Devam' ile kaldığın yerden sürebilirsin.")
    # Sebep-temelli kategoriler, cikti-metni taramasindan ONCE gelir; yoksa
    # "limit/quota/429" gecen bir test ciktisi yanlislikla 'limit' sayilir.
    if "test" in reason:
        return result("test-hatasi", "Test başarısız",
                      "Otomatik test hata verdi. hata.md'yi incele; 'Tekrar' ile hatayı prompt'a ekleyip düzelttir.")
    if "missing" in reason or "eksik" in reason:
        return result("eksik-cikti", "Beklenen çıktı oluşmadı",
                      "Ajan bitirdi ama beklenen dosya yok. Adımı tekrar çalıştır; prompt'ta dosya adını netleştir.")
    if is_usage_limit_error(lowered):
        return result("limit", "Kullanım limiti doldu",
                      "Ajanın kotası doldu. Limit yenilenene kadar bekle veya fallback ajana devret.")
    if any(marker in lowered for marker in _FAILURE_LOGIN_MARKERS):
        return result("login", "CLI oturum/giriş sorunu",
                      "Ajan CLI'sinde oturum açık değil. Terminalde aracı çalıştırıp login ol.")
    if any(marker in lowered for marker in _FAILURE_PATH_ENCODING_MARKERS):
        return result("path-encoding", "Yol/encoding hatası",
                      "Dosya yolu veya karakter kodlaması sorunu. Türkçe karakterli/eksik yolları kontrol et.")
    if reason == "exit":
        return result("ajan-sapmasi", "Ajan hatayla çıktı",
                      "Ajan beklenmedik şekilde hata verdi. Teknik Log'a bak; adımı tekrar dene veya fallback kullan.")
    return result("bilinmiyor", "Sınıflandırılamadı",
                  "Teknik Log'daki son satırlara bak; gerekirse adımı tekrar çalıştır.")


# ---------------- Baslamadan saglik kontrolu (preflight) ----------------

def preflight_check(
    project_dir: str | os.PathLike[str],
    stages: list[dict[str, Any]],
    start_idx: int = 1,
) -> list[dict[str, str]]:
    """'Başlat' öncesi sağlık kontrolü. [{level: 'hata'|'uyari', 'mesaj': ...}] döner."""
    findings: list[dict[str, str]] = []
    root = Path(project_dir)

    try:
        validate_workflow(stages)
    except WorkflowError as exc:
        findings.append({"level": "hata", "mesaj": f"Workflow geçersiz: {exc}"})
        return findings

    missing = missing_required_tools(stages[start_idx - 1:])
    if missing:
        findings.append({"level": "hata", "mesaj": f"Eksik ajan komutları: {', '.join(missing)}"})

    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".maestro_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        findings.append({"level": "hata", "mesaj": f"Proje klasörüne yazılamıyor: {exc}"})

    first = stages[start_idx - 1]
    missing_in = check_inputs(root, first)
    if missing_in:
        findings.append({
            "level": "uyari",
            "mesaj": f"{start_idx}. adımın girdi dosyaları henüz yok: {', '.join(missing_in)}",
        })

    state = load_state(root)
    done = [s for s in state.get("completed", []) if isinstance(s, int)]
    if done and len(done) < len(stages) and state.get("workflow_hash") == workflow_hash(stages):
        findings.append({
            "level": "uyari",
            "mesaj": f"Önceki yarım iş var: {len(done)}/{len(stages)} adım bitmiş. 'Devam' ile sürdürmek token tasarrufu sağlar.",
        })
    return findings


def infer_completed_from_outputs(
    project_dir: str | os.PathLike[str],
    stages: list[dict[str, Any]],
) -> list[int]:
    """Dosyalara bakarak tamamlanmis sayilabilecek ADIM ONEKINI cikarir.

    Kural: bastan itibaren, 'writes' listesi dolu ve TAMAMI diskte olan adimlar
    tamamlanmis sayilir; ilk dogrulanamayan adimda durulur (guvenli toparlama).
    """
    done: list[int] = []
    for i, stage in enumerate(stages, 1):
        writes = stage.get("writes", [])
        if not writes:
            break
        if verify_outputs(project_dir, stage):
            break
        done.append(i)
    return done


def load_metrics(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    path = app_data_dir(project_dir) / METRICS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception as exc:
            logger.debug("Bozuk metrik satiri atlandi: %s", exc)
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def append_terminal_history(project_dir: str | os.PathLike[str], command: str, returncode: int | None = None) -> None:
    path = app_data_dir(project_dir) / TERMINAL_HISTORY_FILE
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "command": command,
        "returncode": returncode,
    }
    with path.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_terminal_history(project_dir: str | os.PathLike[str], limit: int = 50) -> list[dict[str, Any]]:
    path = app_data_dir(project_dir) / TERMINAL_HISTORY_FILE
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception as exc:
            logger.debug("Bozuk terminal gecmisi satiri atlandi: %s", exc)
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-limit:]


def load_prompt_profiles(project_dir: str | os.PathLike[str]) -> dict[str, str]:
    defaults = {
        "agresif kodla": "Gereksiz tartisma yapma; eksikleri tamamla, calisan kod uret, dosyalari dogrudan guncelle.",
        "sadece analiz": "Kod yazma; sadece analiz, riskler, gereksinimler ve uygulanabilir plan cikar.",
        "UI odakli": "Arayuz kalitesine, hiyerarsiye, responsive davranisa ve kullanici deneyimine oncelik ver.",
        "bugfix odakli": "Sadece hatayi duzelt; gereksiz refactor yapma, mevcut davranisi koru.",
    }
    path = app_data_dir(project_dir) / PROMPTS_FILE
    if not path.exists():
        path.write_text(json.dumps(defaults, indent=2, ensure_ascii=False), encoding="utf-8")
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Prompt profilleri okunamadi, varsayilana donuluyor: %s", exc)
        return defaults
    if not isinstance(raw, dict):
        return defaults
    profiles = dict(defaults)
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
            profiles[key.strip()] = value.strip()
    return profiles


def save_prompt_profiles(project_dir: str | os.PathLike[str], profiles: dict[str, str]) -> Path:
    clean = {str(k).strip(): str(v).strip() for k, v in profiles.items() if str(k).strip() and str(v).strip()}
    path = app_data_dir(project_dir) / PROMPTS_FILE
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _snapshot_allowed(project_dir: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(project_dir)
    except ValueError:
        return False
    if any(part in SNAPSHOT_SKIP_DIRS for part in rel.parts):
        return False
    if path.name in SNAPSHOT_SKIP_FILES:
        return False
    return path.is_file()


def _copy_snapshot_files(src_root: Path, dst_root: Path, project_root: Path | None = None) -> tuple[int, int]:
    count = 0
    total = 0
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        if project_root is not None and not _snapshot_allowed(project_root, path):
            continue
        rel = path.relative_to(src_root)
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
        try:
            total += target.stat().st_size
        except OSError:
            pass
    return count, total


def create_snapshot(project_dir: str | os.PathLike[str], run_id: str, step_idx: int, stage: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_dir).resolve()
    snap_name = f"step_{step_idx:03d}_{_slug(str(stage.get('name', 'adim')))}"
    snap_dir = snapshot_store_dir(root) / _slug(run_id) / snap_name
    files_dir = snap_dir / "files"
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    files_dir.mkdir(parents=True, exist_ok=True)
    count, total = _copy_snapshot_files(root, files_dir, root)
    meta = {
        "id": f"{_slug(run_id)}/{snap_name}",
        "run_id": _slug(run_id),
        "step": step_idx,
        "stage_name": stage.get("name", ""),
        "agent": stage.get("agent", ""),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "file_count": count,
        "size": total,
    }
    (snap_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def list_snapshots(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = snapshot_store_dir(project_dir)
    for meta_path in root.glob("*/*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Snapshot meta okunamadi (%s): %s", meta_path, exc)
            continue
        if isinstance(meta, dict):
            rows.append(meta)
    rows.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return rows


def snapshot_files_dir(project_dir: str | os.PathLike[str], snapshot_id: str) -> Path:
    clean = snapshot_id.replace("\\", "/").strip("/")
    parts = [part for part in clean.split("/") if part]
    if len(parts) != 2 or any(part in (".", "..") for part in parts):
        raise WorkflowError("Gecersiz snapshot id.")
    path = snapshot_store_dir(project_dir) / parts[0] / parts[1] / "files"
    if not path.exists():
        raise WorkflowError("Snapshot bulunamadi.")
    return path


def restore_snapshot(project_dir: str | os.PathLike[str], snapshot_id: str) -> None:
    root = Path(project_dir).resolve()
    files_dir = snapshot_files_dir(root, snapshot_id)
    for path in list(root.rglob("*")):
        if _snapshot_allowed(root, path):
            try:
                path.unlink()
            except OSError:
                pass
    _copy_snapshot_files(files_dir, root)


def restore_snapshot_files(project_dir: str | os.PathLike[str], snapshot_id: str, files: list[str]) -> None:
    root = Path(project_dir).resolve()
    files_dir = snapshot_files_dir(root, snapshot_id)
    for rel in files:
        safe = _safe_relative_file(rel, field="snapshot_file")
        src = files_dir / safe
        dst = root / safe
        if not src.exists():
            if dst.exists() and _snapshot_allowed(root, dst):
                dst.unlink()
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def snapshot_diff(project_dir: str | os.PathLike[str], snapshot_id: str, rel_file: str) -> str:
    safe = _safe_relative_file(rel_file, field="snapshot_file")
    root = Path(project_dir).resolve()
    files_dir = snapshot_files_dir(root, snapshot_id)
    before_path = files_dir / safe
    after_path = root / safe
    before = before_path.read_text(encoding="utf-8", errors="replace") if before_path.exists() else ""
    after = after_path.read_text(encoding="utf-8", errors="replace") if after_path.exists() else ""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{snapshot_id}/{safe}",
            tofile=safe,
            lineterm="",
        )
    )


def ensure_chat_file(project_dir: str | os.PathLike[str]) -> Path:
    path = chat_path(project_dir)
    if not path.exists():
        path.write_text(
            "# AI Orkestra Sohbeti\n\n"
            "Bu dosya ajanlar arasindaki devir notlarini tutar. "
            "Ajanlar isi bitince buraya kisa bir ozet ve siradaki ajana not ekler.\n\n",
            encoding="utf-8",
        )
    return path


def append_chat_entry(project_dir: str | os.PathLike[str], speaker: str, message: str) -> None:
    path = ensure_chat_file(project_dir)
    stamp = datetime.now().isoformat(timespec="seconds")
    clean_message = message.strip() or "-"
    with path.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(f"## {stamp} - {speaker}\n{clean_message}\n\n")


def read_chat_tail(project_dir: str | os.PathLike[str], limit: int = 5000) -> str:
    path = ensure_chat_file(project_dir)
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return "... onceki sohbet kirpildi ...\n" + text[-limit:]


def stage_ref(stage: dict[str, Any], idx: int | None = None) -> str:
    prefix = f"{idx}. " if idx is not None else ""
    return f"{prefix}{stage.get('name', 'Adsiz')} [{stage.get('agent', '?')}]"


def next_stage_ref(stages: list[dict[str, Any]] | None, idx: int | None) -> str:
    if not stages or idx is None or idx >= len(stages):
        return "Son adim; siradaki ajan yok."
    return stage_ref(stages[idx], idx + 1)


def build_stage_prompt(
    stage: dict[str, Any],
    *,
    idx: int | None = None,
    total: int | None = None,
    stages: list[dict[str, Any]] | None = None,
    project_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Ajan gorevini ortak sohbet/handoff talimatiyla sarar."""
    if idx is None or total is None:
        return stage["prompt"]

    reads = ", ".join(stage.get("reads", [])) or "-"
    writes = ", ".join(stage.get("writes", [])) or "-"
    next_ref = next_stage_ref(stages, idx)
    workspace_block = ""
    if project_dir is not None:
        workspace_path = Path(project_dir).resolve()
        workspace_block = (
            f"Gercek proje klasoru: {workspace_path}\n"
            "Dosya okuma/yazma islemlerini bu klasor altinda yap; Antigravity scratch veya gecici "
            "calisma alanina asil cikti yazma.\n"
        )
    user_request = read_user_request(project_dir).strip() if project_dir is not None else ""
    if user_request:
        request_block = (
            f"KULLANICI ANA ISTEGI ({REQUEST_FILE}):\n"
            f"{user_request}\n\n"
            "Bu kullanici istegi workflow.py icindeki ornek/iskelet ifadelerden ustundur. "
            "Karar verirken once bu istegi esas al.\n\n"
        )
    else:
        request_block = (
            f"KULLANICI ANA ISTEGI: {REQUEST_FILE} dosyasi bos veya henuz yok.\n"
            "Eger gorevin planlama ise kullanicidan net is istegi gelmeden sabit demo proje uretme.\n\n"
        )
    memory_block = ""
    context_hint = ""
    if project_dir is not None:
        memory = load_project_memory(project_dir)
        if memory:
            memory_block = (
                "PROJE HAFIZASI (onceki kararlar, stack, yasakli tercihler - bunlara uy):\n"
                f"{memory}\n\n"
            )
        if (Path(project_dir) / CONTEXT_SUMMARY_FILE).exists():
            context_hint = (
                f"- Buyuk proje: once {CONTEXT_SUMMARY_FILE} ozetini oku; "
                "tum dosyalari tek tek gezme, ozetten ilgili dosyaya git.\n"
            )
    return (
        "AI Orkestra akisi icinde calisiyorsun. Ortak calisma klasorundesin.\n"
        f"{workspace_block}"
        f"Siradaki gorevin: {stage_ref(stage, idx)}/{total}\n"
        f"Okuman beklenen dosyalar: {reads}\n"
        f"Uretmen beklenen dosyalar: {writes}\n"
        f"Senden sonraki devir: {next_ref}\n\n"
        f"{request_block}"
        f"{memory_block}"
        "Ortak sohbet alani: sohbet.md\n"
        f"Kullanici istek dosyasi: {REQUEST_FILE}\n"
        f"{context_hint}"
        "- Ise baslamadan sohbet.md dosyasindaki son notlari oku.\n"
        f"- {REQUEST_FILE} dosyasi varsa kullanicinin asil istegi olarak oku.\n"
        "- Asil gorevini bitirince sohbet.md dosyasina kisa bir devir notu ekle.\n"
        "- Devir notunda sunlar olsun: ne yaptin, NEDEN o yaklasimi sectin, hangi dosyalara baktin, "
        "hangi dosyalari urettin/degistirdin, siradaki ajana net talimat, "
        "kullanici onayi gerekiyorsa bunu acikca yaz.\n"
        f"- Kalici bir karar/stack tercihi/yasak olustuysa .orkestra/{HAFIZA_FILE} dosyasina TEK satirlik madde ekle.\n"
        "- Samimi ama teknik olarak net konusabilirsin; gereksiz uzatma.\n\n"
        "ASIL GOREV:\n"
        f"{stage['prompt']}"
    )


def normalize_prompt_for_cli(prompt: str) -> str:
    """Windows .cmd tabanli CLI'larda satir sonu komutu bolmesin diye tek satira indirir."""
    return " ".join(line.strip() for line in prompt.splitlines() if line.strip())


def load_fnm_environment() -> None:
    """Explorer'dan acilan uygulamada fnm Node shim yollarini PATH'e ekler."""
    global _FNM_ENV_LOADED
    if _FNM_ENV_LOADED or os.name != "nt":
        return
    _FNM_ENV_LOADED = True

    fnm = shutil.which("fnm") or shutil.which("fnm.exe")
    if not fnm:
        winget_link = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "fnm.exe"
        if winget_link.exists():
            fnm = str(winget_link)
    if not fnm:
        return

    try:
        proc = subprocess.run(
            [fnm, "env", "--shell", "cmd"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception as exc:
        logger.debug("Arac surum/erisim kontrolu calistirilamadi: %s", exc)
        return

    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line.upper().startswith("SET ") or "=" not in line:
            continue
        key, value = line[4:].split("=", 1)
        if key:
            os.environ[key] = value


WINDOWS_RUNNABLE_SUFFIXES = {".exe", ".com", ".bat", ".cmd"}


def clean_executable_path(value: str | os.PathLike[str] | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text or None


def _windows_path_has_separator(value: str) -> bool:
    return "\\" in value or "/" in value or (len(value) > 1 and value[1] == ":")


def gemini_backend() -> str:
    raw = os.environ.get("MAESTRO_GEMINI_BACKEND", DEFAULT_GEMINI_BACKEND).strip().lower()
    return GEMINI_BACKEND_ALIASES.get(raw, DEFAULT_GEMINI_BACKEND)


def _format_duration_seconds(seconds: int) -> str:
    return f"{max(1, int(seconds))}s"


def agent_command_template(agent: str, stage: dict[str, Any] | None = None) -> list[str]:
    if agent not in AGENT_COMMANDS:
        raise WorkflowError(f"Bilinmeyen ajan: {agent}")

    base = AGENT_COMMANDS[agent]
    if agent != "gemini" or not base or base[0] != "gemini" or gemini_backend() != "antigravity":
        return list(base)

    timeout = WF.DEFAULT_TIMEOUT
    if stage and isinstance(stage.get("timeout"), int):
        timeout = int(stage["timeout"])

    cmd = [
        "agy",
        "--dangerously-skip-permissions",
        "--print-timeout",
        _format_duration_seconds(timeout),
    ]
    model = os.environ.get("MAESTRO_ANTIGRAVITY_MODEL", "").strip()
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["-p", "{prompt}"])
    return cmd


def agent_command_label(agent: str) -> str:
    if agent == "gemini" and gemini_backend() == "antigravity":
        return "gemini -> agy -p (Antigravity CLI)"
    if agent == "gemini":
        return "gemini -p"
    if agent == "codex":
        return "codex exec"
    if agent == "claude":
        return "claude -p"
    return agent


def expected_agent_commands_label() -> str:
    return ", ".join(agent_command_label(agent) for agent in ("codex", "gemini", "claude"))


def is_antigravity_gemini_stage(stage: dict[str, Any]) -> bool:
    agent = stage.get("agent")
    if agent != "gemini" or gemini_backend() != "antigravity":
        return False
    try:
        template = agent_command_template("gemini", stage)
    except WorkflowError:
        return False
    return bool(template and clean_executable_path(template[0]) in {"agy", "agy.exe"})


def latest_antigravity_transcript(since_epoch: float) -> Path | None:
    brain_dir = ANTIGRAVITY_CLI_DIR / "brain"
    if not brain_dir.exists():
        return None
    candidates: list[Path] = []
    for transcript in brain_dir.glob("*/.system_generated/logs/transcript.jsonl"):
        try:
            if transcript.stat().st_mtime >= since_epoch - 2:
                candidates.append(transcript)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_antigravity_transcript_summary(transcript: Path, limit: int = 8000) -> str:
    rows: list[str] = []
    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        item_type = str(item.get("type") or "")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if item_type not in {"PLANNER_RESPONSE", "CODE_ACTION", "GENERIC"}:
            continue
        clean = content.strip()
        if len(clean) > 2000:
            clean = clean[:2000].rstrip() + "..."
        rows.append(f"[Antigravity {item_type}] {clean}")

    text = "\n".join(rows).strip()
    if len(text) > limit:
        return "... Antigravity transcript kirpildi ...\n" + text[-limit:]
    return text


def _windows_cmd_referenced_targets(path: Path) -> list[Path]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    targets: list[Path] = []
    for match in re.finditer(r'"(?:%dp0%|%~dp0)\\?([^"]+)"', text, flags=re.IGNORECASE):
        rel = match.group(1).lstrip("\\/")
        if rel:
            targets.append(path.parent / rel)
    return targets


def _windows_command_candidate_is_usable(candidate: str) -> bool:
    clean = clean_executable_path(candidate)
    if not clean:
        return False

    path = Path(clean)
    suffix = path.suffix.lower()
    if suffix not in WINDOWS_RUNNABLE_SUFFIXES:
        return False
    if not path.exists():
        return False

    if suffix in {".bat", ".cmd"}:
        targets = _windows_cmd_referenced_targets(path)
        if targets and not any(target.exists() for target in targets):
            return False
    return True


def _iter_windows_tool_candidates(tool: str) -> list[str]:
    clean_tool = clean_executable_path(tool)
    if not clean_tool:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        clean = clean_executable_path(value)
        if not clean:
            return
        key = clean.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(clean)

    add(shutil.which(clean_tool))

    if _windows_path_has_separator(clean_tool):
        add(clean_tool)
        return candidates

    if clean_tool.lower() in {"agy", "agy.exe"}:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            add(str(Path(local_app_data) / "agy" / "bin" / "agy.exe"))

    try:
        proc = subprocess.run(
            ["where.exe", clean_tool],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception as exc:
        logger.debug("Windows arac adaylari okunamadi (%s): %s", clean_tool, exc)
        return candidates

    for line in proc.stdout.splitlines():
        add(line)
    return candidates


def resolve_tool(tool: str) -> str | None:
    load_fnm_environment()
    clean_tool = clean_executable_path(tool)
    if not clean_tool:
        return None

    if os.name == "nt":
        for candidate in _iter_windows_tool_candidates(clean_tool):
            if _windows_command_candidate_is_usable(candidate):
                return clean_executable_path(candidate)
        return None

    return shutil.which(clean_tool)


def validate_workflow(stages: Any | None = None) -> None:
    stages = WF.STAGES if stages is None else stages
    if not isinstance(stages, list) or not stages:
        raise WorkflowError("STAGES boş olmayan bir liste olmalı.")

    for idx, stage in enumerate(stages, 1):
        if not isinstance(stage, dict):
            raise WorkflowError(f"{idx}. adım sözlük (dict) olmalı.")

        for key in ("name", "agent", "prompt"):
            if key not in stage:
                raise WorkflowError(f"{idx}. adımda zorunlu alan eksik: {key}")
            if not isinstance(stage[key], str) or not stage[key].strip():
                raise WorkflowError(f"{idx}. adımda '{key}' boş olmayan metin olmalı.")

        agent = stage["agent"]
        if agent not in AGENT_COMMANDS:
            known = ", ".join(AGENT_COMMANDS)
            raise WorkflowError(f"{idx}. adımda bilinmeyen ajan: {agent}. Geçerli ajanlar: {known}")

        for key in ("reads", "writes"):
            if key not in stage:
                continue
            if not isinstance(stage[key], list) or not all(isinstance(x, str) for x in stage[key]):
                raise WorkflowError(f"{idx}. adımda '{key}' metin listesi olmalı.")

        if "checkpoint" in stage and not isinstance(stage["checkpoint"], bool):
            raise WorkflowError(f"{idx}. adımda 'checkpoint' True/False olmalı.")

        if "fallback_agent" in stage:
            fallback = stage["fallback_agent"]
            if not isinstance(fallback, str) or fallback not in AGENT_COMMANDS:
                known = ", ".join(AGENT_COMMANDS)
                raise WorkflowError(f"{idx}. adımda 'fallback_agent' geçerli ajan olmalı: {known}")

        if "timeout" in stage:
            timeout = stage["timeout"]
            if not isinstance(timeout, int) or timeout <= 0:
                raise WorkflowError(f"{idx}. adımda 'timeout' pozitif tam sayı olmalı.")


def build_command(
    stage: dict[str, Any],
    *,
    idx: int | None = None,
    total: int | None = None,
    stages: list[dict[str, Any]] | None = None,
    project_dir: str | os.PathLike[str] | None = None,
) -> list[str]:
    agent = stage["agent"]
    if agent not in AGENT_COMMANDS:
        raise WorkflowError(f"Bilinmeyen ajan: {agent}")
    prompt = normalize_prompt_for_cli(
        build_stage_prompt(stage, idx=idx, total=total, stages=stages, project_dir=project_dir)
    )
    template = agent_command_template(agent, stage)
    return [part.replace("{prompt}", prompt) for part in template]


def resolve_command(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    resolved = resolve_tool(cmd[0])
    if resolved:
        return [resolved, *cmd[1:]]
    return cmd


def find_tool(tool: str) -> str | None:
    if tool in AGENT_COMMANDS:
        template = agent_command_template(tool)
        if template:
            return resolve_tool(template[0])
    return resolve_tool(tool)


def missing_required_tools(stages: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for stage in stages:
        for key in ("agent", "fallback_agent"):
            agent = stage.get(key)
            if isinstance(agent, str) and agent in AGENT_COMMANDS and find_tool(agent) is None and agent not in missing:
                missing.append(agent)
    return missing


def workflow_uses_request(stages: list[dict[str, Any]]) -> bool:
    for stage in stages:
        if REQUEST_FILE in stage.get("reads", []):
            return True
        if REQUEST_FILE in stage.get("prompt", ""):
            return True
    return False


def is_gemini_unsupported_auth(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in GEMINI_UNSUPPORTED_MARKERS)


def is_claude_limit_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CLAUDE_LIMIT_MARKERS)


def fallback_agent_for(stage: dict[str, Any], output_text: str) -> str | None:
    agent = stage.get("agent")
    should_fallback = False
    if agent == "gemini":
        should_fallback = is_gemini_unsupported_auth(output_text)
    elif agent == "claude":
        should_fallback = is_claude_limit_error(output_text)
    elif agent == "codex":
        should_fallback = is_usage_limit_error(output_text)
    if not should_fallback:
        return None
    fallback = stage.get("fallback_agent") or DEFAULT_FALLBACK_AGENTS.get(agent)
    if isinstance(fallback, str) and fallback in AGENT_COMMANDS and fallback != agent:
        return fallback
    return None


def with_fallback_agent(stage: dict[str, Any], fallback_agent: str) -> dict[str, Any]:
    fallback_stage = dict(stage)
    original_agent = stage.get("agent", "?")
    fallback_stage["agent"] = fallback_agent
    fallback_stage["prompt"] = (
        f"NOT: Bu adım normalde {original_agent} ile çalışacaktı; ancak {original_agent} "
        "hata veya limit nedeniyle tamamlayamadi. Ayni gorevi sen devral ve tamamla. "
        f"{stage['prompt']}"
    )
    return fallback_stage


def read_tail(path: str | os.PathLike[str], limit: int = 12000) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def check_inputs(project_dir: str | os.PathLike[str], stage: dict[str, Any]) -> list[str]:
    missing = []
    for f in stage.get("reads", []):
        if not (Path(project_dir) / f).exists():
            missing.append(f)
    return missing


def verify_outputs(project_dir: str | os.PathLike[str], stage: dict[str, Any]) -> list[str]:
    missing = []
    for f in stage.get("writes", []):
        if not (Path(project_dir) / f).exists():
            missing.append(f)
    return missing


# NOT: infer_completed_from_outputs'un onek-guvenli TEK tanimi yukaridadir.
# (Ikinci, bitisik-olmayan liste dondurebilen kopya kaldirildi: resume mantigi
# len(completed)+1 varsayimiyla calistigi icin [1,3] gibi sonuc adim atlatirdi.)
def repair_state_from_outputs(project_dir: str | os.PathLike[str], stages: list[dict[str, Any]]) -> dict[str, Any]:
    completed = infer_completed_from_outputs(project_dir, stages)
    state = load_state(project_dir, warn=False)
    state["completed"] = completed
    save_state(project_dir, state)
    return state


def score_stage_quality(
    project_dir: str | os.PathLike[str],
    stage: dict[str, Any],
    idx: int,
    output_text: str = "",
    test_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tamamlanan bir ajan adiminin kalitesini 0-100 arasi puanlar."""
    root = Path(project_dir)
    score = 0
    details: list[str] = []

    # 1) Beklenen dosyalar olustu (25 puan)
    writes = stage.get("writes", [])
    if writes:
        existing = [f for f in writes if (root / f).exists()]
        if len(existing) == len(writes):
            score += 25
            details.append("Tum beklenen ciktilar mevcut (+25)")
        elif existing:
            partial = int(25 * len(existing) / len(writes))
            score += partial
            details.append(f"{len(existing)}/{len(writes)} cikti mevcut (+{partial})")
        else:
            details.append("Hicbir cikti olusturulmamis (+0)")
    else:
        score += 25
        details.append("Yazilacak cikti tanimlanmamis, tam puan (+25)")

    # 2) Dosyalar bos degil (20 puan)
    if writes:
        non_empty = []
        for f in writes:
            path = root / f
            if path.exists() and path.stat().st_size > 10:
                non_empty.append(f)
        if non_empty and len(non_empty) == len(writes):
            score += 20
            details.append("Tum cikti dosyalari dolu (+20)")
        elif non_empty:
            partial = int(20 * len(non_empty) / len(writes))
            score += partial
            details.append(f"{len(non_empty)}/{len(writes)} dosya dolu (+{partial})")
        else:
            details.append("Cikti dosyalari bos (+0)")
    else:
        score += 20
        details.append("Yazilacak dosya yok, tam puan (+20)")

    # 3) Sohbet devir notu var (15 puan)
    chat_text = ""
    try:
        cp = chat_path(project_dir)
        if cp.exists():
            chat_text = cp.read_text(encoding="utf-8", errors="replace")[-4000:]
    except Exception:
        pass
    agent = stage.get("agent", "").upper()
    stage_name = stage.get("name", "")
    if agent and (agent in chat_text or stage_name.lower() in chat_text.lower()):
        score += 15
        details.append("Sohbet dosyasinda devir notu var (+15)")
    else:
        details.append("Sohbet devir notu bulunamadi (+0)")

    # 4) Sonraki ajana net talimat (15 puan)
    has_next_instruction = False
    for f in writes:
        path = root / f
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:3000]
                if any(kw in text.lower() for kw in ("siradaki", "sonraki", "next", "talimat", "yapilacak", "todo")):
                    has_next_instruction = True
                    break
            except Exception:
                pass
    if has_next_instruction:
        score += 15
        details.append("Ciktida sonraki adim talimati var (+15)")
    else:
        details.append("Sonraki adim talimati bulunamadi (+0)")

    # 5) Test/smoke sonucu basarili (15 puan)
    if test_result:
        if test_result.get("status") == "success":
            score += 15
            details.append("Smoke test basarili (+15)")
        else:
            details.append("Smoke test basarisiz (+0)")
    else:
        score += 8
        details.append("Smoke test calistirilmadi, kismi puan (+8)")

    # 6) Hata veya eksik cikti yok (10 puan)
    output_lower = (output_text or "").lower()
    has_error = any(kw in output_lower for kw in ("error", "hata", "exception", "traceback", "failed"))
    if not has_error:
        score += 10
        details.append("Ciktida hata gostergesi yok (+10)")
    else:
        details.append("Ciktida hata gostergesi var (+0)")

    score = max(0, min(100, score))
    if score >= 90:
        label = "guvenli"
    elif score >= 70:
        label = "kabul edilebilir"
    elif score >= 40:
        label = "kontrol gerekli"
    else:
        label = "basarisiz"

    result = {
        "stage_index": idx,
        "stage_name": stage.get("name", ""),
        "agent": stage.get("agent", ""),
        "score": score,
        "label": label,
        "details": details,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    # Kalite raporunu kaydet
    report_path = app_data_dir(project_dir) / QUALITY_REPORT_FILE
    reports: list[dict[str, Any]] = []
    if report_path.exists():
        try:
            reports = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            reports = []
    if not isinstance(reports, list):
        reports = []
    reports.append(result)
    reports = reports[-20:]  # Son 20 kaydi tut
    report_path.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")

    return result


def load_quality_scores(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Kayitli kalite skorlarini yukler."""
    path = app_data_dir(project_dir) / QUALITY_REPORT_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def agent_for_role(role: str, project_type: str = "") -> str:
    """Rol isminden uygun ajan adini doner."""
    role_def = AGENT_ROLES.get(role)
    if not role_def:
        return "gemini"
    return role_def["agent"]


def prompt_profile_for_role(role: str) -> str:
    """Rol icin prompt on ekini doner."""
    role_def = AGENT_ROLES.get(role)
    if not role_def:
        return ""
    return role_def.get("prompt_prefix", "")


def create_delivery_package(
    project_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Proje klasorunden temiz bir teslim zip paketi olusturur."""
    import zipfile

    root = Path(project_dir).resolve()
    packages_root = root / PACKAGES_DIR
    packages_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"teslim_{ts}.zip"
    if output_dir:
        zip_path = Path(output_dir) / zip_name
    else:
        zip_path = packages_root / zip_name

    checks: list[dict[str, str]] = []

    # README kontrolu
    has_readme = any((root / name).exists() for name in ("README.md", "readme.md", "README.txt"))
    checks.append({"name": "README", "status": "ok" if has_readme else "eksik"})

    # Manifest kontrolu
    has_manifest = any(
        (root / name).exists()
        for name in ("requirements.txt", "package.json", "pyproject.toml", "setup.py", "Cargo.toml")
    )
    checks.append({"name": "Proje manifest", "status": "ok" if has_manifest else "eksik"})

    # Test raporu kontrolu
    test_report_path = root / "test_raporu.json"
    test_status = "yok"
    if test_report_path.exists():
        try:
            report = json.loads(test_report_path.read_text(encoding="utf-8"))
            test_status = report.get("status", "bilinmiyor")
        except Exception:
            test_status = "okunamadi"
    checks.append({"name": "Test raporu", "status": test_status})

    # Zip olustur
    file_count = 0
    total_size = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            # Skip dirs
            parts = rel.parts
            if any(part in PACKAGE_SKIP_DIRS for part in parts[:-1]):
                continue
            # Skip top-level skip dirs
            if parts[0] in PACKAGE_SKIP_DIRS:
                continue
            # Buyuk dosyalari atla (50MB)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 50 * 1024 * 1024:
                continue
            zf.write(path, str(rel).replace("\\", "/"))
            file_count += 1
            total_size += size

    zip_size = zip_path.stat().st_size

    manifest = {
        "package_name": zip_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(root),
        "file_count": file_count,
        "total_size": total_size,
        "zip_size": zip_size,
        "zip_path": str(zip_path),
        "checks": checks,
    }

    manifest_path = zip_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return manifest


def list_delivery_packages(project_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Onceki teslim paketlerini listeler."""
    packages_root = Path(project_dir).resolve() / PACKAGES_DIR
    if not packages_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for meta_path in sorted(packages_root.glob("teslim_*.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                rows.append(meta)
        except Exception:
            continue
    return rows[:10]


def stage_output_status(project_dir: str | os.PathLike[str], stage: dict[str, Any]) -> dict[str, Any]:
    expected = stage.get("writes", [])
    missing = []
    produced = []
    for f in expected:
        if (Path(project_dir) / f).exists():
            produced.append(f)
        else:
            missing.append(f)
    return {
        "expected": expected,
        "missing": missing,
        "produced": produced
    }


def process_info(pid: int | None) -> dict[str, Any]:
    info = {"cpu_percent": 0.0, "memory_mb": 0.0, "status": "unknown"}
    if not pid:
        return info
    try:
        import psutil
        proc = psutil.Process(pid)
        # Using a very small interval to get an instant reading without blocking much
        info["cpu_percent"] = proc.cpu_percent(interval=0.0)
        info["memory_mb"] = proc.memory_info().rss / (1024 * 1024)
        info["status"] = proc.status()
    except Exception:
        pass
    return info


ANTIGRAVITY_OUTPUT_EXIT_GRACE_SECONDS = 5.0


def antigravity_outputs_ready(project_dir: str | os.PathLike[str], stage: dict[str, Any]) -> bool:
    return is_antigravity_gemini_stage(stage) and bool(stage.get("writes")) and not verify_outputs(project_dir, stage)


def process_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def process_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
                    if env.get(name):
                        continue
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value:
                        env[name] = value
        except Exception as exc:
            logger.debug("Ek ortam degiskenleri okunamadi: %s", exc)
    return env


def kill_process_tree(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None or proc.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as exc:
            logger.debug("taskkill basarisiz, proc.kill deneniyor: %s", exc)
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        except Exception as exc:
            logger.debug("SIGTERM grubu basarisiz, SIGKILL deneniyor: %s", exc)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    try:
        proc.wait(timeout=3)
    except Exception as exc:
        logger.debug("Surec sonlandirma sonrasi bekleme basarisiz: %s", exc)


def run_stage(
    project_dir: str | os.PathLike[str],
    stage: dict[str, Any],
    idx: int,
    total: int,
    dry_run: bool,
    log_path: str | os.PathLike[str],
    stages: list[dict[str, Any]] | None = None,
    fallback_used: bool = False,
) -> bool:
    name = stage["name"]
    agent = stage["agent"]
    banner(f"ADIM {idx}/{total}: {name}  [{agent.upper()}]")
    if not dry_run:
        ensure_chat_file(project_dir)
        append_chat_entry(
            project_dir,
            "Orkestra",
            (
                f"Sira {idx}/{total}: {stage_ref(stage, idx)} basliyor.\n"
                f"- Bu adimin gorevi: {stage['prompt'][:220]}{'...' if len(stage['prompt']) > 220 else ''}\n"
                f"- Sonraki devir: {next_stage_ref(stages, idx)}"
            ),
        )

    missing_in = check_inputs(project_dir, stage)
    if missing_in and not dry_run:
        log(f"  ! Bu adım için gereken dosyalar yok: {', '.join(missing_in)}", C.RED)
        log("    Önceki adım bunları üretmemiş olabilir. Duruyorum.", C.RED)
        append_chat_entry(
            project_dir,
            "Orkestra",
            f"{stage_ref(stage, idx)} baslayamadi. Eksik girdiler: {', '.join(missing_in)}",
        )
        return False
    if missing_in and dry_run:
        log(f"  (dry-run) Çalışsaydı şu dosyaları okuyacaktı: {', '.join(missing_in)}", C.DIM)

    cmd = build_command(stage, idx=idx, total=total, stages=stages, project_dir=project_dir)
    preview = " ".join(cmd[:2])
    run_cmd = resolve_command(cmd)
    log(f"  Komut: {C.DIM}{preview} ... (cwd={project_dir}){C.RESET}", C.BLUE)
    short_prompt = stage["prompt"][:90] + ("..." if len(stage["prompt"]) > 90 else "")
    log(f"  Görev: {short_prompt}", C.DIM)

    if dry_run:
        log("  [DRY-RUN] Çalıştırılmadı.", C.YELLOW)
        return True

    timeout = int(stage.get("timeout", WF.DEFAULT_TIMEOUT))
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    # Surec dongusu TEK kaynak: runner.run_agent_stage (gui/web ile ayni).
    # CLI boylece sessizlik (stuck) tespiti, cikti-zarafeti, akis-ici limit
    # yakalama ve stage_started/finished olay kayitlarini da kazanir.
    from runner import run_agent_stage  # dongusel import olmasin diye gec

    with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
        lf.write(f"\n\n{'=' * 70}\nADIM {idx}: {name} [{agent}] @ {datetime.now()}\n{'=' * 70}\n")
        lf.flush()

        def to_log(line: str) -> None:
            # Ajan ciktisi eskisi gibi calistirma log dosyasina akar.
            lf.write(line + "\n")
            lf.flush()

        ok, elapsed_f, reason, output_text = run_agent_stage(
            stage, idx, total, stages or [stage], project_dir,
            stop_event=threading.Event(),
            log=to_log,
        )

    elapsed = int(elapsed_f)
    if reason == "not-found":
        log(f"  ! '{agent}' komutu bulunamadı. Bu araç kurulu mu / PATH'te mi?", C.RED)
        append_chat_entry(
            project_dir,
            "Orkestra",
            f"{stage_ref(stage, idx)} calisamadi. '{agent}' komutu PATH icinde bulunamadi.",
        )
        return False
    if reason == "timeout":
        log(f"  ! Zaman aşımı ({timeout}sn). Adım durduruldu.", C.RED)
        append_chat_entry(
            project_dir,
            "Orkestra",
            f"{stage_ref(stage, idx)} zaman asimina ugradi ({timeout}sn). Surec agaci durduruldu.",
        )
        return False
    if reason == "stuck":
        log("  ! Ajan uzun süre sessiz kaldı; süreç durduruldu. Detay: " + str(log_path), C.RED)
        append_chat_entry(
            project_dir,
            "Orkestra",
            f"{stage_ref(stage, idx)} uzun sure cikti uretmeyince durduruldu (stuck).",
        )
        return False
    if ok and "cikti urettikten sonra kapanmadi" in output_text:
        log("  Beklenen ciktilar uretildi; kapanmayan surec tamamlandi sayildi.", C.YELLOW)
    if not ok:
        output_text = output_text or read_tail(log_path)
        fallback = None if fallback_used else fallback_agent_for(stage, output_text)
        if fallback and find_tool(fallback):
            log(
                f"  ! {agent} hata verdi; ayni adim {fallback.upper()} ile devraliniyor.",
                C.YELLOW,
            )
            append_chat_entry(
                project_dir,
                "Orkestra",
                f"{stage_ref(stage, idx)} {agent} ile tamamlanamadi. Ayni gorev {fallback} ajanina devrediliyor.",
            )
            return run_stage(
                project_dir,
                with_fallback_agent(stage, fallback),
                idx,
                total,
                dry_run,
                log_path,
                stages=stages,
                fallback_used=True,
            )
        log(f"  ! Ajan hata döndü ({reason}). Detay: {log_path}", C.RED)
        append_chat_entry(
            project_dir,
            agent.upper(),
            f"{stage_ref(stage, idx)} hata ile bitti ({reason}). Detay log: {log_path}",
        )
        return False

    missing_out = verify_outputs(project_dir, stage)
    if missing_out:
        log(f"  ! Beklenen çıktı dosyaları oluşmamış: {', '.join(missing_out)}", C.YELLOW)
        log(f"    Loga bak: {log_path}", C.YELLOW)
        append_chat_entry(
            project_dir,
            agent.upper(),
            f"{stage_ref(stage, idx)} tamamlandi gibi gorundu ama beklenen ciktılar eksik: {', '.join(missing_out)}",
        )
        return False

    produced = ", ".join(stage.get("writes", [])) or "-"
    log(f"  ✓ Tamam ({elapsed}sn). Üretilen: {produced}", C.GREEN)
    next_ref = next_stage_ref(stages, idx)
    append_chat_entry(
        project_dir,
        agent.upper(),
        (
            f"{stage_ref(stage, idx)} tamamlandi.\n"
            f"- Sure: {elapsed}sn\n"
            f"- Uretilen/beklenen ciktılar: {produced}\n"
            f"- Kanka is sende: {next_ref}\n"
            "- Checkpoint aciksa kullanici onayi geldikten sonra devam edilecek."
        ),
    )
    return True


def ask_checkpoint(stage_name: str) -> str:
    log(f"\n  ⏸  Checkpoint: '{stage_name}' bitti.", C.MAGENTA + C.BOLD)
    log("     [Enter]=devam   r=bu adımı tekrarla   q=çık", C.MAGENTA)
    try:
        ans = input("     > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "quit"
    if ans == "q":
        return "quit"
    if ans == "r":
        return "retry"
    return "continue"


def main() -> None:
    enable_ansi()

    ap = argparse.ArgumentParser(description="AI Orkestra - 3 ajanı sırayla çalıştır")
    ap.add_argument("--resume", action="store_true", help="Kaldığı yerden devam et")
    ap.add_argument("--from", dest="from_idx", type=int, default=1, help="Bu adımdan başla (1'den)")
    ap.add_argument("--yes", "-y", action="store_true", help="Checkpoint'lerde sorma, tam otomatik")
    ap.add_argument("--dry-run", action="store_true", help="Çalıştırma, sadece ne yapacağını göster")
    ap.add_argument("--request", help=f"Kullanici ana istegini {REQUEST_FILE} dosyasina kaydet")
    ap.add_argument("--compare", help="Ayni gorevi kurulu ajanlara ayri ayri yaptirip kiyas raporu uret (DIKKAT: token x ajan sayisi)")
    ap.add_argument("--compare-writes", default="", help="--compare icin beklenen cikti dosyalari (virgullu)")
    args = ap.parse_args()

    if args.compare:
        project_dir = resolve_project_dir()
        project_dir.mkdir(parents=True, exist_ok=True)
        setup_logging(project_dir / LOG_DIR)
        writes = [w.strip() for w in args.compare_writes.split(",") if w.strip()]
        try:
            sonuc = run_agent_comparison(project_dir, args.compare, writes=writes or None, log=log)
        except KeyboardInterrupt:
            log("\nKarsilastirma kullanici tarafindan durduruldu; calisan ajan sureci kapatildi.", C.YELLOW)
            return
        log(f"\nKarsilastirma raporu: {sonuc['report']}", C.GREEN)
        return

    try:
        validate_workflow(WF.STAGES)
    except WorkflowError as exc:
        log(f"Workflow hatası: {exc}", C.RED + C.BOLD)
        sys.exit(2)

    project_dir = resolve_project_dir()
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / LOG_DIR).mkdir(exist_ok=True)
    setup_logging(project_dir / LOG_DIR)  # tani amacli dosya logu (maestro.log)
    logger.info("Orkestra basladi: proje=%s args=%s", project_dir, sys.argv[1:])
    log_path = project_dir / LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"

    if args.request:
        save_user_request(project_dir, args.request)
        append_chat_entry(project_dir, "Kullanici", f"Ana is istegi kaydedildi:\n{args.request}")

    stages = WF.STAGES
    total = len(stages)
    if args.from_idx < 1 or args.from_idx > total:
        log(f"--from değeri 1 ile {total} arasında olmalı.", C.RED)
        sys.exit(2)

    state = load_state(project_dir, warn=True)
    state["completed"] = [x for x in state.get("completed", []) if x <= total]

    banner(f"AI ORKESTRA  ·  proje: {project_dir}  ·  {total} adım")
    if args.dry_run:
        log("DRY-RUN modu: hiçbir ajan çalıştırılmayacak.\n", C.YELLOW)

    start_idx = args.from_idx
    if args.resume and state.get("completed"):
        start_idx = max(start_idx, len(state["completed"]) + 1)
        log(f"Resume: {len(state['completed'])} adım zaten bitmiş, {start_idx}. adımdan devam.\n", C.CYAN)

    if not args.dry_run:
        if workflow_uses_request(stages) and not read_user_request(project_dir):
            log("Kullanici istegi yok. Once GUI'deki Is Istegi alanini doldur veya --request kullan.", C.RED)
            log(f"Beklenen dosya: {project_dir / REQUEST_FILE}", C.DIM)
            sys.exit(2)
        missing_tools = missing_required_tools(stages[start_idx - 1:])
        if missing_tools:
            log("Eksik ajan komutları var; gerçek akış başlatılmadı.", C.RED + C.BOLD)
            log(f"Kurulması gerekenler: {', '.join(missing_tools)}", C.RED)
            log(f"Beklenen gercek komutlar: {expected_agent_commands_label()}", C.DIM)
            sys.exit(2)

    i = start_idx
    while i <= total:
        stage = stages[i - 1]
        ok = run_stage(project_dir, stage, i, total, args.dry_run, log_path, stages=stages)

        if not ok:
            log(
                f"\n✕ {i}. adımda durdu. Sorunu gider, sonra: "
                f"python orkestra.py --from {i}",
                C.RED + C.BOLD,
            )
            sys.exit(1)

        if not args.dry_run:
            if i not in state["completed"]:
                state["completed"].append(i)
            save_state(project_dir, state)

        if not args.dry_run and not args.yes and stage.get("checkpoint", False) and i < total:
            decision = ask_checkpoint(stage["name"])
            if decision == "quit":
                log("\nÇıkıldı. Devam için: python orkestra.py --resume", C.YELLOW)
                sys.exit(0)
            if decision == "retry":
                state["completed"] = [x for x in state["completed"] if x != i]
                save_state(project_dir, state)
                continue

        i += 1

    banner("✓ TÜM AKIŞ TAMAMLANDI")
    log(f"Sonuçlar: {project_dir}", C.GREEN)
    log(f"Loglar:   {log_path}", C.DIM)


if __name__ == "__main__":
    main()
