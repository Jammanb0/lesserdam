"""③ 폴더끼리 짝지어 합치기: 폴더마다 정한 순서로 파일을 늘어놓고 같은 자리(n번째)끼리 묶는다

예) 한글\\가.pdf + 영어\\A.pdf + 숫자\\1.pdf → 1번째 묶음, 나 + B + 2 → 2번째 묶음 …
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import core, sorting

KIND_SETS = {
    "pdf": ({"pdf"}, "PDF만"),
    "pdf_image": ({"pdf", "image"}, "PDF와 이미지"),
    "all": ({"pdf", "image", *core.DOC_KINDS}, "PDF로 바꿀 수 있는 파일 모두 (한글·워드 등 포함)"),
}
UNTIL = {
    "shortest": "모든 폴더에 파일이 있는 데까지만 만들기",
    "longest": "끝까지 만들기 (파일이 없는 폴더는 빼고 합치기)",
}


@dataclass
class Folder:
    path: Path
    files: list[Path] = field(default_factory=list)   # 넣을 파일 (정한 순서)
    other: list[Path] = field(default_factory=list)   # 종류가 안 맞아 뺀 파일
    error: str = ""                                   # 폴더를 읽지 못했을 때

    @property
    def name(self) -> str:
        return self.path.name or str(self.path)


def scan(path: Path, kinds: set[str], order: str, reverse: bool) -> Folder:
    folder = Folder(path)
    try:
        take, other = core.folder_files(path, kinds)
    except OSError as exc:
        folder.error = f"폴더를 열 수 없어요 ({exc.strerror or exc})"
        return folder
    folder.files = sorting.sort_paths(take, order, reverse)
    folder.other = other
    return folder


def row_count(folders: list[Folder], until: str) -> int:
    """만들 묶음 수"""
    counts = [len(f.files) for f in folders if not f.error]
    if not counts:
        return 0
    return min(counts) if until == "shortest" else max(counts)


def rows(folders: list[Folder]) -> list[list[Path | None]]:
    """가장 긴 폴더까지 n번째 줄마다 폴더별 파일 (없으면 None)"""
    longest = max((len(f.files) for f in folders), default=0)
    return [[f.files[i] if i < len(f.files) else None for f in folders] for i in range(longest)]


def first_gap(folders: list[Folder]) -> int | None:
    """어느 폴더든 파일이 처음으로 없는 줄 번호 (0부터). 개수가 모두 같으면 None"""
    counts = [len(f.files) for f in folders]
    if len(set(counts)) <= 1:
        return None
    return min(counts)
