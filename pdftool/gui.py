"""화면 (tkinter): ① 이미지 → PDF  ② PDF 합치기"""
from __future__ import annotations

import ctypes
import functools
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import core, dnd

TITLE = "PDF 변환 합치기"
HINT = "#6b6b6b"
BAD = "#b00020"
IMAGE_PATTERN = " ".join(f"*{ext}" for ext in sorted(core.IMAGE_EXTS))
SHIFT, CONTROL = 0x0001, 0x0004

_ids = count(1)
_cmp = ctypes.windll.shlwapi.StrCmpLogicalW
_cmp.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
_cmp.restype = ctypes.c_int
explorer_order = functools.cmp_to_key(_cmp)  # 탐색기 '이름' 정렬과 같은 순서 (2 다음에 10)

PAGE_HINTS = {
    "a4": "A4 한 장에 비율 그대로 맞춰 넣어요. 가로로 긴 이미지는 가로 A4가 돼요.",
    "original": "이미지 크기 그대로 쪽을 만들어요. (사진은 쪽이 아주 클 수 있어요)",
}
MODE_HINTS = {
    "one": "목록의 이미지를 순서대로 PDF 1개에 담아요. 저장할 파일 이름을 고르게 돼요.",
    "each": "이미지마다 같은 이름의 PDF를 만들어요 (사진1.jpg → 사진1.pdf). 저장할 폴더를 고르게 돼요.",
}


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


@dataclass
class Entry:
    path: Path
    kind: str                 # "pdf" / "image"
    pages: int | None = None  # None: 아직 세는 중
    error: str = ""           # 열 수 없으면 그 이유
    iid: str = field(default_factory=lambda: f"f{next(_ids)}")


