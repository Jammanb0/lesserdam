"""저장할 파일 이름 짓기

이름 = [번호] + 앞에 붙일 말 + (원래 이름 / 원래 이름에서 구간 선택) + 뒤에 붙일 말 + [번호]

'원래 이름에서 구간 선택': 이름들을 띄어쓰기 단위로 나눠 모든 이름에 똑같이 있는 구간과 이름마다 다른 구간을 찾고,
고른 구간만 남긴다 (처음엔 다른 구간만). 똑같은 구간이 앞·가운데·뒤 어디에 몇 개 있어도 된다.
예) 가상도 예제시 샘플구 가상가동 143 토지대장 9001 시험
    → [가상도 예제시 샘플구] 가상가동 143 [토지대장] 9001 [시험] → 가상가동 143 9001
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MIDDLES = {"name": "원래 이름", "diff": "원래 이름에서 구간 선택", "none": "넣지 않음"}
NUMBERS = {"none": "안 붙임", "front": "맨 앞에", "back": "맨 뒤에"}
DIGITS = {1: "1, 2, 3", 2: "01, 02, 03", 3: "001, 002, 003", 4: "0001, 0002"}
SEPARATORS = {" ": "공백", ". ": "마침표 + 공백 (.)", "_": "밑줄 (_)", "-": "하이픈 (-)", "": "없음"}
MAX_STEM = 150  # 경로가 너무 길면 저장이 안 될 수 있어 이름 길이를 줄인다

_GLUE = " _-.()[]{}~,"            # 이 글자로 끝나거나 시작하면 사이에 띄어쓰기를 넣지 않는다
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_WORD = re.compile(r"[^\s_]+")   # 낱말: 띄어쓰기와 _ 사이 (805-1, 산45, (열람용)은 나누지 않는다)


@dataclass
class NameRule:
    before: str = ""          # 앞에 붙일 말
    middle: str = "name"      # MIDDLES 중 하나
    after: str = ""           # 뒤에 붙일 말
    keep: tuple[int, ...] | None = None   # 다른 부분: 넣을 구간 번호 (None이면 이름마다 다른 구간 모두)
    number: str = "none"      # NUMBERS 중 하나
    start: int = 1
    digits: int = 1
    separator: str = " "      # 번호와 나머지 이름 사이에 넣을 문자


@dataclass
class Part:
    same: bool     # 모든 이름에 똑같이 있는 구간인지
    sample: str    # 보기로 보여 줄 글자 (첫 이름에서, 그 이름에 없으면 있는 이름에서)


@dataclass
class Split:
    """이름들을 구간으로 나눈 결과"""
    parts: list[Part] = field(default_factory=list)
    pieces: dict[str, list[str]] = field(default_factory=dict)   # 이름 → 구간마다 글자 ('' = 그 이름엔 없음)

    def default_keep(self) -> tuple[int, ...]:
        return tuple(i for i, p in enumerate(self.parts) if not p.same)

    def pick(self, stem: str, keep: tuple[int, ...] | None) -> str:
        """고른 구간만 이어 붙인 이름. 나눌 때 없던 이름이면 원래 이름 그대로"""
        pieces = self.pieces.get(stem)
        if pieces is None:
            return stem
        chosen = self.default_keep() if keep is None else keep
        return _glue([p for i, p in enumerate(pieces) if i in chosen])

    def signature(self) -> tuple:
        """구간 짜임. 짜임이 같으면 사용자가 고른 구간을 그대로 둔다."""
        return tuple((p.same, p.sample if p.same else "") for p in self.parts)


def split_names(stems: list[str]) -> Split:
    """이름들을 '모두 똑같은 구간'과 '이름마다 다른 구간'으로 차례대로 나눈다"""
    stems = [s for s in dict.fromkeys(stems) if s]
    if not stems:
        return Split()
    words = {s: [(m.group(), m.start(), m.end()) for m in _WORD.finditer(s)] for s in stems}
    common: list[str] = []
    if len(stems) > 1:  # 이름이 하나뿐이면 무엇이 같은지 알 수 없다 → 통째로 다른 구간
        common = [w for w, _, _ in words[stems[0]]]
        for s in stems[1:]:
            common = _lcs(common, [w for w, _, _ in words[s]])
    where: dict[str, list[int]] = {}   # 이름마다 같은 낱말이 몇 번째 낱말인지
    for s in stems:
        pos, j = [], 0
        for w in common:
            while words[s][j][0] != w:
                j += 1
            pos.append(j)
            j += 1
        where[s] = pos
    m = len(common)

    def gap(s: str, g: int) -> str:
        """g번째 같은 낱말 앞의 틈 (g == m이면 마지막 같은 낱말 뒤)"""
        ws, pos = words[s], where[s]
        a = pos[g - 1] + 1 if g > 0 else 0
        b = pos[g] if g < m else len(ws)
        return s[ws[a][1]:ws[b - 1][2]] if a < b else ""

    # 차례: 틈0, 같은0, 틈1, 같은1, …, 틈m. 모든 이름에서 빈 틈은 빼고, 이어지는 같은 낱말은 한 구간으로 묶는다
    plan: list[tuple[str, list[int]]] = []
    for g in range(m + 1):
        if any(gap(s, g) for s in stems):
            plan.append(("gap", [g]))
        if g < m:
            if plan and plan[-1][0] == "same":
                plan[-1][1].append(g)
            else:
                plan.append(("same", [g]))
    pieces = {}
    for s in stems:
        ws, pos = words[s], where[s]
        pieces[s] = [gap(s, idx[0]) if kind == "gap" else s[ws[pos[idx[0]]][1]:ws[pos[idx[-1]]][2]]
                     for kind, idx in plan]
    parts = [Part(kind == "same", next((pieces[s][i] for s in stems if pieces[s][i]), ""))
             for i, (kind, _) in enumerate(plan)]
    return Split(parts, pieces)


def _lcs(a: list[str], b: list[str]) -> list[str]:
    """두 낱말 줄에 차례대로 함께 있는 가장 긴 낱말들"""
    n, k = len(a), len(b)
    table = [[0] * (k + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(k - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    out, i, j = [], 0, 0
    while i < n and j < k:
        if a[i] == b[j]:
            out.append(a[i])
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def make(rule: NameRule, stem: str | None, index: int, split: Split | None = None) -> str:
    """index번째(0부터) 결과의 이름 (확장자 없이). 쓸 수 없는 글자는 _로 바꾼다.
    split: '원래 이름에서 구간 선택'을 쓸 때 이름들을 나눈 결과"""
    if rule.middle == "name":
        middle = stem or ""
    elif rule.middle == "diff":
        middle = split.pick(stem or "", rule.keep) if split is not None else (stem or "")
    else:
        middle = ""
    # 앞뒤 문구의 공백은 사용자가 입력한 대로 연결한다.
    name = rule.before + middle + rule.after
    if rule.number != "none":
        number = str(rule.start + index).zfill(max(1, rule.digits))
        if not name:
            name = number
        elif rule.number == "front":
            name = number + rule.separator + name
        else:
            name = name + rule.separator + number
    return safe_name(name)


def _glue(parts: list[str]) -> str:
    out = ""
    for p in parts:
        if not p:
            continue
        if out and out[-1] not in _GLUE and p[0] not in _GLUE:
            out += " "
        out += p
    return out


def safe_name(text: str) -> str:
    """파일 이름으로 쓸 수 없는 글자를 _로 바꾸고, 끝의 점·띄어쓰기를 지운다"""
    name = _BAD.sub("_", text).strip().rstrip(". ")
    if len(name) > MAX_STEM:
        name = name[:MAX_STEM].rstrip(". ")
    if name.split(".")[0].upper() in _RESERVED:
        name += "_"
    return name


def _cut_ok(s: str, i: int) -> bool:
    """s[:i] | s[i:] 사이를 끊어도 되는 자리인지. 낱말·숫자 중간(예: 805-1의 '-' 앞뒤)은 끊지 않는다."""
    if i <= 0 or i >= len(s):
        return i == 0
    a, b = s[i - 1], s[i]
    return (a.isspace() or b.isspace() or a == "_" or b == "_" or a in ")]}" or b in "([{"
            or (a.isalpha() and b.isdigit()) or (a.isdigit() and b.isalpha()))


def merged_default(stems: list[str]) -> str:
    """② 합치기에서 저장할 때 미리 넣어 둘 이름: 모든 이름의 앞쪽 같은 부분(없으면 첫 파일 이름) + _합본"""
    base = stems[0] if stems else "합본"
    if len(stems) > 1:
        front = os.path.commonprefix(stems)
        while front and not all(_cut_ok(s, len(front)) or len(s) == len(front) for s in stems):
            front = front[:-1]
        front = front.strip(" _-(")
        if len(front) >= 2:
            base = front
    return safe_name(f"{base}_합본")


def unique_targets(wanted: list[Path], avoid_existing: bool) -> list[Path]:
    """같은 폴더에 같은 이름이 겹치면 '이름 (2).pdf'처럼 바꾼다. avoid_existing이면 이미 있는 파일도 피한다."""
    taken: set[str] = set()
    out = []
    for target in wanted:
        t, n = target, 1
        while os.path.normcase(str(t)) in taken or (avoid_existing and t.exists()):
            n += 1
            t = target.with_name(f"{target.stem} ({n}){target.suffix}")
        taken.add(os.path.normcase(str(t)))
        out.append(t)
    return out
