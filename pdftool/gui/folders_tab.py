"""③ 폴더끼리 짝지어 합치기: 폴더마다 같은 순서의 파일을 하나씩 모아 PDF 하나로"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import core, folders, naming, sorting
from ..naming import NameRule
from .common import BAD, HINT, SKIP_FG, TITLE, WARN_BG, key, short_folder
from .options import BookmarkBox, ImageOptionsBox, NamingBox

if TYPE_CHECKING:
    from .app import App

OUT_NAME = "합친 PDF"   # 저장할 폴더를 따로 고르지 않으면 첫 폴더 옆에 이 이름으로 만든다
OUTPUTS = {"each": "줄마다 하나씩", "one": "모두 이어서 하나로"}
ORDER_KEYS = {v: k for k, v in sorting.ORDERS.items()}
KIND_KEYS = {v[1]: k for k, v in folders.KIND_SETS.items()}


class FoldersTab(ttk.Frame):
    title = "③ 폴더끼리 짝지어 합치기"

    def __init__(self, parent, app: App) -> None:
        super().__init__(parent, padding=10)
        self.app = app
        self.paths: list[Path] = []              # 합칠 폴더 (이 순서로 이어 붙인다)
        self.scans: list[folders.Folder] = []
        self.excluded: set[int] = set()          # 사용자가 뺀 줄 (0부터)
        # 만들 줄: (줄 번호, [(폴더 번호, 파일)], 결과 파일 이름 또는 '하나로'일 때 줄 책갈피 이름)
        self.plan: list[tuple[int, list[tuple[int, Path]], str]] = []
        self.output = tk.StringVar(value="each")    # "each" 줄마다 PDF 하나씩 / "one" 모두 이어서 PDF 하나로
        self.order = tk.StringVar(value=sorting.ORDERS["name"])
        self.direction = tk.StringVar(value=sorting.direction_labels("name")[0])
        self.kinds = tk.StringVar(value=folders.KIND_SETS["pdf_image"][1])
        self.until = tk.StringVar(value="shortest")
        self.out_dir = tk.StringVar()
        self._out_auto = True
        self._refresh_id: str | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        intro = ttk.Frame(self)
        intro.grid(row=0, column=0, sticky="ew")
        ttk.Label(intro, text="여러 폴더에서 같은 순서의 파일을 하나씩 모아 PDF로 합쳐요.").pack(side="left")
        ttk.Label(intro, text="예) 한글\\가.pdf + 영어\\A.pdf + 숫자\\1.pdf → 첫 번째 PDF,  나 + B + 2 → 두 번째 PDF …",
                  foreground=HINT).pack(side="left", padx=(10, 0))

        self._build_top()
        self._build_middle()
        self._build_preview()

        bottom = ttk.Frame(self)
        bottom.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(3, weight=1)
        ttk.Label(bottom, text="파일 책갈피").grid(row=0, column=0, sticky="w")
        self.bookmarks = BookmarkBox(bottom, ["folder", "name", "rule", "none"], on_change=lambda: None,
                                     dialog_split=lambda: None, preview=self._bookmark_preview)
        self.bookmarks.grid(row=0, column=1, sticky="w", padx=(6, 18))
        self.out_label = ttk.Label(bottom, text="저장할 폴더")
        self.out_label.grid(row=0, column=2, sticky="w")
        self.out_entry = ttk.Entry(bottom, textvariable=self.out_dir)
        self.out_entry.grid(row=0, column=3, sticky="ew", padx=(6, 4))
        self.out_entry.bind("<Key>", lambda e: setattr(self, "_out_auto", False), add="+")
        self.out_btn = ttk.Button(bottom, text="폴더 선택…", command=self._pick_out)
        self.out_btn.grid(row=0, column=4)
        self.run_btn = ttk.Button(bottom, text="만들기", style="Accent.TButton", command=self.run)
        self.run_btn.grid(row=0, column=5, padx=(16, 0))

        self.order.trace_add("write", lambda *_: self._order_changed())
        for var in (self.direction, self.kinds):
            var.trace_add("write", lambda *_: self.rescan())
        for var in (self.until, self.output):
            var.trace_add("write", lambda *_: self.refresh_preview())
        self.refresh_folders()
        self.refresh_preview()

    # ── 화면 만들기 ────────────────────────────────────────────
    def _build_top(self) -> None:
        top = ttk.Frame(self)
        top.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        top.columnconfigure(0, weight=1)

        box = ttk.LabelFrame(top, text=" 합칠 폴더 — 위에서부터 이 순서로 이어 붙여요 ", padding=(8, 4))
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        bar = ttk.Frame(box)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Button(bar, text="폴더 추가", command=self.pick_folder).pack(side="left")
        ttk.Button(bar, text="▲ 위로", command=lambda: self.move(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="▼ 아래로", command=lambda: self.move(1)).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="빼기", command=self.remove).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="모두 비우기", command=self.clear).pack(side="left", padx=(4, 0))
        ttk.Label(bar, text="한꺼번에 끌어다 놓아도 돼요.", foreground=HINT).pack(side="left", padx=(10, 0))
        self.tree = ttk.Treeview(box, columns=("no", "name", "count", "where"), show="headings",
                                 selectmode="browse", height=3)
        for col, text, width, anchor, stretch in (("no", "순서", 46, "center", False),
                                                  ("name", "폴더", 150, "w", False),
                                                  ("count", "넣을 파일", 150, "w", False),
                                                  ("where", "위치", 200, "w", True)):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=40, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("bad", foreground=BAD)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._open_folder)
        self.tree.bind("<Delete>", lambda e: self.remove())
        self.tree.bind("<Alt-Up>", lambda e: (self.move(-1), "break")[1])
        self.tree.bind("<Alt-Down>", lambda e: (self.move(1), "break")[1])
        self.tree.bind("<<TreeviewSelect>>", self._folder_selected)
        # 비었을 때 안내: 늘 놓아 두고 표 뒤로 내리거나 앞으로 올린다 (치우면 그 자리가 다시 안 그려지는 일이 있다)
        self.empty = tk.Label(box, text="합칠 폴더를 2개 이상 끌어다 놓거나 '폴더 추가'를 누르세요",
                              fg=HINT, bg="SystemWindow")
        self.empty.place(in_=self.tree, relx=0.5, rely=0.5, anchor="center")

        pair = ttk.LabelFrame(top, text=" 짝 맞추기 ", padding=(10, 4))
        pair.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        ttk.Label(pair, text="각 폴더의 파일 정렬").grid(row=0, column=0, sticky="w", pady=2)
        row0 = ttk.Frame(pair)
        row0.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Combobox(row0, textvariable=self.order, values=list(sorting.ORDERS.values()), state="readonly",
                     width=14).pack(side="left")
        self.direction_box = ttk.Combobox(row0, textvariable=self.direction, state="readonly", width=22,
                                          values=list(sorting.direction_labels("name")))
        self.direction_box.pack(side="left", padx=(6, 0))
        ttk.Label(pair, text="정렬한 순서대로 1번째끼리, 2번째끼리 묶어요.", foreground=HINT).grid(
            row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Label(pair, text="가져올 파일").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Combobox(pair, textvariable=self.kinds, values=[v[1] for v in folders.KIND_SETS.values()],
                     state="readonly", width=38).grid(row=2, column=1, sticky="w", padx=(8, 0))
        self.count_label = ttk.Label(pair, wraplength=380, justify="left")
        self.count_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.until_radios = []
        for i, value in enumerate(folders.UNTIL):
            r = ttk.Radiobutton(pair, value=value, variable=self.until)
            r.grid(row=4 + i, column=0, columnspan=2, sticky="w", pady=1)
            self.until_radios.append(r)
        ttk.Label(pair, text="만들 PDF").grid(row=6, column=0, sticky="w", pady=(6, 2))
        row_out = ttk.Frame(pair)
        row_out.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(6, 2))
        self.output_radios = {}
        for value, text in OUTPUTS.items():
            r = ttk.Radiobutton(row_out, text=text, value=value, variable=self.output)
            r.pack(side="left", padx=(0, 12))
            self.output_radios[value] = r

    def _build_middle(self) -> None:
        mid = ttk.Frame(self)
        mid.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        mid.columnconfigure(0, weight=1)
        self.naming = NamingBox(mid, on_change=self.refresh_preview,
                                default=NameRule(middle="diff"), reference_label="결과 이름의 기준 폴더")
        self.naming.grid(row=0, column=0, sticky="nsew")
        self.image_opts = ImageOptionsBox(mid, note="PDF·문서는 원래 모양 그대로")
        self.image_opts.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

    def _build_preview(self) -> None:
        box = ttk.LabelFrame(self, text=" 미리 보기 — 만들어질 PDF ", padding=(8, 4))
        box.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        self.summary = ttk.Label(box)
        self.summary.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.preview = ttk.Treeview(box, show="headings", selectmode="browse", height=7)
        self.preview.tag_configure("skip", foreground=SKIP_FG)
        self.preview.tag_configure("gap", background=WARN_BG)
        vs = ttk.Scrollbar(box, orient="vertical", command=self.preview.yview)
        hs = ttk.Scrollbar(box, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.preview.grid(row=1, column=0, sticky="nsew")
        vs.grid(row=1, column=1, sticky="ns")
        hs.grid(row=2, column=0, sticky="ew")
        ttk.Label(box, text="'만들기' 칸을 누르면 그 줄을 빼거나 다시 넣어요 · 파일 이름을 두 번 누르면 열려요 · 노란 줄은 빠진 파일이 있는 줄",
                  foreground=HINT).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.preview.bind("<ButtonRelease-1>", self._preview_click)
        self.preview.bind("<Double-1>", self._preview_open)
        self.preview.bind("<<TreeviewSelect>>", self._preview_selected)
        self._columns: tuple = ()

    # ── 폴더 넣기 · 빼기 ─────────────────────────────────────────
    def drop(self, raw: list[str]) -> None:
        dirs = [Path(r) for r in raw if Path(r).is_dir()]
        files = [r for r in raw if not Path(r).is_dir()]
        if not dirs:
            self.app.status("③ 탭에는 폴더를 넣어 주세요 (파일은 ①·② 탭에서 다뤄요)", warn=True)
            return
        self.add_folders(dirs, note=f"파일 {len(files)}개는 뺐어요 (③ 탭에는 폴더만)" if files else "")

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.app, title="합칠 폴더 고르기 (여러 개면 하나씩 추가하거나 끌어다 놓으세요)",
                                         initialdir=self.app.open_dir(), mustexist=True)
        if folder:
            self.app.remember_open_dir(Path(folder).parent)
            self.add_folders([Path(folder)])

    def add_folders(self, dirs: list[Path], note: str = "") -> None:
        expanded = ""
        if len(dirs) == 1:
            subs = self._subfolders(dirs[0])
            try:
                take, _ = core.folder_files(dirs[0], self._kinds())
            except OSError:
                take = []
            if not take and len(subs) >= 2:  # 파일은 없고 폴더만 든 폴더면 그 안의 폴더들을 넣는다
                expanded = dirs[0].name
                dirs = subs
        have = {key(p) for p in self.paths}
        added = []
        for d in dirs:
            if key(d) not in have:
                have.add(key(d))
                added.append(d)
        self.paths.extend(added)
        if self._out_auto and self.paths:
            self.out_dir.set(str(self.paths[0].parent / OUT_NAME))
        self.rescan()
        parts = [f"'{expanded}' 안의 폴더 {len(added)}개를 넣었어요" if expanded else f"폴더 {len(added)}개를 넣었어요"]
        if len(dirs) > len(added):
            parts.append(f"이미 있는 {len(dirs) - len(added)}개는 뺐어요")
        if note:
            parts.append(note)
        self.app.status(" · ".join(parts), warn=not added)

    def _subfolders(self, folder: Path) -> list[Path]:
        out_key = key(Path(self.out_dir.get())) if self.out_dir.get().strip() else ""
        try:
            subs = [c for c in folder.iterdir() if c.is_dir() and core.usable_file(c)]
        except OSError:
            return []
        subs = [c for c in subs if c.name != OUT_NAME and key(c) != out_key]  # 예전에 만든 결과 폴더는 빼고
        return sorted(subs, key=sorting.name_key)

    def move(self, delta: int) -> None:
        sel = self.tree.selection()
        if not sel:
            self.app.status("옮길 폴더를 먼저 골라 주세요", warn=True)
            return
        i = int(sel[0])
        j = i + delta
        if not 0 <= j < len(self.paths):
            return
        self.paths[i], self.paths[j] = self.paths[j], self.paths[i]
        self.scans[i], self.scans[j] = self.scans[j], self.scans[i]
        self.refresh_folders(select=j)
        self.refresh_preview()

    def remove(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.app.status("뺄 폴더를 먼저 골라 주세요", warn=True)
            return
        i = int(sel[0])
        del self.paths[i]
        del self.scans[i]
        self.excluded.clear()
        self.refresh_folders(select=min(i, len(self.paths) - 1))
        self.refresh_preview()

    def clear(self) -> None:
        if self.paths and messagebox.askyesno(TITLE, "넣은 폴더를 모두 비울까요? (목록에서만 빠져요)", parent=self.app):
            self.paths, self.scans = [], []
            self.excluded.clear()
            self.refresh_folders()
            self.refresh_preview()

    def rescan(self) -> None:
        """폴더 안 파일을 다시 읽어 정한 순서로 늘어놓는다"""
        kinds = self._kinds()
        order = ORDER_KEYS.get(self.order.get(), "name")
        reverse = self.direction.get() == sorting.direction_labels(order)[1]
        self.scans = [folders.scan(p, kinds, order, reverse) for p in self.paths]
        self.excluded.clear()
        self.refresh_folders()
        self.refresh_preview()

    def _order_changed(self) -> None:
        """기준을 바꾸면 방향 말도 그 기준에 맞게 바꾼다 (오름·내림은 그대로)"""
        descending = self.direction.get().startswith("내림")
        labels = sorting.direction_labels(ORDER_KEYS.get(self.order.get(), "name"))
        self.direction_box.configure(values=list(labels))
        self.direction.set(labels[1 if descending else 0])  # 여기서 다시 읽는다 (rescan)

    def _kinds(self) -> set[str]:
        return folders.KIND_SETS[KIND_KEYS.get(self.kinds.get(), "pdf_image")][0]

    # ── 표시 ──────────────────────────────────────────────────
    def refresh_folders(self, select: int | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, f in enumerate(self.scans):
            if f.error:
                count, tags = f.error, ("bad",)
            else:
                count = f"{len(f.files)}개"
                if f.other:
                    count += f" (다른 종류 {len(f.other)}개 뺌)"
                tags = ("bad",) if not f.files else ()
            self.tree.insert("", "end", iid=str(i), values=(i + 1, f.name, count, short_folder(f.path.parent)),
                             tags=tags)
        if select is not None and 0 <= select < len(self.scans):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        if self.scans:
            self.empty.lower(self.tree)
        else:
            self.empty.lift(self.tree)
        names = [f"{i + 1}. {f.name}" for i, f in enumerate(self.scans)]
        current = self.naming.reference.get()
        self.naming.reference_box.configure(values=names)
        if current not in names:
            self.naming.reference.set(names[0] if names else "")

    def refresh_preview(self) -> None:
        """조금 모아서 한 번에 다시 그린다 (이름 칸에 글자를 칠 때마다 표 전체를 그리지 않게)"""
        if self._refresh_id is not None:
            self.after_cancel(self._refresh_id)
        self._refresh_id = self.after(120, self._redraw)

    def _reference(self) -> int:
        try:
            return max(0, int(self.naming.reference.get().split(".")[0]) - 1)
        except ValueError:
            return 0

    def _redraw(self) -> None:
        self._refresh_id = None
        scans = self.scans
        one = self.output.get() == "one"
        self._update_counts()
        ref = min(self._reference(), max(0, len(scans) - 1))
        if self.naming.uses_parts() and scans:
            self.naming.set_split(naming.split_names([p.stem for p in scans[ref].files]))
        rule = self.naming.rule()
        made_count = folders.row_count(scans, self.until.get()) if len(scans) >= 2 else 0
        rows = folders.rows(scans)
        plan: list[tuple[int, list[tuple[int, Path]], str]] = []
        for i, row in enumerate(rows):
            if i < made_count and i not in self.excluded and any(row):
                base = row[ref] if ref < len(row) and row[ref] else next(p for p in row if p)
                files = [(k, p) for k, p in enumerate(row) if p]
                plan.append((i, files, naming.make(rule, base.stem, len(plan), self.naming.split)))
        renamed = 0
        if one:
            self.plan = plan  # 책갈피 이름은 겹쳐도 된다
        else:
            out = Path(self.out_dir.get().strip() or ".")
            targets = naming.unique_targets([out / f"{name}.pdf" for _, _, name in plan], avoid_existing=False)
            renamed = sum(1 for t, (_, _, name) in zip(targets, plan) if t.stem != name)
            self.plan = [(i, files, t.stem) for (i, files, _), t in zip(plan, targets)]

        columns = ("use", "no", "name", *[f"f{j}" for j in range(len(scans))])
        if columns != self._columns:
            self.preview.configure(columns=columns)
            self._columns = columns
            for col, width, anchor in (("use", 64, "center"), ("no", 46, "center"), ("name", 220, "w")):
                self.preview.column(col, width=width, minwidth=40, anchor=anchor, stretch=False)
            for j in range(len(scans)):
                self.preview.column(f"f{j}", width=170, minwidth=60, anchor="w", stretch=True)
        for col, text, anchor in (("use", "만들기", "center"), ("no", "번호", "center"),
                                  ("name", "줄 책갈피 이름" if one else "결과 파일 이름", "w")):
            self.preview.heading(col, text=text, anchor=anchor)
        for j, f in enumerate(scans):
            self.preview.heading(f"f{j}", text=f"{j + 1}. {f.name}", anchor="w")

        names = {i: name for i, _, name in self.plan}
        self.preview.delete(*self.preview.get_children())
        for i, row in enumerate(rows):
            made = i in names
            if made:
                use = "만듦"
            elif i >= made_count:
                use = "—"
            else:
                use = "뺌"
            tags = ("gap",) if made and None in row else () if made else ("skip",)
            cells = [p.name if p else "(없음)" for p in row]
            shown = (names[i] if one else f"{names[i]}.pdf") if made else ""
            self.preview.insert("", "end", iid=str(i), values=(use, i + 1, shown, *cells), tags=tags)

        if len(scans) < 2:
            text = "폴더를 2개 이상 넣으면 여기에 만들어질 PDF가 보여요."
        elif one:
            text = f"줄 {len(self.plan)}개를 차례대로 이어 PDF 1개로 만들어요 (줄마다 책갈피를 달아요)"
        else:
            text = f"PDF {len(self.plan)}개를 만들어요"
        if len(scans) >= 2 and self.excluded:
            text += f" · 직접 뺀 줄 {len(self.excluded)}개"
        if renamed:
            text += f" · 이름이 겹쳐서 뒤에 (2), (3)…을 붙인 것 {renamed}개"
        self.summary.configure(text=text, foreground=BAD if renamed else "")
        self.output_radios["each"].configure(text=f"줄마다 하나씩 ({len(self.plan)}개)")
        self.output_radios["one"].configure(text="모두 이어서 하나로 (1개)")
        self.naming.configure(text=" 줄 책갈피 이름 (합친 PDF에서 줄마다) " if one else " 저장할 파일 이름 ")
        self.out_label.configure(text="저장할 곳은 만들 때 골라요" if one else "저장할 폴더")
        for w in (self.out_entry, self.out_btn):
            w.state(["disabled"] if one else ["!disabled"])
        if one:
            self.run_btn.configure(text="하나로 합쳐 저장…")
        else:
            self.run_btn.configure(text=f"{len(self.plan)}개 만들기" if self.plan else "만들기")
        example = [name for _, _, name in self.plan]
        if any(not n for n in example) and not one:
            self.naming.set_example([], "이름이 비는 줄이 있어요. 앞에 붙일 말을 쓰거나 가운데를 바꿔 주세요.", warn=True)
        else:
            self.naming.set_example([n or "(첫 파일 이름)" for n in example], suffix="" if one else ".pdf")

    def _update_counts(self) -> None:
        scans = self.scans
        counts = [len(f.files) for f in scans]
        texts = list(folders.UNTIL.values())
        if len(scans) < 2:
            self.count_label.configure(text="합칠 폴더를 2개 이상 넣어 주세요.", foreground=HINT)
            gap = None
        else:
            gap = folders.first_gap(scans)
            if gap is None:
                self.count_label.configure(text=f"폴더마다 {counts[0]}개씩, 파일 수가 같아요.", foreground=HINT)
            else:
                short = [f.name for f in scans if len(f.files) == gap]
                detail = " · ".join(f"{f.name} {len(f.files)}개" for f in scans)
                where = f"{gap + 1}번째부터 '{', '.join(short)}' 폴더에 파일이 없어요." if gap else \
                    f"'{', '.join(short)}' 폴더에 넣을 파일이 없어요."
                self.count_label.configure(text=f"⚠ 폴더마다 파일 수가 달라요 ({detail}).\n{where} 어떻게 할까요?",
                                           foreground=BAD)
                texts = [f"모든 폴더에 파일이 있는 데까지만 ({min(counts)}개 만들기)",
                         f"끝까지 만들기 ({max(counts)}개, 파일이 없는 폴더는 빼고 합치기)"]
        for r, text in zip(self.until_radios, texts):
            r.configure(text=text)
            r.state(["!disabled"] if gap is not None else ["disabled"])

    # ── 미리 보기 다루기 ─────────────────────────────────────────
    def _preview_click(self, event) -> None:
        if self.preview.identify_region(event.x, event.y) != "cell" or self.preview.identify_column(event.x) != "#1":
            return
        row = self.preview.identify_row(event.y)
        if not row:
            return
        i = int(row)
        made_count = folders.row_count(self.scans, self.until.get())
        if i >= made_count:
            self.app.status("이 줄은 '파일 수가 다를 때' 설정 때문에 만들지 않아요", warn=True)
            return
        if i in self.excluded:
            self.excluded.discard(i)
        else:
            self.excluded.add(i)
        self._redraw()
        self.preview.selection_set(row)

    def _cell_path(self, event) -> Path | None:
        row = self.preview.identify_row(event.y)
        col = self.preview.identify_column(event.x)
        if not row or not col:
            return None
        index = int(col[1:]) - 4  # #1 만들기 #2 번호 #3 이름 #4부터 폴더
        rows = folders.rows(self.scans)
        i = int(row)
        if 0 <= index < len(self.scans) and i < len(rows):
            return rows[i][index]
        return None

    def _preview_open(self, event) -> str:
        path = self._cell_path(event)
        if path is not None:
            self.app.open_path(path)
        return "break"

    def _preview_selected(self, event) -> None:
        sel = self.preview.selection()
        if sel:
            i = int(sel[0])
            plan = next((p for p in self.plan if p[0] == i), None)
            if plan:
                where = f"책갈피 '{plan[2]}'" if self.output.get() == "one" else f"{plan[2]}.pdf"
                self.app.status(f"{i + 1}번째: " + " + ".join(p.name for _, p in plan[1]) + f" → {where}")

    def _folder_selected(self, event) -> None:
        sel = self.tree.selection()
        if sel and int(sel[0]) < len(self.scans):
            f = self.scans[int(sel[0])]
            self.app.status(f.error or str(f.path), warn=bool(f.error))

    def _open_folder(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.app.open_path(self.scans[int(row)].path)

    def _pick_out(self) -> None:
        folder = filedialog.askdirectory(parent=self.app, title="PDF를 저장할 폴더 선택",
                                         initialdir=self.out_dir.get() or self.app.open_dir(), mustexist=False)
        if folder:
            self.out_dir.set(str(Path(folder)))
            self._out_auto = False
            self.refresh_preview()

    # ── 만들기 ────────────────────────────────────────────────
    def set_busy(self, busy: bool) -> None:
        self.run_btn.state(["disabled"] if busy else ["!disabled"])

    def lists(self) -> list:
        return []

    def run(self) -> None:
        if self._refresh_id is not None:
            self.after_cancel(self._refresh_id)
            self._redraw()
        if len(self.scans) < 2:
            messagebox.showinfo(TITLE, "합칠 폴더를 2개 이상 넣어 주세요.\n폴더를 이 창에 끌어다 놓거나 '폴더 추가'를 누르면 돼요.",
                                parent=self.app)
            return
        if not self.plan:
            messagebox.showinfo(TITLE, "만들 PDF가 없어요. 폴더 안에 넣을 파일이 있는지 봐 주세요.", parent=self.app)
            return
        one = self.output.get() == "one"
        if not one and any(not name for _, _, name in self.plan):
            messagebox.showwarning(TITLE, "이름이 비는 줄이 있어요.\n'저장할 파일 이름'에서 앞에 붙일 말을 쓰거나 가운데를 바꿔 주세요.",
                                   parent=self.app)
            return
        if not self._confirm_counts(one):
            return
        opts = self.image_opts.get()
        splits = self._splits(self.bookmarks.rule)
        if one:
            target = self._ask_one_target()
            if target is None:
                return
            rows = [(name or files[0][1].stem, self._items(files, splits)) for _, files, name in self.plan]
            self.app.run(lambda s: core.merge_rows(s, rows, opts, target),
                         lambda pages, error: self._done_one(target, pages, error))
            return
        text = self.out_dir.get().strip()
        if not text:
            self._pick_out()
            text = self.out_dir.get().strip()
            if not text:
                return
        out = Path(text)
        if any(key(out) == key(p) for p in self.paths):
            messagebox.showwarning(TITLE, "저장할 폴더가 합칠 폴더 중 하나와 같아요.\n다른 폴더를 골라 주세요.", parent=self.app)
            return
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showwarning(TITLE, f"저장할 폴더를 만들지 못했어요.\n{out}\n({exc})", parent=self.app)
            return
        targets = self.app.plan_targets([out / f"{name}.pdf" for _, _, name in self.plan])
        if targets is None:
            return
        sets = [(self._items(files, splits), target) for (_, files, _), target in zip(self.plan, targets)]
        self.app.run(lambda s: core.merge_sets(s, sets, opts),
                     lambda report, error: self._done(out, report, error))

    def _confirm_counts(self, one: bool) -> bool:
        """폴더마다 파일 수가 다르면 지금 설정대로 만들지 한 번 더 묻는다"""
        counts = [len(f.files) for f in self.scans]
        if len(set(counts)) <= 1:
            return True
        detail = "\n".join(f"· {f.name}: {len(f.files)}개" for f in self.scans)
        if self.until.get() == "shortest":
            how = f"지금 설정대로 {min(counts)}번째 줄까지만 쓰고, 그 뒤는 넣지 않아요."
        else:
            how = f"지금 설정대로 {max(counts)}번째 줄까지 모두 쓰고, 파일이 없는 폴더는 빼고 합쳐요."
        what = f"줄 {len(self.plan)}개를 PDF 1개로" if one else f"만들 PDF {len(self.plan)}개"
        return messagebox.askyesno(TITLE, f"폴더마다 파일 수가 달라요.\n{detail}\n\n{how}\n({what})\n\n이대로 만들까요?",
                                   parent=self.app)

    def _splits(self, rule: NameRule) -> dict[int, naming.Split]:
        """책갈피에 '원래 이름에서 구간 선택'을 쓸 때 폴더마다 이름을 나눈 결과"""
        if rule.middle != "diff":
            return {}
        return {k: naming.split_names([p.stem for p in f.files]) for k, f in enumerate(self.scans)}

    def _items(self, files: list[tuple[int, Path]], splits: dict[int, naming.Split]) -> list[core.Item]:
        titles = self.bookmarks.titles([p.stem for _, p in files], [self.scans[k].name for k, _ in files],
                                       [splits.get(k) for k, _ in files])
        return [core.Item(p, core.kind_of(p), mark=t) for (_, p), t in zip(files, titles)]

    def _bookmark_preview(self, rule: NameRule, split: naming.Split | None) -> list[tuple[str, str]]:
        """책갈피 이름 규칙 정하기 창의 미리 보기: 앞쪽 줄들의 파일"""
        splits = self._splits(rule)
        out = []
        for _, files, _ in self.plan[:6]:
            for j, (k, p) in enumerate(files):
                out.append((f"{self.scans[k].name}\\{p.stem}", naming.make(rule, p.stem, j, splits.get(k))))
        return out

    def _ask_one_target(self) -> Path | None:
        parent = self.paths[0].parent
        default = naming.safe_name(f"{parent.name or '폴더'}_합본") + ".pdf"
        path = filedialog.asksaveasfilename(parent=self.app, title="합친 PDF 저장 — 이름과 저장할 곳을 고르세요",
                                            defaultextension=".pdf", filetypes=[("PDF 파일", "*.pdf")],
                                            initialdir=self.app.save_dir(parent), initialfile=default)
        if not path:
            return None
        target = Path(path)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(target.name + ".pdf")
        if any(key(target.parent) == key(p) for p in self.paths):
            messagebox.showwarning(TITLE, "합칠 폴더 안에는 저장할 수 없어요 (다음에 그 폴더를 합칠 때 같이 들어가요).\n"
                                          "다른 곳을 골라 주세요.", parent=self.app)
            return None
        return target

    def _done(self, out: Path, report: core.Report | None, error: Exception | None) -> None:
        if error is not None:
            self.app.failed(error, None)
            return
        self.app.finish_many(report, "PDF", folder=out)

    def _done_one(self, target: Path, pages: int | None, error: Exception | None) -> None:
        if error is not None:
            self.app.failed(error, None)
            return
        self.app.remember_save_dir(target.parent)
        self.app.status(f"저장했어요: {target.name} (줄 {len(self.plan)}개, 모두 {pages}쪽)")
        if messagebox.askyesno(TITLE, f"저장했어요. (줄 {len(self.plan)}개, 모두 {pages}쪽)\n\n{target}\n\n지금 열어 볼까요?",
                               parent=self.app):
            self.app.open_path(target)
