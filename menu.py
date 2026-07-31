#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Orkestra - Terminal kontrol menüsü.
Çalıştır: python menu.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import workflow as WF
from orkestra import (
    CHAT_FILE,
    LOG_DIR,
    REQUEST_FILE,
    WorkflowError,
    enable_ansi,
    find_tool,
    load_state,
    read_user_request,
    resolve_project_dir,
    validate_workflow,
)
from logging_config import get_logger, setup_logging

logger = get_logger("menu")


BASE_DIR = Path(__file__).resolve().parent


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


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def cprint(msg: str, color: str = "") -> None:
    print(f"{color}{msg}{C.RESET}")


def project_path() -> Path:
    return resolve_project_dir()


def tool_status() -> str:
    out = []
    for tool in ("codex", "gemini", "claude"):
        if find_tool(tool):
            out.append(f"{C.GREEN}●{C.RESET} {tool}")
        else:
            out.append(f"{C.RED}○{C.RESET} {tool}")
    return "   ".join(out)


def state() -> dict:
    return load_state(project_path())


def stage_list() -> str:
    try:
        validate_workflow(WF.STAGES)
    except WorkflowError as exc:
        return f"   {C.RED}Workflow hatası: {exc}{C.RESET}"

    done = set(state().get("completed", []))
    agent_color = {"codex": C.GREEN, "gemini": C.BLUE, "claude": C.MAGENTA}
    lines = []
    for i, stage in enumerate(WF.STAGES, 1):
        mark = f"{C.GREEN}✓{C.RESET}" if i in done else f"{C.DIM}·{C.RESET}"
        col = agent_color.get(stage["agent"], "")
        cp = f"{C.YELLOW}⏸{C.RESET}" if stage.get("checkpoint") else " "
        lines.append(f"   {mark} {i}. {stage['name']:<20} {col}[{stage['agent']}]{C.RESET} {cp}")
    return "\n".join(lines)


def header() -> None:
    clear()
    width = 56
    cprint("╔" + "═" * width + "╗", C.CYAN)
    cprint("║" + "AI ORKESTRA  ·  Kontrol Menüsü".center(width) + "║", C.CYAN + C.BOLD)
    cprint("╚" + "═" * width + "╝", C.CYAN)
    print()
    cprint(f"  Proje:    {project_path()}", C.DIM)
    print(f"  Araçlar:  {tool_status()}")
    st = state()
    if st.get("last_run"):
        cprint(
            f"  Son çalışma: {st['last_run']}  "
            f"({len(st.get('completed', []))}/{len(WF.STAGES)} adım bitti)",
            C.DIM,
        )
    print()
    cprint("  ── Adımlar ──  ( ✓=bitti  ·=bekliyor  ⏸=checkpoint )", C.DIM)
    print(stage_list())
    print()


def run_orkestra(extra_args: list[str]) -> None:
    cmd = [sys.executable, str(BASE_DIR / "orkestra.py")] + extra_args
    print()
    cprint("  ── Çalışıyor ──  (durdurmak için Ctrl+C)\n", C.CYAN)
    try:
        subprocess.run(cmd, cwd=BASE_DIR, check=False)
    except KeyboardInterrupt:
        cprint("\n  Durduruldu.", C.YELLOW)
    pause()


def pick_step() -> int | None:
    print()
    try:
        validate_workflow(WF.STAGES)
        raw = input(f"  Hangi adımdan başlayayım? (1-{len(WF.STAGES)}): ").strip()
        n = int(raw)
        if 1 <= n <= len(WF.STAGES):
            return n
    except (ValueError, EOFError, KeyboardInterrupt, WorkflowError):
        pass
    cprint("  Geçersiz adım.", C.RED)
    pause()
    return None


def show_workflow() -> None:
    header()
    cprint("  ── İş Akışı Detayı ──\n", C.BOLD)
    try:
        validate_workflow(WF.STAGES)
    except WorkflowError as exc:
        cprint(f"  Workflow hatası: {exc}", C.RED)
        pause()
        return

    for i, stage in enumerate(WF.STAGES, 1):
        cprint(f"  {i}. {stage['name']}  [{stage['agent']}]", C.BOLD)
        cprint(f"     Görev: {stage['prompt']}", C.DIM)
        if stage.get("reads"):
            cprint(f"     Okur:  {', '.join(stage['reads'])}", C.DIM)
        if stage.get("writes"):
            cprint(f"     Yazar: {', '.join(stage['writes'])}", C.DIM)
        print()
    cprint("  Akışı değiştirmek için workflow.py dosyasını düzenle.", C.YELLOW)
    pause()


def show_last_log() -> None:
    header()
    logdir = project_path() / "logs"
    if not logdir.exists() or not any(logdir.iterdir()):
        cprint("  Henüz log yok.", C.YELLOW)
        pause()
        return
    last = max(logdir.glob("run_*.log"), key=lambda p: p.stat().st_mtime, default=None)
    if not last:
        cprint("  Log bulunamadı.", C.YELLOW)
        pause()
        return
    cprint(f"  ── Son log: {last.name} (son 40 satır) ──\n", C.BOLD)
    lines = last.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-40:]:
        print("  " + line)
    pause()


