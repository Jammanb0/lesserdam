"""EXE에 포함된 라이선스 원문을 읽는 창."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


def show_licenses(parent) -> None:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    win = tk.Toplevel(parent)
    win.title("오픈소스 고지")
    win.geometry("950x650")
    win.transient(parent)
    files = [root / "THIRD_PARTY_NOTICES.md", root / "LICENSE"]
    files.extend(sorted(p for p in (root / "licenses").rglob("*") if p.is_file() and p.suffix != ".json"))
    choice = ttk.Combobox(win, state="readonly", values=[str(p.relative_to(root)) for p in files])
    choice.pack(fill="x", padx=12, pady=12)
    text = ScrolledText(win, wrap="word", padx=12, pady=12)
    text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def load(_=None):
        path = files[choice.current()]
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = "고지 파일을 찾지 못했어요. 배포 파일의 licenses 폴더를 확인해 주세요."
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", content)
        text.configure(state="disabled")

    choice.bind("<<ComboboxSelected>>", load)
    choice.current(0)
    load()
