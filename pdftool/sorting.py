"""파일 늘어놓는 순서 (BatchNamer처럼 여러 기준). 날짜·쪽수를 모르는 파일은 늘 맨 뒤에 이름순으로 둔다."""
from __future__ import annotations

import ctypes
import functools
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

ORDERS = {
    "name": "이름",
    "modified": "수정한 날짜",
    "created": "만든 날짜",
    "taken": "찍은 날짜 (사진)",
    "size": "크기",
    "ext": "종류 (확장자)",
    "pages": "쪽수",
    "folder": "폴더 위치",
}


def direction_labels(order: str) -> tuple[str, str]:
    """(오름차순, 내림차순)을 기준에 맞는 말로"""
    if order in ("modified", "created", "taken"):
        return "오름차순 (오래된 것부터)", "내림차순 (최근 것부터)"
    if order == "size":
        return "오름차순 (작은 것부터)", "내림차순 (큰 것부터)"
    if order == "pages":
        return "오름차순 (적은 것부터)", "내림차순 (많은 것부터)"
    return "오름차순 (1→9, 가→하)", "내림차순 (하→가, 9→1)"


_cmp = ctypes.windll.shlwapi.StrCmpLogicalW
_cmp.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
_cmp.restype = ctypes.c_int
explorer_order = functools.cmp_to_key(_cmp)  # 탐색기 '이름' 정렬과 같은 순서 (2 다음에 10)

_EXIF_IFD, _TAKEN, _DIGITIZED, _DATETIME = 0x8769, 0x9003, 0x9004, 0x0132


@dataclass
class Stat:
    size: int
    modified: float
    created: float


def stat(path: Path) -> Stat | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return Stat(st.st_size, st.st_mtime, getattr(st, "st_birthtime", st.st_ctime))


def taken_date(path: Path) -> datetime | None:
    """사진을 찍은 날짜 (EXIF). 없으면 None"""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            value = exif.get_ifd(_EXIF_IFD).get(_TAKEN) or exif.get_ifd(_EXIF_IFD).get(_DIGITIZED) or exif.get(_DATETIME)
    except Exception:  # noqa: BLE001
        return None
    try:
        return datetime.strptime(str(value).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def name_key(path: Path):
    return explorer_order(path.name), explorer_order(str(path.parent))


def sort_paths(paths: list[Path], order: str, reverse: bool = False,
               pages: dict[str, int | None] | None = None,
               cache: dict[str, object] | None = None) -> list[Path]:
    """paths를 order 기준으로 늘어놓는다. pages: 경로 → 쪽수 (모르면 None). cache: 같은 파일 정보를 다시 읽지 않게."""
    cache = {} if cache is None else cache

    def value(p: Path):
        k = f"{order}|{os.path.normcase(str(p))}"
        if k not in cache:
            cache[k] = _value(p, order, pages)
        return cache[k]

    known = [p for p in paths if value(p) is not None]
    unknown = [p for p in paths if value(p) is None]
    known.sort(key=lambda p: (value(p), name_key(p)), reverse=reverse)
    unknown.sort(key=name_key)
    return known + unknown


def _value(p: Path, order: str, pages: dict[str, int | None] | None):
    if order == "name":
        return explorer_order(p.name), explorer_order(str(p.parent))
    if order == "folder":
        return explorer_order(str(p.parent)), explorer_order(p.name)
    if order == "ext":
        return p.suffix.lower(), explorer_order(p.name)
    if order == "pages":
        return None if pages is None else pages.get(os.path.normcase(str(p)))
    if order == "taken":
        return taken_date(p)
    st = stat(p)
    if st is None:
        return None
    return {"modified": st.modified, "created": st.created, "size": st.size}[order]