def show_outputs() -> None:
    header()
    pdir = project_path()
    if not pdir.exists():
        cprint("  Proje klasörü henüz oluşmadı.", C.YELLOW)
        pause()
        return
    cprint(f"  ── {pdir} içindeki dosyalar ──\n", C.BOLD)
    items = sorted([p for p in pdir.iterdir() if p.name != ".orkestra_state.json"])
    if not items:
        cprint("   Henüz çıktı yok.", C.YELLOW)
    for item in items:
        tag = "/" if item.is_dir() else ""
        cprint(f"   {item.name}{tag}", C.GREEN if item.is_file() else C.BLUE)
    pause()


def show_chat() -> None:
    header()
    path = project_path() / CHAT_FILE
    if not path.exists():
        cprint("  Henüz sohbet yok. Akış başlayınca sohbet.md oluşacak.", C.YELLOW)
        pause()
        return
    cprint(f"  ── {CHAT_FILE} (son 80 satır) ──\n", C.BOLD)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-80:]:
        print("  " + line)
    pause()


def edit_request() -> None:
    header()
    pdir = project_path()
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / REQUEST_FILE
    if not path.exists():
        path.write_text("", encoding="utf-8")

    current = read_user_request(pdir)
    if current:
        cprint(f"  Mevcut {REQUEST_FILE}:", C.BOLD)
        for line in current.splitlines()[:8]:
            print("  " + line)
        if len(current.splitlines()) > 8:
            print("  ...")
        print()

    cprint(f"  {REQUEST_FILE} dosyasi editor ile aciliyor: {path}", C.CYAN)
    try:
        if os.name == "nt":
            subprocess.run(["notepad", str(path)], check=False)
        else:
            editor = os.environ.get("EDITOR", "nano")
            subprocess.run([editor, str(path)], check=False)
    except OSError as exc:
        cprint(f"  Editor acilamadi: {exc}", C.RED)
    pause()


def reset_state() -> None:
    header()
    cprint("  Durum kaydı sıfırlanacak. Dosyalar silinmez, sadece ilerleme temizlenir.", C.YELLOW)
    try:
        ans = input("  Emin misin? (e/h): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    if ans == "e":
        p = project_path() / ".orkestra_state.json"
        if p.exists():
            p.unlink()
        cprint("  ✓ Sıfırlandı. Akış baştan başlar.", C.GREEN)
    else:
        cprint("  İptal edildi.", C.DIM)
    pause()


def pause() -> None:
    print()
    try:
        input(f"  {C.DIM}[Enter ile menüye dön]{C.RESET} ")
    except (EOFError, KeyboardInterrupt):
        pass


MENU = """  Ne yapmak istersin?

  {b}1{r}) Akışı çalıştır          {d}(her checkpoint'te sana sorar){r}
  {b}2{r}) Tam otomatik çalıştır   {d}(hiç sormadan, başla-bitir){r}
  {b}3{r}) Kaldığı yerden devam    {d}(resume){r}
  {b}4{r}) Belirli adımdan başla
  {b}5{r}) Önizleme                {d}(dry-run, hiçbir şey çalıştırmaz){r}
  {b}6{r}) İş akışını göster
  {b}7{r}) Son logu göster
  {b}8{r}) Çıktı dosyalarını göster
  {b}9{r}) Sohbeti göster
  {b}10{r}) Durumu sıfırla
  {b}11{r}) İstek düzenle          {d}(ajanlara verilecek isteği yaz/düzenle){r}
  {b}0{r}) Çıkış
"""


def main() -> None:
    enable_ansi()
    setup_logging(resolve_project_dir() / LOG_DIR)  # tani amacli dosya logu (maestro.log)
    logger.info("Menu baslatildi")
    while True:
        header()
        print(MENU.format(b=C.BOLD + C.CYAN, r=C.RESET, d=C.DIM))
        try:
            choice = input("  Seçim: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "1":
            run_orkestra([])
        elif choice == "2":
            run_orkestra(["--yes"])
        elif choice == "3":
            run_orkestra(["--resume"])
        elif choice == "4":
            n = pick_step()
            if n:
                run_orkestra(["--from", str(n)])
        elif choice == "5":
            run_orkestra(["--dry-run"])
        elif choice == "6":
            show_workflow()
        elif choice == "7":
            show_last_log()
        elif choice == "8":
            show_outputs()
        elif choice == "9":
            show_chat()
        elif choice == "10":
            reset_state()
        elif choice == "11":
            edit_request()
        elif choice == "0":
            cprint("\n  Görüşürüz kanka.", C.CYAN)
            break
        else:
            cprint("  Geçersiz seçim.", C.RED)
            pause()


if __name__ == "__main__":
    main()