class FileList(ttk.Frame):
    """순서를 정할 수 있는 파일 목록 (넣기 · 끌어서 순서 바꾸기 · 빼기)"""

    def __init__(self, parent, app: App, kinds: set[str], filetypes: list[tuple[str, str]], empty_text: str) -> None:
        super().__init__(parent)
        self.app = app
        self.kinds = kinds
        self.filetypes = filetypes
        self.items: list[Entry] = []
        self._drag: str | None = None
        self._dragged = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Button(top, text="파일 추가", command=self.pick_files).pack(side="left")
        ttk.Button(top, text="폴더 추가", command=self.pick_folder).pack(side="left", padx=(6, 0))
        ttk.Label(top, text="파일이나 폴더를 이 창에 끌어다 놓아도 돼요.", foreground=HINT).pack(side="left", padx=(12, 0))

        self.tree = ttk.Treeview(self, columns=("no", "name", "pages", "folder"), show="headings",
                                 selectmode="extended", height=12)
        for col, text, width, anchor, stretch in (("no", "순서", 50, "center", False),
                                                  ("name", "파일 이름", 300, "w", True),
                                                  ("pages", "쪽", 80, "center", False),
                                                  ("folder", "폴더", 280, "w", True)):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=40, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("bad", foreground=BAD)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")

        side = ttk.Frame(self)
        side.grid(row=1, column=2, sticky="ns", padx=(8, 0))
        for text, where in (("맨 위로", "top"), ("▲ 위로", "up"), ("▼ 아래로", "down"), ("맨 아래로", "bottom")):
            ttk.Button(side, text=text, command=lambda w=where: self.move(w)).pack(fill="x", pady=(0, 4))
        ttk.Button(side, text="이름순 정렬", command=self.sort_by_name).pack(fill="x", pady=(10, 0))
        ttk.Button(side, text="목록에서 빼기", command=self.remove_selected).pack(fill="x", pady=(18, 4))
        ttk.Button(side, text="모두 비우기", command=self.clear).pack(fill="x")

        bottom = ttk.Frame(self)
        bottom.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.summary = ttk.Label(bottom)
        self.summary.pack(side="left")
        ttk.Label(bottom, text="줄을 끌어서 순서를 바꿀 수 있어요 · 두 번 클릭하면 파일 열기 · Delete 키로 빼기",
                  foreground=HINT).pack(side="right")

        self.empty = tk.Label(self, text=empty_text, fg=HINT, bg="SystemWindow", justify="center")

        t = self.tree
        t.bind("<ButtonPress-1>", self._press)
        t.bind("<B1-Motion>", self._motion)
        t.bind("<ButtonRelease-1>", self._release)
        t.bind("<Double-1>", self._open_row)
        t.bind("<Delete>", lambda e: self.remove_selected())
        t.bind("<Control-a>", self._select_all)
        t.bind("<Control-A>", self._select_all)
        t.bind("<Alt-Up>", lambda e: self._key_move("up"))
        t.bind("<Alt-Down>", lambda e: self._key_move("down"))
        t.bind("<<TreeviewSelect>>", self._selected)
        self._refresh()

    # ── 넣기 ──────────────────────────────────────────────────
    def pick_files(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.app, title="넣을 파일 고르기 (여러 개 골라도 돼요)",
                                            initialdir=self.app.open_dir(), filetypes=self.filetypes)
        if paths:
            self.app.remember_open_dir(Path(paths[0]).parent)
            self.add(list(paths))

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.app, title="폴더 고르기 (안에 있는 파일을 이름순으로 모두 넣어요)",
                                         initialdir=self.app.open_dir(), mustexist=True)
        if folder:
            self.app.remember_open_dir(Path(folder))
            self.add([folder])

    def add(self, raw_paths: list[str]) -> None:
        """파일·폴더 경로들을 목록 끝에 넣는다. 한 번에 넣은 것끼리는 이름순."""
        files: list[Path] = []
        folders: list[Path] = []
        skipped: list[str] = []   # 넣을 수 없는 파일
        other: list[str] = []     # 다른 탭에 넣어야 하는 파일 (이미지 탭에 PDF)
        for raw in raw_paths:
            p = Path(raw)
            if p.is_dir():
                folders.append(p)
            elif core.kind_of(p) in self.kinds:
                files.append(p)
            elif core.kind_of(p) is not None:
                other.append(p.name)
            else:
                skipped.append(p.name)
        files.sort(key=lambda f: explorer_order(f.name))
        for folder in sorted(folders, key=lambda f: explorer_order(f.name)):
            try:
                inside = [c for c in folder.iterdir() if c.is_file() and core.kind_of(c) in self.kinds]
            except OSError:
                skipped.append(f"{folder.name} (폴더를 열 수 없음)")
                continue
            if not inside:
                skipped.append(f"{folder.name} (폴더 안에 넣을 파일이 없음)")
            files.extend(sorted(inside, key=lambda f: explorer_order(f.name)))

        have = {_key(e.path) for e in self.items}
        new: list[Entry] = []
        dup = 0
        for f in files:
            if _key(f) in have:
                dup += 1
                continue
            have.add(_key(f))
            new.append(Entry(f, core.kind_of(f)))
        for e in new:
            self.items.append(e)
            self.tree.insert("", "end", iid=e.iid, values=self._values(e, len(self.items)))
        if new:
            self.tree.see(new[-1].iid)
            self.app.inspect(self, new)
            self.app.progress["value"] = 0
        self._refresh()

        parts = [f"{len(new)}개를 넣었어요" if new else "넣은 파일이 없어요"]
        if dup:
            parts.append(f"이미 목록에 있는 {dup}개는 뺐어요")
        if other:
            parts.append(f"PDF {len(other)}개는 '② PDF 합치기' 탭에서 넣어 주세요")
        if skipped:
            more = " 등" if len(skipped) > 3 else ""
            parts.append(f"넣을 수 없는 것 {len(skipped)}개: {', '.join(skipped[:3])}{more}")
        if any(Path(s).suffix.lower() in (".heic", ".heif") for s in skipped):
            parts.append("HEIC 사진은 JPG로 바꿔서 넣어 주세요")
        text = " · ".join(parts)
        self.app.status(text, warn=not new or bool(other or skipped))
        if not new and (other or skipped):
            messagebox.showinfo(TITLE, text.replace(" · ", "\n"), parent=self.app)

    def set_pages(self, iid: str, pages: int | None, error: str) -> None:
        for i, e in enumerate(self.items):
            if e.iid == iid:
                e.pages, e.error = pages, error
                self.tree.item(iid, values=self._values(e, i + 1), tags=("bad",) if error else ())
                self._refresh()
                return

    # ── 순서 ──────────────────────────────────────────────────
    def selected_ids(self) -> list[str]:
        sel = set(self.tree.selection())
        return [e.iid for e in self.items if e.iid in sel]

    def move(self, where: str) -> None:
        ids = self.selected_ids()
        if not ids:
            self.app.status("옮길 줄을 먼저 골라 주세요", warn=True)
            return
        pos = [i for i, e in enumerate(self.items) if e.iid in ids]
        first, last, n = pos[0], pos[-1], len(ids)
        slot = {"top": 0, "up": max(0, first - 1), "down": last - n + 2, "bottom": len(self.items) - n}[where]
        self._move_to(ids, slot)
        self.tree.see(ids[0] if where in ("top", "up") else ids[-1])

    def _key_move(self, where: str) -> str:
        self.move(where)
        return "break"

    def _move_to(self, ids: list[str], slot: int) -> None:
        """고른 줄들을 (나머지 줄 기준) slot 자리로 옮긴다"""
        block = [e for e in self.items if e.iid in ids]
        rest = [e for e in self.items if e.iid not in ids]
        slot = max(0, min(slot, len(rest)))
        self.items = rest[:slot] + block + rest[slot:]
        self._sync_order()

    def sort_by_name(self) -> None:
        if not self.items:
            return
        ordered = sorted(self.items, key=lambda e: (explorer_order(e.path.name), explorer_order(str(e.path.parent))))
        reverse = [e.iid for e in ordered] == [e.iid for e in self.items]
        if reverse:
            ordered.reverse()
        self.items = ordered
        self._sync_order()
        self.app.status("이름 역순으로 정렬했어요 (한 번 더 누르면 이름순)" if reverse else "이름순으로 정렬했어요")

    def _sync_order(self) -> None:
        for i, e in enumerate(self.items):
            self.tree.move(e.iid, "", i)
            self.tree.set(e.iid, "no", i + 1)

    # ── 빼기 ──────────────────────────────────────────────────
    def remove_selected(self) -> None:
        ids = set(self.selected_ids())
        if not ids:
            self.app.status("뺄 줄을 먼저 골라 주세요", warn=True)
            return
        first = min(i for i, e in enumerate(self.items) if e.iid in ids)
        self.items = [e for e in self.items if e.iid not in ids]
        self.tree.delete(*ids)
        self._sync_order()
        if self.items:
            nxt = self.items[min(first, len(self.items) - 1)].iid
            self.tree.selection_set(nxt)
            self.tree.focus(nxt)
            self.tree.see(nxt)
        self._refresh()
        self.app.status(f"{len(ids)}개를 목록에서 뺐어요 (파일은 그대로 있어요)")

    def clear(self) -> None:
        if not self.items:
            return
        if not messagebox.askyesno(TITLE, f"목록의 {len(self.items)}개를 모두 비울까요?\n(목록에서만 빠지고 파일은 그대로 있어요)",
                                   parent=self.app):
            return
        self.tree.delete(*[e.iid for e in self.items])
        self.items = []
        self._refresh()
        self.app.status("목록을 비웠어요")

    # ── 마우스 · 키보드 ─────────────────────────────────────────
    def _press(self, event):
        self._dragged = False
        if self.tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            self._drag = None
            return None
        self._drag = self.tree.identify_row(event.y) or None
        sel = self.tree.selection()
        if self._drag and not event.state & (SHIFT | CONTROL) and len(sel) > 1 and self._drag in sel:
            self.tree.focus_set()
            return "break"  # 여러 줄을 골라 둔 채로 한꺼번에 끌 수 있게 선택을 그대로 둔다
        return None

    def _motion(self, event):
        if not self._drag:
            return None
        height = self.tree.winfo_height()
        if event.y < 10:
            self.tree.yview_scroll(-1, "units")
        elif event.y > height - 10:
            self.tree.yview_scroll(1, "units")
        target = self.tree.identify_row(event.y)
        ids = self.selected_ids()
        if target and ids and target not in ids:
            pos = {e.iid: i for i, e in enumerate(self.items)}
            t = pos[target]
            rest_index = t - sum(1 for i in ids if pos[i] < t)
            self._move_to(ids, rest_index + 1 if t > pos[ids[-1]] else rest_index)
            self._dragged = True
            self.tree.configure(cursor="sb_v_double_arrow")
        return "break"

    def _release(self, event):
        if self._drag and not self._dragged and not event.state & (SHIFT | CONTROL):
            sel = self.tree.selection()
            if len(sel) > 1 and self._drag in sel:
                self.tree.selection_set(self._drag)  # 끌지 않고 클릭만 했으면 그 줄만 고른다
                self.tree.focus(self._drag)
        if self._dragged:
            self.app.status("순서를 바꿨어요")
        self._drag = None
        self._dragged = False
        self.tree.configure(cursor="")

    def _open_row(self, event):
        row = self.tree.identify_row(event.y)
        entry = next((e for e in self.items if e.iid == row), None)
        if entry is not None:
            self.app.open_path(entry.path)
        return "break"

    def _select_all(self, event):
        self.tree.selection_set([e.iid for e in self.items])
        return "break"

    def _selected(self, event) -> None:
        ids = self.selected_ids()
        if len(ids) == 1:
            entry = next(e for e in self.items if e.iid == ids[0])
            if entry.error:
                self.app.status(f"{entry.path.name}: {entry.error}", warn=True)
            else:
                self.app.status(str(entry.path))

    # ── 표시 ──────────────────────────────────────────────────
    @staticmethod
    def _values(e: Entry, no: int) -> tuple:
        if e.error:
            pages = "열 수 없음"
        elif e.pages is None:
            pages = "…"
        else:
            pages = e.pages
        folder = str(e.path.parent)
        if len(folder) > 40 and len(e.path.parent.parts) > 3:
            folder = "…\\" + "\\".join(e.path.parent.parts[-2:])  # 끝쪽 폴더 이름이 보이게 (전체 경로는 줄을 고르면 아래에)
        return no, e.path.name, pages, folder

    def _refresh(self) -> None:
        if not self.items:
            self.empty.place(in_=self.tree, relx=0.5, rely=0.5, anchor="center")
            self.summary.configure(text="", foreground=HINT)
            return
        self.empty.place_forget()
        good = [e for e in self.items if not e.error]
        bad = len(self.items) - len(good)
        text = f"파일 {len(self.items)}개 · 모두 {sum(e.pages or 0 for e in good)}쪽"
        if any(e.pages is None for e in good):
            text += " (쪽수 세는 중…)"
        if bad:
            text += f" · 열 수 없는 파일 {bad}개 (빨간 줄)"
        self.summary.configure(text=text, foreground=BAD if bad else "")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(TITLE)
        self._setup_style()
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self._closed = False
        self._open_dir = ""  # 이번에 실행한 동안 마지막으로 파일을 고른 폴더 / 저장한 폴더 (파일로 남기지 않음)
        self._last_save_dir = ""
        self._build()
        self._fit_screen()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.drop: dnd.FileDrop | None = None
        try:
            self.drop = dnd.FileDrop(self._all_hwnds())
        except Exception as exc:  # noqa: BLE001 - 끌어다 놓기만 안 될 뿐 나머지는 쓸 수 있다
            self.status(f"끌어다 놓기를 켜지 못했어요 ({exc}). '파일 추가' 버튼으로 넣어 주세요.", warn=True)
        threading.Thread(target=core.clean_old_temp, daemon=True).start()
        self._poll_id = self.after(100, self._poll)

    # ── 모양 ──────────────────────────────────────────────────
    def _setup_style(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Malgun Gothic", size=9)
            except tk.TclError:
                pass
        self.bold = tkfont.Font(family="Malgun Gothic", size=9, weight="bold")
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=int(tkfont.nametofont("TkDefaultFont").metrics("linespace") * 1.6))
        style.configure("Accent.TButton", font=self.bold, padding=(18, 6))
        style.configure("TNotebook.Tab", padding=(14, 4))

    def _all_hwnds(self) -> list[int]:
        """창 안 모든 칸의 Windows 창 번호. 어느 칸에 놓아도 파일을 받게 한다 (안 보이는 탭의 칸도 이때 만들어진다)."""
        out, todo = [], [self]
        while todo:
            w = todo.pop()
            out.append(w.winfo_id())
            todo.extend(w.winfo_children())
        return out

    def _fit_screen(self) -> None:
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 90)
        self.geometry(f"{w}x{h}+40+20")
        self.minsize(w, min(h, 560))

    def _build(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.tabs = ttk.Notebook(root)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self._build_image_tab()
        self._build_merge_tab()

        bottom = ttk.Frame(root)
        bottom.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(bottom, maximum=100, length=200)
        self.progress.grid(row=0, column=0, sticky="w")
        self.status_var = tk.StringVar(value="파일을 넣고 순서를 정한 다음 저장 버튼을 누르세요.")
        self.status_label = ttk.Label(bottom, textvariable=self.status_var, width=1)
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(10, 0))

    def _options_row(self, box, row: int, label: str, var: tk.StringVar, choices, hints: dict[str, str]) -> None:
        ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=3)
        hint = ttk.Label(box, foreground=HINT)

        def changed(*_) -> None:
            hint.configure(text=hints[var.get()])

        for col, (value, text) in enumerate(choices, start=1):
            ttk.Radiobutton(box, text=text, value=value, variable=var).grid(
                row=row, column=col, sticky="w", padx=(12, 0), pady=3)
        hint.grid(row=row, column=len(choices) + 1, sticky="w", padx=(16, 0), pady=3)
        hint.configure(text=hints[var.get()])
        var.trace_add("write", changed)

    def _build_image_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="① 이미지 → PDF")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(tab, text="이미지를 PDF로 바꿔서 저장해요. 목록 순서가 PDF의 쪽 순서가 돼요.").grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        self.image_list = FileList(tab, self, {"image"}, [("이미지 파일", IMAGE_PATTERN), ("모든 파일", "*.*")],
                                   "여기에 이미지를 끌어다 놓거나\n위의 '파일 추가'를 누르세요")
        self.image_list.grid(row=1, column=0, sticky="nsew")

        opts = ttk.LabelFrame(tab, text=" 저장 설정 ", padding=(10, 4))
        opts.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.image_page = tk.StringVar(value="a4")
        self.image_mode = tk.StringVar(value="one")
        self._options_row(opts, 0, "페이지 크기", self.image_page, (("a4", "A4에 맞춤"), ("original", "원본 크기")),
                          PAGE_HINTS)
        self._options_row(opts, 1, "저장 방식", self.image_mode,
                          (("one", "PDF 1개로 합치기"), ("each", "이미지마다 PDF 따로")), MODE_HINTS)

        self.image_save_btn = ttk.Button(tab, text="PDF로 저장…", style="Accent.TButton", command=self._save_images)
        self.image_save_btn.grid(row=3, column=0, sticky="e", pady=(10, 0))

    def _build_merge_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="② PDF 합치기")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(tab, text="PDF와 이미지를 목록 순서대로 PDF 1개로 합쳐요. 원래 파일은 바뀌지 않아요.").grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        self.merge_list = FileList(tab, self, {"pdf", "image"},
                                   [("PDF·이미지", "*.pdf " + IMAGE_PATTERN), ("PDF 파일", "*.pdf"),
                                    ("이미지 파일", IMAGE_PATTERN), ("모든 파일", "*.*")],
                                   "여기에 PDF나 이미지를 끌어다 놓거나\n위의 '파일 추가'를 누르세요")
        self.merge_list.grid(row=1, column=0, sticky="nsew")

        opts = ttk.LabelFrame(tab, text=" 저장 설정 ", padding=(10, 4))
        opts.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.merge_page = tk.StringVar(value="a4")
        hints = {k: "목록의 이미지에만 적용돼요. PDF는 원래 모양 그대로 들어가요." for k in PAGE_HINTS}
        self._options_row(opts, 0, "이미지 페이지 크기", self.merge_page,
                          (("a4", "A4에 맞춤"), ("original", "원본 크기")), hints)

        self.merge_save_btn = ttk.Button(tab, text="합쳐서 저장…", style="Accent.TButton", command=self._save_merge)
        self.merge_save_btn.grid(row=3, column=0, sticky="e", pady=(10, 0))

    # ── 폴더 기억 (실행하는 동안만) ─────────────────────────────
    def open_dir(self) -> str | None:
        """None이면 Windows 대화상자가 기억하는 마지막 폴더가 열린다"""
        return self._open_dir if self._open_dir and Path(self._open_dir).is_dir() else None

    def remember_open_dir(self, folder: Path) -> None:
        self._open_dir = str(folder)

    def _save_dir(self, entries: list[Entry]) -> str:
        if self._last_save_dir and Path(self._last_save_dir).is_dir():
            return self._last_save_dir
        return str(entries[0].path.parent)

    # ── 저장 ──────────────────────────────────────────────────
    def _save_images(self) -> None:
        entries = list(self.image_list.items)
        if not entries:
            messagebox.showinfo(TITLE, "이미지를 먼저 넣어 주세요.\n'파일 추가'를 누르거나 이미지를 이 창에 끌어다 놓으면 돼요.",
                                parent=self)
            return
        page = self.image_page.get()
        bad = [e for e in entries if e.error]
        if self.image_mode.get() == "one":
            if bad:
                messagebox.showwarning(TITLE, self._bad_text(bad) + "\n\n이 파일을 목록에서 빼고 다시 해 주세요.", parent=self)
                return
            target = self._ask_target(entries, f"{entries[0].path.stem}.pdf")
            if target is None:
                return
            items = [core.Item(e.path, e.kind) for e in entries]
            self._run(lambda progress: core.merge(items, page, target, progress),
                      lambda pages, error: self._done_one(target, pages, error, self.image_list))
            return

        if bad:
            if not messagebox.askyesno(TITLE, self._bad_text(bad) + "\n\n이 파일은 빼고 나머지만 저장할까요?", parent=self):
                return
            entries = [e for e in entries if not e.error]
            if not entries:
                return
        folder = filedialog.askdirectory(parent=self, title="PDF를 저장할 폴더 고르기", initialdir=self._save_dir(entries),
                                         mustexist=True)
        if not folder:
            return
        folder = Path(folder)
        plan = self._plan_each(entries, folder)
        if plan is None:
            return
        self._run(lambda progress: self._convert_each(plan, page, progress),
                  lambda result, error: self._done_each(folder, result, error))

    def _save_merge(self) -> None:
        entries = list(self.merge_list.items)
        if not entries:
            messagebox.showinfo(TITLE, "합칠 파일을 먼저 넣어 주세요.\n'파일 추가'를 누르거나 파일을 이 창에 끌어다 놓으면 돼요.",
                                parent=self)
            return
        bad = [e for e in entries if e.error]
        if bad:
            messagebox.showwarning(TITLE, self._bad_text(bad) + "\n\n이 파일을 목록에서 빼고 다시 해 주세요.", parent=self)
            return
        if len(entries) == 1 and not messagebox.askyesno(
                TITLE, "목록에 파일이 1개뿐이에요. 이대로 저장할까요?", parent=self):
            return
        target = self._ask_target(entries, f"{entries[0].path.stem}_합본.pdf")
        if target is None:
            return
        page = self.merge_page.get()
        items = [core.Item(e.path, e.kind) for e in entries]
        self._run(lambda progress: core.merge(items, page, target, progress),
                  lambda pages, error: self._done_one(target, pages, error, self.merge_list))

    def _ask_target(self, entries: list[Entry], default_name: str) -> Path | None:
        path = filedialog.asksaveasfilename(parent=self, title="PDF 저장", defaultextension=".pdf",
                                            filetypes=[("PDF 파일", "*.pdf")], initialdir=self._save_dir(entries),
                                            initialfile=default_name)
        if not path:
            return None
        target = Path(path)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(target.name + ".pdf")
        if any(_key(e.path) == _key(target) for e in entries):
            messagebox.showwarning(TITLE, f"'{target.name}'은(는) 목록에 들어 있는 파일이에요.\n다른 이름으로 저장해 주세요.",
                                   parent=self)
            return None
        return target

    def _plan_each(self, entries: list[Entry], folder: Path) -> list[tuple[Path, Path]] | None:
        """이미지마다 저장할 PDF 이름을 정한다. 이미 있는 이름이면 덮어쓸지 물어본다."""
        wanted = [(e.path, folder / f"{e.path.stem}.pdf") for e in entries]
        exists = [t for _, t in wanted if t.exists()]
        overwrite = False
        if exists:
            names = "\n".join(f"· {t.name}" for t in exists[:5])
            if len(exists) > 5:
                names += f"\n… 외 {len(exists) - 5}개"
            answer = messagebox.askyesnocancel(
                TITLE, f"저장할 폴더에 같은 이름의 PDF가 {len(exists)}개 있어요.\n{names}\n\n"
                       "[예] 덮어쓰기\n[아니요] 이름 뒤에 (2), (3)…을 붙여 따로 저장\n[취소] 그만두기", parent=self)
            if answer is None:
                return None
            overwrite = answer
        taken: set[str] = set()
        plan = []
        for src, target in wanted:
            t, n = target, 1
            while t.name.casefold() in taken or (not overwrite and t.exists()):
                n += 1
                t = target.with_name(f"{target.stem} ({n}).pdf")
            taken.add(t.name.casefold())
            plan.append((src, t))
        return plan

    @staticmethod
    def _convert_each(plan: list[tuple[Path, Path]], page: str, progress) -> tuple[list[Path], list[str]]:
        saved, failed = [], []
        for i, (src, target) in enumerate(plan):
            progress(i, len(plan), src.name)
            try:
                core.image_to_pdf(src, target, page)
                saved.append(target)
            except Exception as exc:  # noqa: BLE001 - 하나가 안 돼도 나머지는 계속한다
                failed.append(str(exc) if isinstance(exc, (core.ItemError, core.SaveError))
                              else f"{src.name}: {core.reason_of(exc)}")
        return saved, failed

    def _run(self, job, done) -> None:
        """job(progress)를 뒤에서 돌리고, 끝나면 화면 쪽에서 done(결과, 오류)를 부른다"""
        self._set_busy(True)

        def progress(i: int, total: int, name: str | None) -> None:
            self.events.put(("progress", i, total, name))

        def work() -> None:
            try:
                result, error = job(progress), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            self.events.put(("finished", done, result, error))

        self.worker = threading.Thread(target=work, daemon=True, name="worker")
        self.worker.start()

    def _done_one(self, target: Path, pages: int | None, error: Exception | None, flist: FileList) -> None:
        if error is not None:
            self._failed(error, flist)
            return
        self._last_save_dir = str(target.parent)
        self.progress["value"] = 100
        self.status(f"저장했어요: {target.name} (모두 {pages}쪽)")
        if messagebox.askyesno(TITLE, f"저장했어요. (모두 {pages}쪽)\n\n{target}\n\n지금 열어 볼까요?", parent=self):
            self.open_path(target)

    def _done_each(self, folder: Path, result, error: Exception | None) -> None:
        if error is not None:
            self._failed(error, self.image_list)
            return
        saved, failed = result
        self._last_save_dir = str(folder)
        self.progress["value"] = 100
        text = f"PDF {len(saved)}개를 저장했어요.\n\n{folder}"
        if failed:
            text += f"\n\n저장하지 못한 파일 {len(failed)}개:\n" + "\n".join(f"· {f}" for f in failed[:8])
            if len(failed) > 8:
                text += f"\n… 외 {len(failed) - 8}개"
        self.status(f"PDF {len(saved)}개를 저장했어요" + (f" · 저장하지 못한 파일 {len(failed)}개" if failed else ""),
                    warn=bool(failed))
        if saved:
            if messagebox.askyesno(TITLE, text + "\n\n폴더를 열어 볼까요?", parent=self):
                self.open_path(folder)
        else:
            messagebox.showwarning(TITLE, text, parent=self)

    def _failed(self, error: Exception, flist: FileList) -> None:
        self.progress["value"] = 0
        self.status("저장하지 못했어요", warn=True)
        if isinstance(error, core.ItemError):
            for e in flist.items:
                if _key(e.path) == _key(error.path):
                    flist.tree.selection_set(e.iid)
                    flist.tree.see(e.iid)
                    break
            messagebox.showwarning(TITLE, f"이 파일 때문에 저장하지 못했어요. (만들어진 PDF는 없어요)\n\n"
                                          f"{error.path.name}\n{error.reason}\n\n"
                                          "이 파일을 목록에서 빼거나 고친 다음 다시 해 주세요.", parent=self)
        elif isinstance(error, core.SaveError):
            messagebox.showwarning(TITLE, str(error), parent=self)
        else:
            messagebox.showerror(TITLE, f"생각지 못한 오류가 났어요. (만들어진 PDF는 없어요)\n\n"
                                        f"{type(error).__name__}: {error}", parent=self)

    @staticmethod
    def _bad_text(bad: list[Entry]) -> str:
        lines = "\n".join(f"· {e.path.name} — {e.error}" for e in bad[:8])
        if len(bad) > 8:
            lines += f"\n… 외 {len(bad) - 8}개"
        return f"열 수 없는 파일이 {len(bad)}개 있어요 (목록의 빨간 줄).\n{lines}"

    # ── 상태 ──────────────────────────────────────────────────
    def inspect(self, flist: FileList, entries: list[Entry]) -> None:
        """새로 넣은 파일의 쪽수를 뒤에서 센다 (열 수 없는 파일도 여기서 걸러진다)"""
        jobs = [(e.iid, e.path) for e in entries]

        def work() -> None:
            for iid, path in jobs:
                try:
                    pages, error = core.inspect(path), ""
                except core.ItemError as exc:
                    pages, error = None, exc.reason
                except Exception as exc:  # noqa: BLE001
                    pages, error = None, core.reason_of(exc)
                self.events.put(("pages", flist, iid, pages, error))

        threading.Thread(target=work, daemon=True).start()

    def status(self, text: str, warn: bool = False) -> None:
        self.status_var.set(text)
        self.status_label.configure(foreground=BAD if warn else "")

    def open_path(self, path: Path) -> None:
        try:
            os.startfile(path)  # noqa: S606 - 사용자가 고른 파일·폴더를 기본 프로그램으로 연다
        except OSError as exc:
            messagebox.showwarning(TITLE, f"열지 못했어요.\n{path}\n({exc})", parent=self)

    def _running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _set_busy(self, busy: bool) -> None:
        for b in (self.image_save_btn, self.merge_save_btn):
            b.state(["disabled"] if busy else ["!disabled"])
        if busy:
            self.progress["value"] = 0
            self.status("준비하는 중…")

    def _current_list(self) -> FileList:
        return self.image_list if self.tabs.index("current") == 0 else self.merge_list

    def _poll(self) -> None:
        if self.drop is not None:
            for paths in self.drop.take():
                self._current_list().add(paths)
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "pages":
                    _, flist, iid, pages, error = event
                    flist.set_pages(iid, pages, error)
                elif kind == "progress":
                    _, i, total, name = event
                    if name is None:
                        self.progress["value"] = 100
                        self.status("PDF 파일로 저장하는 중…")
                    else:
                        self.progress["value"] = i / max(1, total) * 100
                        self.status(f"{i + 1}/{total} · {name}")
                elif kind == "finished":
                    _, done, result, error = event
                    self.worker = None
                    self._set_busy(False)
                    done(result, error)
        except queue.Empty:
            pass
        if not self._closed:
            self._poll_id = self.after(100, self._poll)

    def _on_close(self) -> None:
        if self._running() and not messagebox.askyesno(
                TITLE, "아직 저장하는 중이에요. 그래도 닫을까요?\n(지금 만들던 PDF는 저장되지 않아요)", parent=self):
            return
        self.destroy()

    def destroy(self) -> None:
        self._closed = True
        try:
            self.after_cancel(self._poll_id)
        except (tk.TclError, AttributeError, ValueError):
            pass
        if getattr(self, "drop", None) is not None:
            self.drop.close()
        super().destroy()

    def report_callback_exception(self, exc, val, tb) -> None:  # 버튼 등에서 난 오류도 화면에 알린다
        self.status(f"오류: {exc.__name__}: {val}", warn=True)
        messagebox.showerror(TITLE, f"생각지 못한 오류가 났어요.\n\n{exc.__name__}: {val}", parent=self)


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App().mainloop()
