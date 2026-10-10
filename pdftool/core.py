"""실제 작업 (화면과 상관없음): 파일 종류·쪽수 알아보기, PDF로 바꾸기, 합치기, 저장"""
from __future__ import annotations

import os
import msvcrt
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Callable

import pikepdf
from PIL import UnidentifiedImageError

from . import images, office
from .images import IMAGE_EXTS, ImageOptions

PDF_EXTS = {".pdf"}
DOC_KINDS = set(office.APPS)
KIND_LABELS = {"pdf": "PDF", "image": "이미지", **{k: v.label for k, v in office.APPS.items()}}
TEMP_PREFIX = "PDF변환합치기_"


def _temp_dir(prefix: str):
    """사용 중인 임시 폴더는 다른 실행 창의 청소 작업이 지우지 못하게 잠근다."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    owner = (path / ".owner").open("w+b")
    owner.write(b"1")
    owner.flush()
    owner.seek(0)
    msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
    return path, owner

Notify = Callable[[tuple], None]  # 작업 스레드 → 화면으로 보내는 알림


class ItemError(Exception):
    """목록의 특정 파일 때문에 실패했을 때"""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path.name}: {reason}")
        self.path = path
        self.reason = reason


class SaveError(Exception):
    """결과 PDF를 저장하지 못했을 때"""


class Cancelled(Exception):
    """[중지]를 눌렀을 때"""


@dataclass
class Item:
    path: Path
    kind: str      # "pdf" / "image" / "hwp" / "word" / "excel" / "ppt"
    turn: int = 0  # 사용자가 돌린 각도 (시계 방향, 90의 배수)
    mark: str = ""  # 합칠 때 이 파일 첫 쪽에 달 책갈피 이름 ('' 이면 달지 않음)


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return office.DOC_EXTS.get(ext)


def usable_file(path: Path) -> bool:
    """폴더에서 파일을 모을 때 뺄 것: 숨김·시스템 파일, 오피스 잠금 파일(~$…), 저장 중인 임시 파일"""
    name = path.name
    if name.startswith("~$") or name.endswith(".저장중.pdf"):
        return False
    try:
        attrs = path.stat().st_file_attributes
    except (OSError, AttributeError):
        return True
    return not attrs & 0x6  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


def folder_files(folder: Path, kinds: set[str]) -> tuple[list[Path], list[Path]]:
    """폴더 바로 안의 파일 중 kinds 종류인 것과, 종류가 맞지 않아 뺀 것"""
    take, other = [], []
    for p in folder.iterdir():
        if not p.is_file() or not usable_file(p):
            continue
        (take if kind_of(p) in kinds else other).append(p)
    return take, other


def reason_of(exc: BaseException) -> str:
    """오류를 사용자에게 보여 줄 말로 바꾼다"""
    if isinstance(exc, ItemError):
        return exc.reason
    if isinstance(exc, office.DocError):
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return "파일이 없어요 (옮겨졌거나 지워졌을 수 있어요)"
    if isinstance(exc, PermissionError):
        return "파일을 열 수 없어요 (다른 프로그램에서 쓰는 중일 수 있어요)"
    if isinstance(exc, pikepdf.PasswordError):
        return "암호가 걸린 PDF라 열 수 없어요"
    if isinstance(exc, pikepdf.PdfError):
        return "PDF를 읽지 못했어요 (파일이 손상됐을 수 있어요)"
    if isinstance(exc, UnidentifiedImageError):
        return "이미지를 읽지 못했어요 (지원하지 않는 형식이거나 손상된 파일이에요)"
    if isinstance(exc, MemoryError):
        return "메모리가 부족해요 (이미지가 너무 커요)"
    if isinstance(exc, OSError):
        return f"파일을 읽지 못했어요 ({exc})"
    return str(exc) or type(exc).__name__


def inspect(path: Path) -> int | None:
    """쪽수를 센다. 문서(한글·워드…)는 바꿔 봐야 알 수 있어 None. 열 수 없으면 ItemError"""
    kind = kind_of(path)
    try:
        if kind == "pdf":
            with pikepdf.open(path) as pdf:
                return len(pdf.pages)
        if kind == "image":
            return images.count_pages(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        office.check(kind, path)
        return None
    except Exception as exc:  # noqa: BLE001
        raise ItemError(path, reason_of(exc)) from exc


# ── 문서 변환 결과 기억 ──────────────────────────────────────
class DocCache:
    """프로그램을 켜 둔 동안 문서를 PDF로 바꾼 결과를 기억한다 (같은 파일을 다시 바꾸지 않게).
    파일이 바뀌면(크기·수정 시각) 새로 바꾼다."""

    def __init__(self) -> None:
        self.dir, self._owner = _temp_dir(TEMP_PREFIX + "변환_")
        self._done: dict[tuple, tuple[Path, int]] = {}
        self._ids = count(1)
        self._lock = threading.Lock()

    @staticmethod
    def _key(path: Path) -> tuple:
        st = path.stat()
        return os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns

    def pages(self, path: Path) -> int | None:
        try:
            hit = self._done.get(self._key(path))
        except OSError:
            return None
        return hit[1] if hit else None

    def get(self, path: Path, make: Callable[[Path], None]) -> tuple[Path, int]:
        key = self._key(path)
        with self._lock:
            hit = self._done.get(key)
            if hit and hit[0].is_file():
                return hit
            dst = self.dir / f"{next(self._ids)}.pdf"
        make(dst)
        with pikepdf.open(dst) as pdf:
            pages = len(pdf.pages)
        if not pages:
            raise office.DocError("인쇄할 내용이 없어서 PDF가 비어 있어요")
        with self._lock:
            self._done[key] = (dst, pages)
        return dst, pages

    def clear(self) -> None:
        self._owner.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# ── 작업 한 번 ───────────────────────────────────────────────
class Session:
    """작업 한 번(작업 스레드 하나) 동안 쓰는 것: 진행 알림, 중지, 문서 변환 프로그램, 임시 폴더"""

    def __init__(self, notify: Notify, cache: DocCache) -> None:
        self.notify = notify
        self.cache = cache
        self.cancel = threading.Event()
        self.office = office.Office(on_dialog=lambda label, title: notify(("dialog", label, title)))
        self.work, self._owner = _temp_dir(TEMP_PREFIX)
        self._ids = count(1)

    def step(self, done: int, total: int, text: str | None, kind: str | None = None) -> None:
        """진행 알림 (text가 None이면 저장하는 중). [중지]를 눌렀으면 여기서 멈춘다."""
        if self.cancel.is_set():
            raise Cancelled
        self.notify(("progress", done, total, text, kind))

    def stop(self) -> None:
        self.cancel.set()
        self.office.stop()

    def close(self) -> None:
        try:
            self.office.close()
        finally:
            self._owner.close()
            shutil.rmtree(self.work, ignore_errors=True)

    def pdf_of(self, item: Item, opts: ImageOptions) -> Path:
        """item을 PDF 파일로: PDF는 원본 그대로, 이미지는 새로 만들고, 문서는 기억해 둔 결과를 쓰거나 새로 바꾼다"""
        if item.kind == "pdf":
            return item.path
        if item.kind == "image":
            part = self.work / f"{next(self._ids)}.pdf"
            part.write_bytes(images.image_pdf_bytes(item.path, opts, item.turn))
            return part
        try:
            path, pages = self.cache.get(item.path, lambda dst: self.office.to_pdf(item.kind, item.path, dst))
        except office.Stopped as exc:
            raise Cancelled from exc
        self.notify(("pages", item.path, pages))
        return path

    def append(self, dst: pikepdf.Pdf, item: Item, opts: ImageOptions, opened: list[pikepdf.Pdf]) -> int:
        """item의 쪽들을 dst 끝에 붙인다 (이미지가 아니면 사용자가 돌린 만큼 쪽을 돌린다)"""
        src = pikepdf.open(self.pdf_of(item, opts))
        opened.append(src)
        start = len(dst.pages)
        dst.pages.extend(src.pages)
        if item.kind != "image" and item.turn:
            for page in dst.pages[start:]:
                page.rotate(item.turn, relative=True)
        return start


def merge(session: Session, items: list[Item], opts: ImageOptions, target: Path) -> int:
    """items를 순서대로 PDF 1개로 합쳐 target에 저장하고 전체 쪽수를 돌려준다 (item.mark가 있으면 책갈피)"""
    return _merge(session, [("", items)], opts, target, step="item")


def merge_quiet(session: Session, items: list[Item], opts: ImageOptions, target: Path) -> int:
    """진행 알림 없이 합쳐서 저장 (여러 묶음을 만들 때 묶음 하나)"""
    return _merge(session, [("", items)], opts, target, step=None)


def merge_rows(session: Session, rows: list[tuple[str, list[Item]]], opts: ImageOptions, target: Path) -> int:
    """③ '모두 이어서 하나로': 줄들을 차례대로 PDF 1개로. 줄마다 책갈피(줄 이름)를 달고 그 아래에 파일 책갈피를 단다."""
    return _merge(session, rows, opts, target, step="row")


def _merge(session: Session, groups: list[tuple[str, list[Item]]], opts: ImageOptions, target: Path,
           step: str | None) -> int:
    """groups: [(줄 책갈피 이름 또는 '', 파일들)]. step: 진행 알림 단위 ("item" 파일마다 / "row" 줄마다 / None 없음)"""
    total = sum(len(items) for _, items in groups)
    with pikepdf.new() as dst:
        opened: list[pikepdf.Pdf] = []
        tree: list[tuple[str, int, list[tuple[str, int]]]] = []   # (줄 이름, 첫 쪽, [(파일 책갈피, 첫 쪽)])
        done = 0
        try:
            for g, (title, items) in enumerate(groups):
                if step == "row":
                    session.step(g, len(groups), title or items[0].path.name,
                                 next((it.kind for it in items if it.kind in DOC_KINDS), None))
                first = len(dst.pages)
                children = []
                for item in items:
                    if step == "item":
                        session.step(done, total, item.path.name, item.kind)
                    elif session.cancel.is_set():
                        raise Cancelled
                    done += 1
                    try:
                        start = session.append(dst, item, opts, opened)
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        raise ItemError(item.path, reason_of(exc)) from exc
                    if item.mark and len(dst.pages) > start:
                        children.append((item.mark, start))
                if len(dst.pages) > first:
                    tree.append((title, first, children))
            if not dst.pages:
                raise SaveError(f"{target.name}: 넣을 쪽이 하나도 없어요 (쪽이 없는 PDF만 들어 있어요)")
            if step is not None:
                count = len(groups) if step == "row" else total
                session.step(count, count, None)
            _bookmarks(dst, tree)
            store(target, _save_pdf(dst), cancel=session.cancel)
            return len(dst.pages)
        finally:
            for src in opened:
                src.close()


def _save_pdf(pdf: pikepdf.Pdf) -> Callable[[Path], object]:
    """PDF 저장 함수. 이미 메타데이터(XMP)가 든 PDF를 다시 저장할 때 pikepdf가 PDF 버전 표기를 고치려고
    lxml을 불러오는데, 그 기능만 끄면 lxml 없이 저장된다 (EXE에 lxml을 넣지 않기 위해)."""
    return lambda path: pdf.save(path, fix_metadata_version=False)


def _bookmarks(pdf: pikepdf.Pdf, tree: list[tuple[str, int, list[tuple[str, int]]]]) -> None:
    """합친 PDF에 책갈피를 단다 (PDF 보기 프로그램의 책갈피 칸에서 바로 찾아갈 수 있게).
    줄 이름이 있으면 줄 책갈피 아래에 파일 책갈피를 넣는다."""
    top: list[pikepdf.OutlineItem] = []
    for title, page, children in tree:
        kids = [pikepdf.OutlineItem(t, p) for t, p in children]
        if title:
            node = pikepdf.OutlineItem(title, page)
            node.children.extend(kids)
            top.append(node)
        else:
            top.extend(kids)
    if not top:
        return
    try:
        with pdf.open_outline() as outline:
            outline.root.clear()
            outline.root.extend(top)
    except Exception as exc:  # noqa: BLE001
        raise SaveError("책갈피를 만들지 못해서 저장하지 않았어요.") from exc


@dataclass
class Report:
    """여러 개를 만드는 작업의 결과"""
    saved: list[Path]
    failed: list[str]     # "파일 이름: 이유"
    stopped: bool = False


def convert_each(session: Session, plan: list[tuple[Item, Path]], opts: ImageOptions) -> Report:
    """파일마다 PDF 하나씩. 하나가 안 돼도 나머지는 계속한다."""
    report = Report([], [])
    for i, (item, target) in enumerate(plan):
        try:
            session.step(i, len(plan), item.path.name, item.kind)
            if item.kind == "image":
                data = images.image_pdf_bytes(item.path, opts, item.turn)
                store(target, lambda part: part.write_bytes(data), cancel=session.cancel)
            else:
                _save_doc(session, item, opts, target)
            report.saved.append(target)
        except Cancelled:
            report.stopped = True
            break
        except Exception as exc:  # noqa: BLE001
            report.failed.append(str(exc) if isinstance(exc, (ItemError, SaveError))
                                 else f"{item.path.name}: {reason_of(exc)}")
    return report


def _save_doc(session: Session, item: Item, opts: ImageOptions, target: Path) -> None:
    """문서 하나를 PDF 하나로. 프로그램이 만든 PDF를 그대로 쓴다 (책갈피 등이 남게), 돌렸으면 쪽만 돌린다."""
    try:
        made = session.pdf_of(item, opts)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ItemError(item.path, reason_of(exc)) from exc
    if not item.turn:
        store(target, lambda part: shutil.copyfile(made, part), cancel=session.cancel)
        return
    with pikepdf.open(made) as pdf:
        for page in pdf.pages:
            page.rotate(item.turn, relative=True)
        store(target, _save_pdf(pdf), cancel=session.cancel)


def merge_sets(session: Session, sets: list[tuple[list[Item], Path]], opts: ImageOptions) -> Report:
    """묶음마다 PDF 하나씩 (③ 폴더끼리 짝지어 합치기). 한 묶음이 안 돼도 나머지는 계속한다."""
    report = Report([], [])
    for i, (items, target) in enumerate(sets):
        try:
            session.step(i, len(sets), target.name, next((it.kind for it in items if it.kind in DOC_KINDS), None))
            merge_quiet(session, items, opts, target)
            report.saved.append(target)
        except Cancelled:
            report.stopped = True
            break
        except Exception as exc:  # noqa: BLE001
            reason = exc.reason if isinstance(exc, ItemError) else reason_of(exc)
            where = f" ({exc.path.name} 때문)" if isinstance(exc, ItemError) else ""
            report.failed.append(f"{target.name}: {reason}{where}")
    return report


def store(target: Path, write: Callable[[Path], object], *, cancel: threading.Event | None = None) -> None:
    """같은 폴더에 임시 이름으로 다 쓴 다음 바꿔 넣는다. 도중에 실패해도 반쯤 쓴 파일이 남지 않는다."""
    part = None
    try:
        if cancel is not None and cancel.is_set():
            raise Cancelled
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="~pdftool_", suffix=".저장중.pdf", dir=target.parent)
        os.close(fd)
        part = Path(name)
        write(part)
        if cancel is not None and cancel.is_set():
            raise Cancelled
        _replace(part, target)
    except Exception as exc:  # noqa: BLE001
        try:
            if part is not None:
                part.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, Cancelled):
            raise
        if isinstance(exc, PermissionError):
            reason = "저장하지 못했어요. 같은 이름의 PDF가 열려 있으면 닫고 다시 해 주세요."
        elif isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
            reason = "저장할 공간이 부족해요."
        else:
            reason = f"저장하지 못했어요 ({reason_of(exc)})"
        raise SaveError(f"{target.name}: {reason}") from exc


def _replace(part: Path, target: Path, tries: int = 10) -> None:
    """임시 파일을 결과 이름으로 바꾼다. 백신·검색 색인이나 다른 저장이 결과 파일을 잠깐 붙잡고 있으면
    Windows가 '접근 거부'를 내므로 조금 기다렸다 다시 해 본다 (PDF 보기 프로그램이 열고 있으면 결국 실패한다)."""
    for attempt in range(tries):
        try:
            os.replace(part, target)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.1 + 0.05 * attempt)


def clean_old_temp(hours: float = 6) -> None:
    """오래됐고 사용 중이 아님을 확인한 임시 폴더만 지운다. 구버전의 표식 없는 폴더는 건드리지 않는다."""
    base = Path(tempfile.gettempdir())
    for p in base.glob(TEMP_PREFIX + "*"):
        try:
            if p.is_symlink() or time.time() - p.stat().st_mtime <= hours * 3600:
                continue
            with (p / ".owner").open("r+b") as owner:
                msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
            shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
