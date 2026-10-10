"""순서를 정할 수 있는 파일 목록 (넣기 · 버튼으로 순서 바꾸기 · 정렬 · 돌리기 · 빼기)"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from .. import core, sorting
from .common import BAD, HINT, TITLE, TURN_TEXT, date_text, key, reveal, short_folder, size_text

if TYPE_CHECKING:
    from .app import App

_ids = count(1)

COLUMNS = (("no", "순서", 46, "center", False),
           ("name", "파일 이름", 250, "w", True),
           ("pages", "쪽", 72, "center", False),
           ("turn", "회전 각도", 82, "center", False),
           ("size", "크기", 70, "e", False),
           ("date", "수정한 날짜", 116, "center", False),
           ("folder", "폴더", 190, "w", True))
HEADER_ORDER = {"name": "name", "pages": "pages", "size": "size", "date": "modified", "folder": "folder"}


@dataclass
class Entry:
    path: Path
    kind: str                  # core.kind_of
    pages: int | None = None   # None: 세는 중이거나, 문서라서 바꿔 봐야 앎
    error: str = ""            # 열 수 없으면 그 이유
    checked: bool = False      # 쪽수 세기(열어 보기)가 끝났는지
    turn: int = 0              # 사용자가 돌린 각도 (시계 방향)
    size: int | None = None
    modified: float | None = None
    iid: str = field(default_factory=lambda: f"f{next(_ids)}")

    def item(self) -> core.Item:
        return core.Item(self.path, self.kind, self.turn)


class FileList(ttk.Frame):
    """refuse(파일들) → 이 목록에 못 넣는 종류일 때 알려 줄 말 / on_change() → 목록이 바뀔 때마다"""

    def __init__(self, parent, app: App, kinds: set[str], filetypes: list[tuple[str, str]], empty_text: str,
                 refuse: Callable[[list[Path]], str] | None = None,
                 on_change: Callable[[], None] | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.kinds = kinds
        self.filetypes = filetypes
        self.refuse = refuse
        self.on_change = on_change or (lambda: None)
        self.items: list[Entry] = []
        self.order = tk.StringVar(value="name")       # 정렬 기준. 새로 넣는 파일도 이 순서로 늘어놓는다
        self.direction = tk.StringVar(value="asc")    # "asc" 오름차순 / "desc" 내림차순
        self._sorted: tuple[str, bool] | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Button(top, text="파일 추가", command=self.pick_files).pack(side="left")
        ttk.Button(top, text="폴더 추가", command=self.pick_folder).pack(side="left", padx=(6, 0))
        ttk.Label(top, text="파일이나 폴더를 이 창에 끌어다 놓아도 돼요.", foreground=HINT).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="모두 비우기", command=self.clear).pack(side="right")
        ttk.Button(top, text="목록에서 빼기", command=self.remove_selected).pack(side="right", padx=(0, 6))

        self.tree = ttk.Treeview(self, columns=[c[0] for c in COLUMNS], show="headings", selectmode="extended",
                                 height=10)
        for col, text, width, anchor, stretch in COLUMNS:
            self.tree.heading(col, text=text, anchor=anchor,
                              command=(lambda c=col: self._header(c)) if col in HEADER_ORDER else "")
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
        sort_btn = ttk.Menubutton(side, text="정렬 기준…")
        sort_btn.pack(fill="x", pady=(10, 0))
        self.sort_menu = menu = tk.Menu(sort_btn, tearoff=False)
        menu.add_command(label="정렬 기준", state="disabled")
        for order, text in sorting.ORDERS.items():
            menu.add_radiobutton(label=text, value=order, variable=self.order, command=self._sort_menu)
        menu.add_separator()
        menu.add_command(label="방향", state="disabled")
        self._dir_index = menu.index("end") + 1
        for value, text in zip(("asc", "desc"), sorting.direction_labels("name")):
            menu.add_radiobutton(label=text, value=value, variable=self.direction, command=self._sort_menu)
        sort_btn["menu"] = menu
        ttk.Button(side, text="오른쪽 90° 회전", command=lambda: self.rotate(90)).pack(fill="x", pady=(4, 0))

        bottom = ttk.Frame(self)
        bottom.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.summary = ttk.Label(bottom)
        self.summary.pack(side="left")
        ttk.Label(bottom, text="위·아래 버튼으로 순서 변경 · 열 제목을 눌러 정렬 · 두 번 클릭하면 열기 · 오른쪽 클릭 메뉴",
                  foreground=HINT).pack(side="right")

        # 목록이 비었을 때 안내. 숨길 때 place_forget을 쓰면 가렸던 자리가 다시 안 그려지는 일이 있어서
        # 늘 놓아 두고 목록 표 뒤로 내리거나 앞으로 올린다.
        self.empty = tk.Label(self, text=empty_text, fg=HINT, bg="SystemWindow", justify="center")
        self.empty.place(in_=self.tree, relx=0.5, rely=0.5, anchor="center")
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="파일 열기", command=self._open_selected)
        self.menu.add_command(label="있는 폴더 열기", command=self._reveal_selected)
        self.menu.add_separator()
        self.menu.add_command(label="오른쪽 90° 회전", command=lambda: self.rotate(90))
        self.menu.add_command(label="왼쪽 90° 회전", command=lambda: self.rotate(270))
        self.menu.add_command(label="180° 회전", command=lambda: self.rotate(180))
        self.menu.add_command(label="회전 각도 초기화", command=lambda: self.rotate(None))
        self.menu.add_separator()
        self.menu.add_command(label="목록에서 빼기", command=self.remove_selected)

        t = self.tree
        t.bind("<Double-1>", self._open_row)
        t.bind("<Button-3>", self._context)
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
        folder = filedialog.askdirectory(parent=self.app, title="폴더 고르기 (안에 있는 파일을 모두 넣어요)",
                                         initialdir=self.app.open_dir(), mustexist=True)
        if folder:
            self.app.remember_open_dir(Path(folder))
            self.add([folder])

    def add(self, raw_paths: list[str]) -> None:
        """파일·폴더 경로들을 목록 끝에 넣는다. 한 번에 넣은 것끼리는 정해 둔 순서(처음엔 이름순)로."""
        files: list[Path] = []
        folders: list[Path] = []
        skipped: list[str] = []   # 넣을 수 없는 것
        other: list[Path] = []    # 다른 탭에 넣어야 하는 파일
        for raw in raw_paths:
            p = Path(raw)
            if p.is_dir():
                folders.append(p)
            elif core.kind_of(p) in self.kinds:
                files.append(p)
            elif core.kind_of(p) is not None:
                other.append(p)
            else:
                skipped.append(p.name)
        batch = self._ordered(files)
        for folder in sorted(folders, key=sorting.name_key):
            try:
                inside, rest = core.folder_files(folder, self.kinds)
            except OSError:
                skipped.append(f"{folder.name} (폴더를 열 수 없음)")
                continue
            other.extend(p for p in rest if core.kind_of(p) is not None)
            if not inside:
                skipped.append(f"{folder.name} (폴더 안에 넣을 파일이 없음)")
            batch.extend(self._ordered(inside))

        have = {key(e.path) for e in self.items}
        new: list[Entry] = []
        dup = 0
        for f in batch:
            if key(f) in have:
                dup += 1
                continue
            have.add(key(f))
            st = sorting.stat(f)
            new.append(Entry(f, core.kind_of(f), size=st.size if st else None, modified=st.modified if st else None))
        for e in new:
            self.items.append(e)
            self.tree.insert("", "end", iid=e.iid, values=self._values(e, len(self.items)))
        if new:
            self.tree.see(new[-1].iid)
            self.app.inspect(self, new)
            self._sorted = None
            self._headers()
        self._refresh()

        parts = [f"{len(new)}개를 넣었어요" if new else "넣은 파일이 없어요"]
        if dup:
            parts.append(f"이미 목록에 있는 {dup}개는 뺐어요")
        if other:
            parts.append(self.refuse(other) if self.refuse else f"넣을 수 없는 종류 {len(other)}개는 뺐어요")
        if skipped:
            more = " 등" if len(skipped) > 3 else ""
            parts.append(f"넣을 수 없는 것 {len(skipped)}개: {', '.join(skipped[:3])}{more}")
        if any(Path(s).suffix.lower() in (".heic", ".heif") for s in skipped):
            parts.append("HEIC 사진은 JPG로 바꿔서 넣어 주세요")
        text = " · ".join(parts)
        self.app.status(text, warn=not new or bool(other or skipped))
        if not new and (other or skipped):
            messagebox.showinfo(TITLE, text.replace(" · ", "\n"), parent=self.app)
        if new:
            self.on_change()

    def _ordered(self, paths: list[Path]) -> list[Path]:
        return sorting.sort_paths(paths, self.order.get(), self.direction.get() == "desc", self._pages())

    def set_pages(self, iid: str, pages: int | None, error: str) -> None:
        for i, e in enumerate(self.items):
            if e.iid == iid:
                e.pages, e.error, e.checked = pages, error, True
                self.tree.item(iid, values=self._values(e, i + 1), tags=("bad",) if error else ())
                self._refresh()
                return

    def set_doc_pages(self, path_key: str, pages: int) -> None:
        """문서를 PDF로 바꿔 쪽수를 알게 됐을 때"""
        for i, e in enumerate(self.items):
            if key(e.path) == path_key and e.pages != pages:
                e.pages = pages
                self.tree.item(e.iid, values=self._values(e, i + 1))
        self._refresh()

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
        new = rest[:slot] + block + rest[slot:]
        if [e.iid for e in new] != [e.iid for e in self.items]:
            self.items = new
            self._sorted = None
            self._headers()
            self._sync_order()
            self.on_change()

    def sort(self, order: str, reverse: bool) -> None:
        if not self.items:
            return
        by_key = {key(e.path): e for e in self.items}
        paths = sorting.sort_paths([e.path for e in self.items], order, reverse, self._pages())
        self.items = [by_key[key(p)] for p in paths]
        self._sorted = (order, reverse)
        self._headers()
        self._sync_order()
        self.on_change()
        unknown = {"taken": "찍은 날짜가 없는", "pages": "쪽수를 아직 모르는"}.get(order)
        how = sorting.direction_labels(order)[1 if reverse else 0].split(" (")[0]
        text = f"{sorting.ORDERS[order]} 기준 {how}으로 늘어놓았어요"
        if unknown:
            text += f" ({unknown} 파일은 맨 뒤에 이름순으로)"
        self.app.status(text)

    def _sort_menu(self) -> None:
        self._direction_labels()
        self.sort(self.order.get(), self.direction.get() == "desc")

    def _direction_labels(self) -> None:
        for i, text in enumerate(sorting.direction_labels(self.order.get())):
            self.sort_menu.entryconfigure(self._dir_index + i, label=text)

    def _header(self, col: str) -> None:
        order = HEADER_ORDER[col]
        reverse = self._sorted == (order, False)  # 같은 제목을 한 번 더 누르면 내림차순
        self.order.set(order)
        self.direction.set("desc" if reverse else "asc")
        self._direction_labels()
        self.sort(order, reverse)

    def _headers(self) -> None:
        for col, text, *_ in COLUMNS:
            mark = ""
            if self._sorted and HEADER_ORDER.get(col) == self._sorted[0]:
                mark = " ▼" if self._sorted[1] else " ▲"
            self.tree.heading(col, text=text + mark)

    def _pages(self) -> dict[str, int | None]:
        return {key(e.path): e.pages for e in self.items}

    def _sync_order(self) -> None:
        for i, e in enumerate(self.items):
            self.tree.move(e.iid, "", i)
            self.tree.set(e.iid, "no", i + 1)

    # ── 돌리기 · 빼기 ────────────────────────────────────────────
    def rotate(self, delta: int | None) -> None:
        ids = set(self.selected_ids())
        if not ids:
            self.app.status("회전할 파일을 먼저 골라 주세요", warn=True)
            return
        for i, e in enumerate(self.items):
            if e.iid in ids:
                e.turn = 0 if delta is None else (e.turn + delta) % 360
                self.tree.set(e.iid, "turn", TURN_TEXT[e.turn])
        self.app.status("고른 파일의 모든 쪽을 회전해 출력해요 (원래 파일은 그대로)" if delta else "회전 각도를 초기화했어요")

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
        self.on_change()
        self.app.status(f"{len(ids)}개를 목록에서 뺐어요 (파일은 그대로 있어요)")

    def clear(self) -> None:
        if not self.items:
            return
        if not messagebox.askyesno(TITLE, f"목록의 {len(self.items)}개를 모두 비울까요?\n(목록에서만 빠지고 파일은 그대로 있어요)",
                                   parent=self.app):
            return
        self.tree.delete(*[e.iid for e in self.items])
        self.items = []
        self._sorted = None
        self._headers()
        self._refresh()
        self.on_change()
        self.app.status("목록을 비웠어요")

    # ── 마우스 · 키보드 ─────────────────────────────────────────
    def _open_row(self, event):
        row = self.tree.identify_row(event.y)
        entry = next((e for e in self.items if e.iid == row), None)
        if entry is not None:
            self.app.open_path(entry.path)
        return "break"

    def _context(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
            self.tree.focus(row)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _first_selected(self) -> Entry | None:
        ids = self.selected_ids()
        return next((e for e in self.items if ids and e.iid == ids[0]), None)

    def _open_selected(self) -> None:
        entry = self._first_selected()
        if entry is not None:
            self.app.open_path(entry.path)

    def _reveal_selected(self) -> None:
        entry = self._first_selected()
        if entry is not None:
            reveal(entry.path)

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
        elif e.pages is not None:
            pages = e.pages
        elif e.checked:
            pages = "–"   # 문서: PDF로 바꿔 봐야 안다
        else:
            pages = "…"
        return (no, e.path.name, pages, TURN_TEXT[e.turn], size_text(e.size), date_text(e.modified),
                short_folder(e.path.parent))

    def _refresh(self) -> None:
        if not self.items:
            self.empty.lift(self.tree)
            self.summary.configure(text="", foreground=HINT)
            return
        self.empty.lower(self.tree)
        good = [e for e in self.items if not e.error]
        bad = len(self.items) - len(good)
        text = f"파일 {len(self.items)}개 · 모두 {sum(e.pages or 0 for e in good)}쪽"
        docs = sum(1 for e in good if e.checked and e.pages is None)
        if docs:
            text += f" (+ 문서 {docs}개는 PDF로 바꿔 봐야 쪽수를 알 수 있어요)"
        if any(not e.checked for e in good):
            text += " (쪽수 세는 중…)"
        if bad:
            text += f" · 열 수 없는 파일 {bad}개 (빨간 줄)"
        self.summary.configure(text=text, foreground=BAD if bad else "")
