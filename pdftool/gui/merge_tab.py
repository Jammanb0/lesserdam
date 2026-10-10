"""② 하나로 합치기: 목록 순서대로 PDF 1개"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import core, naming
from .common import DOC_PATTERN, HINT, IMAGE_PATTERN, TITLE, bad_text, key
from .filelist import FileList
from .options import BookmarkBox, ImageOptionsBox

if TYPE_CHECKING:
    from .app import App


class MergeTab(ttk.Frame):
    title = "② 하나로 합치기"

    def __init__(self, parent, app: App) -> None:
        super().__init__(parent, padding=10)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.folder = tk.StringVar()
        self.filename = tk.StringVar()
        self._auto_name = ""
        ttk.Label(self, text="PDF·이미지·한글·워드 등을 목록 순서대로 PDF 1개로 합쳐요. 원래 파일은 바뀌지 않아요.").grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        self.files = FileList(self, app, {"pdf", "image", *core.DOC_KINDS},
                              [("합칠 수 있는 파일", f"*.pdf {IMAGE_PATTERN} {DOC_PATTERN}"), ("PDF 파일", "*.pdf"),
                               ("이미지 파일", IMAGE_PATTERN), ("한글·오피스 문서", DOC_PATTERN), ("모든 파일", "*.*")],
                              "여기에 PDF·이미지·한글·워드 파일을 끌어다 놓거나\n위의 '파일 추가'를 누르세요",
                              on_change=self._files_changed)
        self.files.grid(row=1, column=0, sticky="nsew")

        bottom = ttk.Frame(self)
        bottom.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(2, weight=1)
        self.image_opts = ImageOptionsBox(bottom, note="PDF·문서는 원래 모양 그대로")
        self.image_opts.grid(row=0, column=0, sticky="nw")
        marks = ttk.LabelFrame(bottom, text=" 책갈피 (파일마다) ", padding=(10, 4))
        marks.grid(row=0, column=1, sticky="nw", padx=(10, 0))
        ttk.Label(marks, text="합친 PDF의 책갈피 칸에서 파일마다 바로 찾아갈 수 있어요.", foreground=HINT).pack(anchor="w")
        self.bookmarks = BookmarkBox(marks, ["name", "rule", "folder", "none"], on_change=self.update_bookmarks,
                                     dialog_split=self._split, preview=self._preview)
        self.bookmarks.pack(anchor="w", pady=(4, 2))
        self.bookmark_example = ttk.Label(marks, foreground=HINT, wraplength=330, justify="left")
        self.bookmark_example.pack(anchor="w", pady=(0, 2))
        save = ttk.LabelFrame(self, text=" 저장할 파일 ", padding=(10, 8))
        save.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        save.columnconfigure(1, weight=1)
        ttk.Label(save, text="저장할 폴더").grid(row=0, column=0, sticky="w")
        ttk.Entry(save, textvariable=self.folder).grid(row=0, column=1, sticky="ew", padx=(8, 6))
        ttk.Button(save, text="폴더 선택…", command=self._pick_folder).grid(row=0, column=2)
        ttk.Label(save, text="파일 이름").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(save, textvariable=self.filename).grid(row=1, column=1, sticky="ew", padx=(8, 6), pady=(6, 0))
        self.run_btn = ttk.Button(save, text="합쳐서 저장", style="Accent.TButton", command=self.run)
        self.run_btn.grid(row=1, column=2, pady=(6, 0))

    def drop(self, paths: list[str]) -> None:
        self.files.add(paths)

    def set_busy(self, busy: bool) -> None:
        self.run_btn.state(["disabled"] if busy else ["!disabled"])

    def lists(self) -> list[FileList]:
        return [self.files]

    # ── 책갈피 ────────────────────────────────────────────────
    def _files_changed(self) -> None:
        entries = self.files.items
        if entries:
            if not self.folder.get().strip():
                self.folder.set(self.app.save_dir(entries[0].path.parent))
            if not self.filename.get().strip() or self.filename.get() == self._auto_name:
                self._auto_name = naming.merged_default([e.path.stem for e in entries]) + ".pdf"
                self.filename.set(self._auto_name)
        self.update_bookmarks()

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.app, title="PDF를 저장할 폴더 선택",
                                         initialdir=self.folder.get() or self.app.open_dir(), mustexist=False)
        if folder:
            self.folder.set(str(Path(folder)))

    def _split(self) -> naming.Split:
        return naming.split_names([e.path.stem for e in self.files.items])

    def _titles(self, entries, split: naming.Split | None = None) -> list[str]:
        stems = [e.path.stem for e in entries]
        split = split or self._split()
        return self.bookmarks.titles(stems, [e.path.parent.name for e in entries], [split] * len(stems))

    def _preview(self, rule: naming.NameRule, split: naming.Split | None) -> list[tuple[str, str]]:
        split = split or self._split()
        return [(e.path.stem, naming.make(rule, e.path.stem, i, split)) for i, e in enumerate(self.files.items)]

    def update_bookmarks(self) -> None:
        if self.bookmarks.mode_key() == "none":
            self.bookmark_example.configure(text="책갈피를 달지 않아요.")
            return
        titles = [t for t in self._titles(self.files.items) if t]
        more = f" … (모두 {len(titles)}개)" if len(titles) > 3 else ""
        self.bookmark_example.configure(text=f"예) {' · '.join(titles[:3])}{more}" if titles else "")

    def run(self) -> None:
        entries = list(self.files.items)
        if not entries:
            messagebox.showinfo(TITLE, "합칠 파일을 먼저 넣어 주세요.\n'파일 추가'를 누르거나 파일을 이 창에 끌어다 놓으면 돼요.",
                                parent=self.app)
            return
        bad = [e for e in entries if e.error]
        if bad:
            if not messagebox.askyesno(TITLE, bad_text(bad) + "\n\n이 파일은 빼고 합칠까요?", parent=self.app):
                return
            entries = [e for e in entries if not e.error]
            if not entries:
                return
        if len(entries) == 1 and not messagebox.askyesno(
                TITLE, "합칠 파일이 1개뿐이에요. 이대로 저장할까요?", parent=self.app):
            return
        target = self._ask_target(entries)
        if target is None:
            return
        items = [e.item() for e in entries]
        for item, title in zip(items, self._titles(entries)):
            item.mark = title
        opts = self.image_opts.get()
        self.app.run(lambda s: core.merge(s, items, opts, target),
                     lambda pages, error: self._done(target, pages, error))

    def _ask_target(self, entries) -> Path | None:
        if not self.folder.get().strip():
            self._pick_folder()
        if not self.folder.get().strip():
            return None
        name = self.filename.get().strip()
        stem = name[:-4] if name.lower().endswith(".pdf") else name
        if not stem or naming.safe_name(stem) != stem:
            messagebox.showwarning(TITLE, "저장할 파일 이름을 확인해 주세요.\n폴더 경로나 사용할 수 없는 문자는 이름에 넣을 수 없어요.",
                                   parent=self.app)
            return None
        folder = Path(self.folder.get().strip())
        if folder.exists() and not folder.is_dir():
            messagebox.showwarning(TITLE, "저장할 폴더 위치에 파일이 있어요. 다른 폴더를 선택해 주세요.", parent=self.app)
            return None
        if not folder.is_dir() and not messagebox.askyesno(TITLE, f"저장할 폴더가 없어요.\n{folder}\n\n새로 만들까요?", parent=self.app):
            return None
        target = folder / f"{stem}.pdf"
        if any(key(e.path) == key(target) for e in entries):
            messagebox.showwarning(TITLE, f"'{target.name}'은(는) 목록에 들어 있는 파일이에요.\n다른 이름으로 저장해 주세요.",
                                   parent=self.app)
            return None
        targets = self.app.plan_targets([target])
        return targets[0] if targets else None

    def _done(self, target: Path, pages: int | None, error: Exception | None) -> None:
        if error is not None:
            self.app.failed(error, self.files)
            return
        self.app.remember_save_dir(target.parent)
        self.app.status(f"저장했어요: {target.name} (모두 {pages}쪽)")
        if messagebox.askyesno(TITLE, f"저장했어요. (모두 {pages}쪽)\n\n{target}\n\n지금 열어 볼까요?", parent=self.app):
            self.app.open_path(target)
