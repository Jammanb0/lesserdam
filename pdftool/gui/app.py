"""창 (tkinter): ① PDF로 바꾸기  ② 하나로 합치기  ③ 폴더끼리 짝지어 합치기"""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, messagebox, ttk

from .. import core, dnd, naming, office
from .common import BAD, TITLE, TURN_TEXT, key, listing, reveal
from .convert_tab import ConvertTab
from .filelist import FileList
from .folders_tab import FoldersTab
from .merge_tab import MergeTab
from .licenses import show_licenses


class App(tk.Tk):
    def __init__(self, initial: list[str] | None = None) -> None:
        super().__init__()
        self.title(TITLE)
        self._setup_style()
        self.events: queue.Queue = queue.Queue()
        self.cache = core.DocCache()
        self.session: core.Session | None = None
        self._sessions: set[core.Session] = set()   # 아직 띄운 프로그램을 닫는 중인 작업도 포함
        self._closed = False
        self._open_dir = ""   # 이번에 실행한 동안 마지막으로 파일을 고른 폴더 / 저장한 폴더 (파일로 남기지 않음)
        self._last_save_dir = ""
        self._step: tuple[str, str | None, float] | None = None   # (진행 글, 바꾸는 프로그램 이름, 시작 시각)
        self._dialog: tuple[str, str] | None = None
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
        if initial:  # exe 아이콘에 파일을 끌어다 놓아 실행했을 때
            self.tabs.select(self.merge_tab)
            self.merge_tab.drop(initial)

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
        w = min(self.winfo_reqwidth(), self.winfo_screenwidth() - 40)
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 90)
        self.geometry(f"{w}x{h}+20+10")
        self.minsize(min(w, 900), min(h, 600))
        if self.winfo_reqheight() > self.winfo_screenheight() - 90 or self.winfo_reqwidth() > self.winfo_screenwidth() - 40:
            self.state("zoomed")  # 작은 화면(노트북)에서는 처음부터 크게

    def _build(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.tabs = ttk.Notebook(root)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.convert_tab = ConvertTab(self.tabs, self)
        self.merge_tab = MergeTab(self.tabs, self)
        self.folders_tab = FoldersTab(self.tabs, self)
        for tab in (self.convert_tab, self.merge_tab, self.folders_tab):
            self.tabs.add(tab, text=tab.title)

        bottom = ttk.Frame(root)
        bottom.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(bottom, maximum=100, length=200)
        self.progress.grid(row=0, column=0, sticky="w")
        self.status_var = tk.StringVar(value="파일을 넣고 순서를 정한 다음 아래 버튼을 누르세요.")
        self.status_label = ttk.Label(bottom, textvariable=self.status_var, width=1)
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.stop_btn = ttk.Button(bottom, text="중지", command=self.stop)
        ttk.Button(bottom, text="오픈소스 고지…", command=lambda: show_licenses(self)).grid(
            row=0, column=3, padx=(10, 0))

    def _tab_list(self):
        return (self.convert_tab, self.merge_tab, self.folders_tab)

    # ── 폴더 기억 (실행하는 동안만) ─────────────────────────────
    def open_dir(self) -> str | None:
        """None이면 Windows 대화상자가 기억하는 마지막 폴더가 열린다"""
        return self._open_dir if self._open_dir and Path(self._open_dir).is_dir() else None

    def remember_open_dir(self, folder: Path) -> None:
        self._open_dir = str(folder)

    def save_dir(self, default: Path) -> str:
        if self._last_save_dir and Path(self._last_save_dir).is_dir():
            return self._last_save_dir
        return str(default)

    def remember_save_dir(self, folder: Path) -> None:
        self._last_save_dir = str(folder)

    # ── 탭끼리 ────────────────────────────────────────────────
    def send_to_merge(self, paths: list[str]) -> None:
        turns = {key(e.path): e.turn for e in self.convert_tab.files.items}
        self.tabs.select(self.merge_tab)
        self.merge_tab.files.add(paths)
        for e in self.merge_tab.files.items:
            if turns.get(key(e.path)):
                e.turn = turns[key(e.path)]
                self.merge_tab.files.tree.set(e.iid, "turn", TURN_TEXT[e.turn])

    # ── 작업 ──────────────────────────────────────────────────
    def run(self, job, done) -> None:
        """job(session)을 뒤에서 돌리고, 끝나면 화면 쪽에서 done(결과, 오류)를 부른다.
        결과를 먼저 알리고, 문서를 바꾸느라 띄운 프로그램은 그 뒤에 닫는다."""
        session = core.Session(self.events.put, self.cache)
        self.session = session
        self._sessions.add(session)
        self._set_busy(True)

        def work() -> None:
            try:
                result, error = job(session), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            self.events.put(("finished", done, result, error))
            try:
                session.close()
            finally:
                self.events.put(("closed", session))

        threading.Thread(target=work, daemon=True, name="worker").start()

    def stop(self) -> None:
        if self.session is not None:
            self.session.stop()
            self.stop_btn.state(["disabled"])
            self.status("멈추는 중…", warn=True)

    def plan_targets(self, wanted: list[Path]) -> list[Path] | None:
        """저장할 파일 이름들. 이미 있는 파일이 있으면 덮어쓸지 물어보고, 같은 이름끼리는 (2), (3)…을 붙인다."""
        exists = [t for t in dict.fromkeys(wanted) if t.exists()]
        overwrite = False
        if exists:
            names = listing([t.name for t in exists], 5)
            answer = messagebox.askyesnocancel(
                TITLE, f"저장할 곳에 같은 이름의 PDF가 {len(exists)}개 있어요.\n{names}\n\n"
                       "[예] 덮어쓰기\n[아니요] 이름 뒤에 (2), (3)…을 붙여 따로 저장\n[취소] 그만두기", parent=self)
            if answer is None:
                return None
            overwrite = answer
        return naming.unique_targets(wanted, avoid_existing=not overwrite)

    def failed(self, error: Exception, flist: FileList | None) -> None:
        self.progress["value"] = 0
        if isinstance(error, core.Cancelled):
            self.status("중지했어요 (만들던 PDF는 저장하지 않았어요)", warn=True)
            return
        self.status("저장하지 못했어요", warn=True)
        if isinstance(error, core.ItemError):
            for e in (flist.items if flist else []):
                if key(e.path) == key(error.path):
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

    def finish_many(self, report: core.Report, noun: str, folder: Path | None = None) -> None:
        """여러 개를 만드는 작업이 끝났을 때 알린다"""
        self.progress["value"] = 100 if report.saved else 0
        if report.stopped and not report.saved and not report.failed:
            self.status("중지했어요 (만든 PDF는 없어요)", warn=True)
            return
        if report.saved:
            self.remember_save_dir(report.saved[0].parent)
        lines = [f"{noun} {len(report.saved)}개를 만들었어요."]
        if report.stopped:
            lines.append("중지해서 나머지는 만들지 않았어요.")
        if folder is not None and report.saved:
            lines.append(f"\n{folder}")
        if report.failed:
            lines += ["", f"만들지 못한 것 {len(report.failed)}개:", listing(report.failed)]
        text = "\n".join(lines)
        self.status(f"{noun} {len(report.saved)}개를 만들었어요"
                    + (f" · 만들지 못한 것 {len(report.failed)}개" if report.failed else "")
                    + (" · 중지함" if report.stopped else ""), warn=bool(report.failed or report.stopped))
        if report.saved:
            if messagebox.askyesno(TITLE, text + "\n\n저장한 폴더를 열어 볼까요?", parent=self):
                if folder is not None:
                    self.open_path(folder)
                else:
                    reveal(report.saved[0])
        else:
            messagebox.showwarning(TITLE, text, parent=self)

    # ── 상태 ──────────────────────────────────────────────────
    def inspect(self, flist: FileList, entries) -> None:
        """새로 넣은 파일의 쪽수를 뒤에서 센다 (열 수 없는 파일도 여기서 걸러진다)"""
        jobs = [(e.iid, e.path) for e in entries]

        def work() -> None:
            for iid, path in jobs:
                try:
                    pages, error = core.inspect(path), ""
                    if pages is None:
                        pages = self.cache.pages(path)
                except core.ItemError as exc:
                    pages, error = None, exc.reason
                except Exception as exc:  # noqa: BLE001
                    pages, error = None, core.reason_of(exc)
                self.events.put(("inspected", flist, iid, pages, error))

        threading.Thread(target=work, daemon=True).start()

    def status(self, text: str, warn: bool = False) -> None:
        self.status_var.set(text)
        self.status_label.configure(foreground=BAD if warn else "")

    def open_path(self, path: Path) -> None:
        try:
            os.startfile(path)  # noqa: S606 - 사용자가 고른 파일·폴더를 기본 프로그램으로 연다
        except OSError as exc:
            messagebox.showwarning(TITLE, f"열지 못했어요.\n{path}\n({exc})", parent=self)

    def _set_busy(self, busy: bool) -> None:
        for tab in self._tab_list():
            tab.set_busy(busy)
        if busy:
            self.progress["value"] = 0
            self.status("준비하는 중…")
            self.stop_btn.state(["!disabled"])
            self.stop_btn.grid(row=0, column=2, padx=(10, 0))
        else:
            self.stop_btn.grid_remove()
            self._step = None
            self._dialog = None

    def _show_step(self) -> None:
        if self._dialog is not None:
            label, title = self._dialog
            if label == "한글":  # 한글은 다른 폴더의 파일을 열 때 '접근 허용'을 묻는다
                self.status("한글이 확인 창을 띄웠어요. 파일 접근을 묻는 창이면 '모두 허용'을 누르면 이번 작업 동안 다시 묻지 않아요"
                            " · 멈추려면 [중지]", warn=True)
            else:
                self.status(f"{office.i_ga(label)} '{title}' 창을 띄웠어요. 그 창에서 버튼을 눌러 주세요 · 멈추려면 [중지]",
                            warn=True)
            return
        if self._step is None:
            return
        text, label, since = self._step
        if label:
            sec = int(time.monotonic() - since)
            text += f" — {label}로 PDF 만드는 중…" + (f" {sec}초" if sec >= 3 else "")
            if sec >= 30:
                text += f" (오래 걸리면 {label} 확인 창이 떠 있는지 봐 주세요)"
        self.status(text)

    def _poll(self) -> None:
        if self.drop is not None:
            for paths in self.drop.take():
                self.tabs.nametowidget(self.tabs.select()).drop(paths)
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "inspected":
                    _, flist, iid, pages, error = event
                    flist.set_pages(iid, pages, error)
                elif kind == "pages":
                    _, path, pages = event
                    for tab in self._tab_list():
                        for flist in tab.lists():
                            flist.set_doc_pages(key(path), pages)
                elif kind == "progress":
                    _, done, total, text, item_kind = event
                    if text is None:
                        self.progress["value"] = 100
                        self._step = ("PDF 파일로 저장하는 중…", None, time.monotonic())
                    else:
                        self.progress["value"] = done / max(1, total) * 100
                        label = office.APPS[item_kind].label if item_kind in office.APPS else None
                        self._step = (f"{done + 1}/{total} · {text}", label, time.monotonic())
                    self._show_step()
                elif kind == "dialog":
                    _, label, title = event
                    self._dialog = (label, title) if label else None
                    self._show_step()
                elif kind == "finished":
                    _, done, result, error = event
                    self.session = None
                    self._set_busy(False)
                    done(result, error)
                elif kind == "closed":
                    self._sessions.discard(event[1])
        except queue.Empty:
            pass
        if self._step is not None and self._step[1] and self._dialog is None:
            self._show_step()  # 문서를 바꾸는 동안 걸린 시간을 새로 쓴다
        if not self._closed:
            self._poll_id = self.after(250, self._poll)

    def _on_close(self) -> None:
        if self.session is not None and not messagebox.askyesno(
                TITLE, "아직 작업하는 중이에요. 그만두고 닫을까요?\n(지금 만들던 PDF는 저장되지 않아요)", parent=self):
            return
        self.destroy()

    def destroy(self) -> None:
        self._closed = True
        for session in list(self._sessions):
            session.stop()   # 띄워 둔 한글·오피스가 남지 않게 끈다
        try:
            self.after_cancel(self._poll_id)
        except (tk.TclError, AttributeError, ValueError):
            pass
        if getattr(self, "drop", None) is not None:
            self.drop.close()
        self.cache.clear()
        super().destroy()

    def report_callback_exception(self, exc, val, tb) -> None:  # 버튼 등에서 난 오류도 화면에 알린다
        self.status(f"오류: {exc.__name__}: {val}", warn=True)
        messagebox.showerror(TITLE, f"생각지 못한 오류가 났어요.\n\n{exc.__name__}: {val}", parent=self)


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App(sys.argv[1:]).mainloop()
