"""화면 여러 곳에서 같이 쓰는 것"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from .. import APP_TITLE, core, office

TITLE = APP_TITLE
HINT = "#6b6b6b"
BAD = "#b00020"
WARN_BG = "#fff1d6"   # 미리 보기에서 파일이 빠진 줄
SKIP_FG = "#9a9a9a"   # 만들지 않는 줄

IMAGE_PATTERN = " ".join(f"*{ext}" for ext in sorted(core.IMAGE_EXTS))
DOC_PATTERN = " ".join(f"*{ext}" for ext in sorted(office.DOC_EXTS))
TURN_TEXT = {0: "", 90: "↻ 90°", 180: "↻ 180°", 270: "↺ 90°"}


def key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def short_folder(folder: Path) -> str:
    """긴 경로는 끝쪽 폴더 이름이 보이게 줄인다 (전체 경로는 줄을 고르면 아래 상태 줄에)"""
    text = str(folder)
    if len(text) > 40 and len(folder.parts) > 3:
        return "…\\" + "\\".join(folder.parts[-2:])
    return text


def size_text(size: int | None) -> str:
    if size is None:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def date_text(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def doc_support_text() -> str:
    """이 PC에서 바꿀 수 있는 문서 종류 안내"""
    have = [info.label for kind, info in office.APPS.items() if office.installed(kind)]
    missing = [info.label for kind, info in office.APPS.items() if not office.installed(kind)]
    text = "이미지" + ("·" + "·".join(have) if have else "")
    if missing:
        text += f" (이 PC에 {'·'.join(missing)} 프로그램이 없어서 그 파일은 못 바꿔요)"
    return text


def reveal(path: Path) -> None:
    """탐색기에서 파일을 고른 채로 폴더를 연다"""
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])  # noqa: S603, S607
    except OSError:
        pass


def options_row(box, row: int, label: str, var, choices, column: int = 0) -> list[ttk.Radiobutton]:
    """'이름  ○ 선택 ○ 선택' 한 줄"""
    ttk.Label(box, text=label).grid(row=row, column=column, sticky="w", pady=2)
    out = []
    for i, (value, text) in enumerate(choices, start=1):
        r = ttk.Radiobutton(box, text=text, value=value, variable=var)
        r.grid(row=row, column=column + i, sticky="w", padx=(10, 0), pady=2)
        out.append(r)
    return out


def bad_text(entries, limit: int = 8) -> str:
    lines = "\n".join(f"· {e.path.name} — {e.error}" for e in entries[:limit])
    if len(entries) > limit:
        lines += f"\n… 외 {len(entries) - limit}개"
    return f"열 수 없는 파일이 {len(entries)}개 있어요 (목록의 빨간 줄).\n{lines}"


def listing(lines: list[str], limit: int = 8) -> str:
    text = "\n".join(f"· {line}" for line in lines[:limit])
    if len(lines) > limit:
        text += f"\n… 외 {len(lines) - limit}개"
    return text
