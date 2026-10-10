"""설정 칸: 이미지 넣는 방법, 결과 파일 이름 짓기"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..images import ImageOptions
from .. import naming
from ..naming import DIGITS, MIDDLES, NUMBERS, SEPARATORS, NameRule, Split
from .common import BAD, HINT, TITLE, options_row


class ImageOptionsBox(ttk.LabelFrame):
    """쪽 크기 · 용지 방향 · 돌려서 크게 넣기"""

    def __init__(self, parent, note: str = "") -> None:
        super().__init__(parent, text=f" 이미지 넣는 방법{f' ({note})' if note else ''} ", padding=(10, 4))
        self.page = tk.StringVar(value="a4")
        self.orient = tk.StringVar(value="auto")
        self.fit = tk.BooleanVar(value=False)
        options_row(self, 0, "쪽 크기", self.page, (("a4", "A4에 맞춤"), ("original", "원본 크기")))
        self._orients = options_row(self, 1, "용지 방향", self.orient,
                                    (("auto", "자동"), ("portrait", "세로"), ("landscape", "가로")))
        self._fit = ttk.Checkbutton(self, text="방향이 다른 이미지는 90° 눕혀서 크게 넣기", variable=self.fit)
        self._fit.grid(row=2, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=2)
        self.hint = ttk.Label(self, foreground=HINT, wraplength=340, justify="left")
        self.hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 2))
        for var in (self.page, self.orient, self.fit):
            var.trace_add("write", lambda *_: self._update())
        self._update()

    def get(self) -> ImageOptions:
        return ImageOptions(self.page.get(), self.orient.get(), bool(self.fit.get()))

    def set(self, opts: ImageOptions) -> None:
        self.page.set(opts.page)
        self.orient.set(opts.orient)
        self.fit.set(opts.fit_turn)

    def _update(self) -> None:
        a4 = self.page.get() == "a4"
        for r in self._orients:
            r.state(["!disabled"] if a4 else ["disabled"])
        forced = a4 and self.orient.get() != "auto"
        self._fit.state(["!disabled"] if forced else ["disabled"])
        if not a4:
            text = "이미지 크기 그대로 쪽을 만들어요. (사진은 쪽이 아주 커요)"
        elif not forced:
            text = "가로로 긴 이미지는 가로 A4, 세로로 긴 이미지는 세로 A4에 비율 그대로 맞춰요."
        else:
            side = "세로" if self.orient.get() == "portrait" else "가로"
            other = "가로" if side == "세로" else "세로"
            how = "90° 눕혀서 크게" if self.fit.get() else "그대로 세워서 작게"
            text = f"모든 쪽을 {side} A4로 만들어요. {other}로 긴 이미지는 {how} 넣어요."
        self.hint.configure(text=text)


class NamingBox(ttk.LabelFrame):
    """결과 파일 이름 = [번호] 앞에 붙일 말 + 가운데(원래 이름 / 원래 이름에서 구간 선택) + 뒤에 붙일 말 [번호]

    on_change(): 무엇이든 바뀌면. 주인은 이름들을 나눈 결과를 set_split으로 알려 주고 예시를 새로 그린다.
    reference_label: ③ 탭처럼 결과 이름의 기준 폴더를 고르게 할 때 그 칸의 이름
    show_parts: False면 '다른 부분'의 구간 체크칸을 보이지 않는다 (이름 묶음이 여럿이라 한 짜임으로 고를 수 없을 때)"""

    PER_ROW = 5   # 구간 체크칸을 한 줄에 몇 개까지 놓을지

    def __init__(self, parent, on_change: Callable[[], None], default: NameRule | None = None,
                 reference_label: str = "", show_parts: bool = True, title: str = "저장할 파일 이름") -> None:
        super().__init__(parent, text=f" {title} ", padding=(10, 4))
        rule = default or NameRule()
        self.on_change = on_change
        self.show_parts = show_parts
        self.split = Split()
        self._signature: tuple | None = None
        self._keep: list[tk.BooleanVar] = []
        self._checks: list[ttk.Checkbutton] = []
        self._quiet = False
        self.before = tk.StringVar(value=rule.before)
        self.middle = tk.StringVar(value=MIDDLES[rule.middle])
        self.after = tk.StringVar(value=rule.after)
        self.number = tk.StringVar(value=NUMBERS[rule.number])
        self.start = tk.StringVar(value=str(rule.start))
        self.digits = tk.StringVar(value=DIGITS[rule.digits])
        self.separator = tk.StringVar(value=SEPARATORS.get(rule.separator, rule.separator))
        self.reference = tk.StringVar()
        style = ttk.Style(self)
        style.configure("Diff.TCheckbutton", foreground="#0b57d0")
        style.configure("Same.TCheckbutton", foreground=HINT)

        row0 = ttk.Frame(self)
        row0.grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(row0, text="앞에 붙일 말").pack(side="left")
        ttk.Entry(row0, textvariable=self.before, width=12).pack(side="left", padx=(6, 6))
        ttk.Label(row0, text="+").pack(side="left")
        ttk.Combobox(row0, textvariable=self.middle, values=list(MIDDLES.values()), state="readonly",
                     width=27).pack(side="left", padx=6)
        ttk.Label(row0, text="+  뒤에 붙일 말").pack(side="left")
        ttk.Entry(row0, textvariable=self.after, width=12).pack(side="left", padx=(6, 0))

        row1 = ttk.Frame(self)  # (결과 이름의 기준 폴더) + 번호
        row1.grid(row=1, column=0, sticky="w", pady=2)
        if reference_label:
            ttk.Label(row1, text=reference_label).pack(side="left")
            self.reference_box = ttk.Combobox(row1, textvariable=self.reference, state="readonly", width=24)
            self.reference_box.pack(side="left", padx=(6, 18))
        ttk.Label(row1, text="번호").pack(side="left")
        ttk.Combobox(row1, textvariable=self.number, values=list(NUMBERS.values()), state="readonly",
                     width=8).pack(side="left", padx=(6, 6))
        self.start_box = ttk.Spinbox(row1, from_=0, to=99999, textvariable=self.start, width=6)
        self.start_box.pack(side="left")
        ttk.Label(row1, text="부터,").pack(side="left", padx=(4, 6))
        self.digits_box = ttk.Combobox(row1, textvariable=self.digits, values=list(DIGITS.values()),
                                       state="readonly", width=14)
        self.digits_box.pack(side="left")

        row2 = ttk.Frame(self)
        row2.grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(row2, text="번호와 이름 사이").pack(side="left")
        self.separator_box = ttk.Combobox(row2, textvariable=self.separator,
                                           values=list(SEPARATORS.values()), width=20)
        self.separator_box.pack(side="left", padx=(6, 10))
        ttk.Label(row2, text="목록에서 고르거나 직접 입력해요", foreground=HINT).pack(side="left")

        # 원래 이름에서 구간 선택: 구간마다 체크칸 (파랑: 이름마다 다른 구간, 회색: 모든 이름에 똑같은 구간)
        self.row_parts = ttk.Frame(self)
        ttk.Label(self.row_parts, text="넣을 구간").grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=1)
        self.parts_box = ttk.Frame(self.row_parts)
        self.parts_box.grid(row=0, column=1, sticky="w")
        ttk.Button(self.row_parts, text="처음대로", command=self._reset_parts).grid(
            row=0, column=2, sticky="nw", padx=(10, 0))
        ttk.Label(self.row_parts, foreground=HINT,
                  text="파란 글씨는 이름마다 다른 구간, 회색은 모든 이름에 똑같은 구간이에요. "
                       "체크한 구간만 이름에 넣어요.").grid(row=1, column=0, columnspan=3, sticky="w")
        if not show_parts:  # 폴더마다 이름 짜임이 달라 한 번에 고를 수 없다
            for w in self.row_parts.winfo_children():
                w.grid_remove()
            ttk.Label(self.row_parts, foreground=HINT,
                      text="폴더마다 이름에서 다른 구간을 찾아 넣어요 (모든 이름에 똑같은 구간은 빼요).").grid(
                row=0, column=0, sticky="w")
        self.parts_empty = ttk.Label(self.parts_box, text="파일을 넣으면 여기에 이름의 구간이 보여요",
                                     foreground=HINT)

        self.example = ttk.Label(self, foreground=HINT, wraplength=560, justify="left")
        self.example.grid(row=4, column=0, sticky="w", pady=(2, 2))

        for var in (self.before, self.middle, self.after, self.number, self.start, self.digits,
                    self.separator, self.reference):
            var.trace_add("write", lambda *_: self._changed())
        self._show_parts()
        self._layout()

    def rule(self) -> NameRule:
        middle = next(k for k, v in MIDDLES.items() if v == self.middle.get())
        number = next(k for k, v in NUMBERS.items() if v == self.number.get())
        digits = next(k for k, v in DIGITS.items() if v == self.digits.get())
        try:
            start = max(0, int(self.start.get()))
        except ValueError:
            start = 1
        keep = tuple(i for i, var in enumerate(self._keep) if var.get()) if self._keep else None
        separator = next((s for s, label in SEPARATORS.items() if label == self.separator.get()), self.separator.get())
        return NameRule(self.before.get(), middle, self.after.get(), keep, number, start, digits, separator)

    def set_rule(self, rule: NameRule) -> None:
        self._quiet = True
        try:
            self.before.set(rule.before)
            self.middle.set(MIDDLES.get(rule.middle, MIDDLES["name"]))
            self.after.set(rule.after)
            self.number.set(NUMBERS.get(rule.number, NUMBERS["none"]))
            self.start.set(str(rule.start))
            self.digits.set(DIGITS.get(rule.digits, DIGITS[1]))
            self.separator.set(SEPARATORS.get(rule.separator, rule.separator))
        finally:
            self._quiet = False
        self._changed()

    def set_split(self, split: Split) -> None:
        """이름들을 나눈 결과를 받는다. 구간 짜임이 그대로면 사용자가 고른 체크를 그대로 둔다.
        주인이 예시를 그리는 도중에 부르므로 주인에게 다시 알리지 않는다."""
        self.split = split
        signature = split.signature()
        if signature == self._signature:
            for check, part in zip(self._checks, split.parts):
                check.configure(text=_short(part.sample))  # 보기 글자만 새로
            return
        self._signature = signature
        self._show_parts()

    def set_example(self, names: list[str], note: str = "", warn: bool = False, suffix: str = ".pdf") -> None:
        shown = " · ".join(f"{n}{suffix}" for n in names[:3])
        more = f" … (모두 {len(names)}개)" if len(names) > 3 else ""
        text = f"예) {shown}{more}" if names else ""
        if note:
            text = f"{text}\n{note}" if text else note
        self.example.configure(text=text, foreground=BAD if warn else HINT)

    def uses_parts(self) -> bool:
        return self.middle.get() == MIDDLES["diff"]

    def _show_parts(self) -> None:
        """구간 체크칸을 새로 만든다 (처음엔 이름마다 다른 구간만 체크)"""
        for check in self._checks:
            check.destroy()
        self._checks, self._keep = [], []
        if not self.show_parts:
            return
        chosen = self.split.default_keep()
        for i, part in enumerate(self.split.parts):
            var = tk.BooleanVar(value=i in chosen)
            var.trace_add("write", lambda *_: self._changed())
            check = ttk.Checkbutton(self.parts_box, text=_short(part.sample), variable=var,
                                    style="Same.TCheckbutton" if part.same else "Diff.TCheckbutton")
            check.grid(row=i // self.PER_ROW + 1, column=i % self.PER_ROW, sticky="w", padx=(0, 12))
            self._checks.append(check)
            self._keep.append(var)
        if self._checks:
            self.parts_empty.grid_remove()
        else:
            self.parts_empty.grid(row=0, column=0, sticky="w")

    def _reset_parts(self) -> None:
        chosen = self.split.default_keep()
        self._quiet = True
        try:
            for i, var in enumerate(self._keep):
                var.set(i in chosen)
        finally:
            self._quiet = False
        self._changed()

    def _layout(self) -> None:
        if self.uses_parts():
            self.row_parts.grid(row=3, column=0, sticky="w", pady=2)
        else:
            self.row_parts.grid_remove()
        numbered = self.number.get() != NUMBERS["none"]
        for w in (self.start_box, self.digits_box, self.separator_box):
            w.state(["!disabled"] if numbered else ["disabled"])

    def _changed(self) -> None:
        self._layout()
        if not self._quiet:
            self.on_change()


def _short(text: str, limit: int = 24) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


BOOKMARK_MODES = {"folder": "폴더 이름", "name": "원래 파일 이름", "rule": "사용자 지정 이름 규칙", "none": "달지 않음"}


class BookmarkBox(ttk.Frame):
    """[방식 ▼] [이름 규칙 정하기…] — 합친 PDF에서 파일마다 달 책갈피 이름 (폴더 이름 / 원래 파일 이름 / 정한 규칙 / 달지 않음)

    dialog_split(): 이름 규칙 정하기 창에서 구간 체크칸에 쓸 '이름들을 나눈 결과' (없으면 None → 체크칸 없이)
    preview(규칙, 나눈 결과): 이름 규칙 정하기 창의 미리 보기 [(원래 이름, 책갈피 이름)]"""

    def __init__(self, parent, modes: list[str], on_change: Callable[[], None],
                 dialog_split: Callable[[], Split | None],
                 preview: Callable[[NameRule, Split | None], list[tuple[str, str]]]) -> None:
        super().__init__(parent)
        self.on_change = on_change
        self.dialog_split = dialog_split
        self.preview = preview
        self.rule = NameRule(middle="name")
        self.mode = tk.StringVar(value=BOOKMARK_MODES[modes[0]])
        ttk.Combobox(self, textvariable=self.mode, values=[BOOKMARK_MODES[m] for m in modes], state="readonly",
                     width=25).pack(side="left")
        self.edit_btn = ttk.Button(self, text="이름 규칙 정하기…", command=self.edit)
        self.edit_btn.pack(side="left", padx=(6, 0))
        self.mode.trace_add("write", lambda *_: self._mode_changed())
        self._update_edit_state()

    def _update_edit_state(self) -> None:
        self.edit_btn.state(["!disabled"] if self.mode_key() == "rule" else ["disabled"])

    def _mode_changed(self) -> None:
        self._update_edit_state()
        self.on_change()

    def mode_key(self) -> str:
        return next(k for k, v in BOOKMARK_MODES.items() if v == self.mode.get())

    def titles(self, stems: list[str], folder_names: list[str], splits: list[Split | None]) -> list[str]:
        """파일마다 책갈피 이름 ('' = 달지 않음). 번호는 이 목록 안의 차례로 붙는다.
        splits[i]: i번째 이름이 속한 묶음을 나눈 결과 ('원래 이름에서 구간 선택'용)"""
        mode = self.mode_key()
        if mode == "none":
            return [""] * len(stems)
        if mode == "folder":
            return [f or s for f, s in zip(folder_names, stems)]
        if mode == "name":
            return list(stems)
        return [naming.make(self.rule, s, i, sp) or s for i, (s, sp) in enumerate(zip(stems, splits))]

    def edit(self) -> None:
        if self.mode_key() != "rule":
            return
        dialog = BookmarkDialog(self, self.rule, self.dialog_split(), self.preview)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.rule = dialog.result
            self.on_change()


class BookmarkDialog(tk.Toplevel):
    """책갈피 이름 규칙 정하기: ③의 이름 짓기와 같은 방식 + 미리 보기"""

    def __init__(self, parent, rule: NameRule, split: Split | None,
                 preview: Callable[[NameRule, Split | None], list[tuple[str, str]]]) -> None:
        super().__init__(parent)
        self.title(f"책갈피 이름 규칙 정하기 — {TITLE}")
        self.transient(parent.winfo_toplevel())
        self.result: NameRule | None = None
        self.preview = preview
        self.split = split
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="합친 PDF의 책갈피 칸에 보일 이름을 정해요. 원래 파일 이름은 바뀌지 않아요.").pack(anchor="w")
        self.naming = NamingBox(body, on_change=self._redraw, default=rule, show_parts=split is not None,
                                title="책갈피 이름")
        self.naming.pack(fill="x", pady=(8, 0))
        box = ttk.LabelFrame(body, text=" 미리 보기 (원래 이름 → 책갈피 이름) ", padding=(8, 4))
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.list = tk.Listbox(box, height=9, activestyle="none", borderwidth=0, highlightthickness=0)
        self.list.pack(fill="both", expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="확인", style="Accent.TButton", command=self._ok).pack(side="right", padx=(0, 6))
        self.bind("<Escape>", lambda e: self.destroy())
        self._redraw()
        self.update_idletasks()
        top = parent.winfo_toplevel()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - self.winfo_reqwidth()) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_set()

    def _redraw(self) -> None:
        if self.split is not None and self.naming.uses_parts():
            self.naming.set_split(self.split)
        pairs = self.preview(self.naming.rule(), self.naming.split if self.split is not None else None)
        self.list.delete(0, "end")
        for original, title in pairs[:40]:
            self.list.insert("end", f"{original}  →  {title or '(이름이 비어 원래 이름을 써요)'}")
        if len(pairs) > 40:
            self.list.insert("end", f"… 모두 {len(pairs)}개")
        if not pairs:
            self.list.insert("end", "파일을 넣으면 여기에 보여요")

    def _ok(self) -> None:
        self.result = self.naming.rule()
        self.destroy()
