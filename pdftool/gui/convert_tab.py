"""① PDF로 바꾸기: 파일마다 PDF 하나씩"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import core, naming
from .common import DOC_PATTERN, HINT, IMAGE_PATTERN, TITLE, bad_text, doc_support_text, listing, reveal
from .filelist import FileList
from .options import ImageOptionsBox, NamingBox

if TYPE_CHECKING:
    from .app import App


class ConvertTab(ttk.Frame):
    title = "① PDF로 바꾸기"

    def __init__(self, parent, app: App) -> None:
        super().__init__(parent, padding=10)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="파일마다 PDF를 하나씩 만들어요.  바꿀 수 있는 파일: " + doc_support_text()).grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        self.files = FileList(self, app, {"image", *core.DOC_KINDS},
                              [("바꿀 수 있는 파일", f"{IMAGE_PATTERN} {DOC_PATTERN}"), ("이미지", IMAGE_PATTERN),
                               ("한글·오피스 문서", DOC_PATTERN), ("모든 파일", "*.*")],
                              "여기에 이미지나 한글·워드·엑셀·파워포인트 파일을 끌어다 놓거나\n위의 '파일 추가'를 누르세요",
                              refuse=self._refuse, on_change=self.update_names)
        self.files.grid(row=1, column=0, sticky="nsew")

        opts = ttk.Frame(self)
        opts.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        opts.columnconfigure(1, weight=1)
        self.image_opts = ImageOptionsBox(opts)
        self.image_opts.grid(row=0, column=0, sticky="nsew")

        save = ttk.LabelFrame(opts, text=" 저장할 폴더 ", padding=(10, 4))
        save.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        save.columnconfigure(1, weight=1)
        self.where = tk.StringVar(value="same")
        self.folder = tk.StringVar()
        ttk.Radiobutton(save, text="원본 파일과 같은 폴더", value="same",
                        variable=self.where).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Radiobutton(save, text="지정한 폴더:", value="folder", variable=self.where).grid(
            row=1, column=0, sticky="w", pady=2)
        self.folder_entry = ttk.Entry(save, textvariable=self.folder)
        self.folder_entry.grid(row=1, column=1, sticky="ew", padx=(6, 4))
        ttk.Button(save, text="폴더 선택…", command=self._pick_folder).grid(row=1, column=2)
        ttk.Label(save, text="같은 이름의 PDF가 이미 있으면 저장하기 전에 물어봐요.", foreground=HINT).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.where.trace_add("write", lambda *_: self._where_changed())

        self.naming = NamingBox(self, on_change=self.update_names)
        self.naming.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        bottom = ttk.Frame(self)
        bottom.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(bottom, text="여러 파일을 PDF 하나로 만들려면 ② 탭을 쓰세요.", foreground=HINT).pack(side="left")
        ttk.Button(bottom, text="이 목록을 ② 탭으로 보내기", command=self._send_to_merge).pack(side="left", padx=(8, 0))
        self.run_btn = ttk.Button(bottom, text="PDF로 바꾸기", style="Accent.TButton", command=self.run)
        self.run_btn.pack(side="right")
        self._where_changed()
        self.update_names()

    # ── 화면 ──────────────────────────────────────────────────
    def drop(self, paths: list[str]) -> None:
        self.files.add(paths)

    def set_busy(self, busy: bool) -> None:
        self.run_btn.state(["disabled"] if busy else ["!disabled"])

    def lists(self) -> list[FileList]:
        return [self.files]

    @staticmethod
    def _refuse(other: list[Path]) -> str:
        pdfs = sum(1 for p in other if core.kind_of(p) == "pdf")
        if pdfs == len(other):
            return f"PDF {pdfs}개는 이미 PDF라서 뺐어요 (합치려면 ② 탭에 넣어 주세요)"
        return f"넣을 수 없는 종류 {len(other)}개는 뺐어요"

    def _where_changed(self) -> None:
        self.folder_entry.state(["!disabled"] if self.where.get() == "folder" else ["disabled"])
        if self.where.get() == "folder" and not self.folder.get().strip() and self.files.items:
            self.folder.set(str(self.files.items[0].path.parent))

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.app, title="PDF를 저장할 폴더 선택",
                                         initialdir=self.folder.get() or self.app.open_dir(), mustexist=False)
        if folder:
            self.folder.set(str(Path(folder)))
            self.where.set("folder")

    def _send_to_merge(self) -> None:
        if not self.files.items:
            self.app.status("보낼 파일이 없어요", warn=True)
            return
        self.app.send_to_merge([str(e.path) for e in self.files.items])

    def update_names(self) -> None:
        """이름 예시를 다시 그린다 (다른 부분을 쓰면 목록의 이름들을 구간으로 다시 나눈다)"""
        stems = [e.path.stem for e in self.files.items]
        if self.naming.uses_parts():
            self.naming.set_split(naming.split_names(stems))
        rule = self.naming.rule()
        names = [naming.make(rule, s, i, self.naming.split) for i, s in enumerate(stems)]
        if any(not n for n in names) or (not names and rule.middle == "none" and not (rule.before or rule.after)):
            self.naming.set_example([], "이름이 비어요. 앞에 붙일 말을 쓰거나 가운데를 '원래 이름'으로 골라 주세요.", warn=True)
        elif len(names) > 1 and len(set(names)) == 1:
            self.naming.set_example(names, "모든 파일 이름이 같아져요. 번호를 붙여 주세요. (그대로 두면 (2), (3)…이 붙어요)",
                                    warn=True)
        else:
            self.naming.set_example(names)

    # ── 저장 ──────────────────────────────────────────────────
    def run(self) -> None:
        entries = list(self.files.items)
        if not entries:
            messagebox.showinfo(TITLE, "바꿀 파일을 먼저 넣어 주세요.\n'파일 추가'를 누르거나 파일을 이 창에 끌어다 놓으면 돼요.",
                                parent=self.app)
            return
        bad = [e for e in entries if e.error]
        if bad:
            if not messagebox.askyesno(TITLE, bad_text(bad) + "\n\n이 파일은 빼고 나머지만 바꿀까요?", parent=self.app):
                return
            entries = [e for e in entries if not e.error]
            if not entries:
                return
        rule = self.naming.rule()
        names = [naming.make(rule, e.path.stem, i, self.naming.split) for i, e in enumerate(entries)]
        if any(not n for n in names):
            messagebox.showwarning(TITLE, "이름이 비는 파일이 있어요.\n'저장할 파일 이름'에서 앞에 붙일 말을 쓰거나 가운데를 '원래 이름'으로 골라 주세요.",
                                   parent=self.app)
            return
        if self.where.get() == "folder":
            folder = self._target_folder()
            if folder is None:
                return
            wanted = [folder / f"{n}.pdf" for n in names]
        else:
            wanted = [e.path.parent / f"{n}.pdf" for e, n in zip(entries, names)]
        targets = self.app.plan_targets(wanted)
        if targets is None:
            return
        plan = list(zip([e.item() for e in entries], targets))
        opts = self.image_opts.get()
        self.app.run(lambda s: core.convert_each(s, plan, opts), self._done)

    def _target_folder(self) -> Path | None:
        text = self.folder.get().strip()
        if not text:
            self._pick_folder()
            text = self.folder.get().strip()
            if not text:
                return None
        folder = Path(text)
        if not folder.is_dir():
            if not messagebox.askyesno(TITLE, f"저장할 폴더가 없어요.\n{folder}\n\n새로 만들까요?", parent=self.app):
                return None
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showwarning(TITLE, f"폴더를 만들지 못했어요.\n{folder}\n({exc})", parent=self.app)
                return None
        return folder

    def _done(self, report: core.Report | None, error: Exception | None) -> None:
        if error is not None:
            self.app.failed(error, self.files)
            return
        self.app.finish_many(report, "PDF")
