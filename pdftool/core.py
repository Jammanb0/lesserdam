"""이미지 → PDF 변환과 PDF 합치기 (화면과 상관없는 실제 작업)"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

import img2pdf
import pikepdf
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = None  # 큰 스캔 이미지도 연다 (내 PC에 있는 파일만 다룸)
logging.getLogger("img2pdf").setLevel(logging.ERROR)

IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}
# 움직이는 그림은 첫 장면만, MPO(폰 사진: 사진 + 숨은 보조 이미지)는 사진만 넣는다. 여러 쪽 TIFF는 전부.
FIRST_FRAME_ONLY = {"GIF", "WEBP", "PNG", "MPO"}
ORIENTATION = 0x0112
TEMP_PREFIX = "PDF변환합치기_"
A4 = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))

Progress = Callable[[int, int, "str | None"], None]  # (지금 몇 번째, 전체, 파일 이름 / 저장 중이면 None)


class ItemError(Exception):
    """목록의 특정 파일 때문에 실패했을 때"""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path.name}: {reason}")
        self.path = path
        self.reason = reason


class SaveError(Exception):
    """결과 PDF를 저장하지 못했을 때"""


@dataclass
class Item:
    path: Path
    kind: str  # "pdf" / "image"


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def reason_of(exc: BaseException) -> str:
    """오류를 사용자에게 보여 줄 말로 바꾼다"""
    if isinstance(exc, ItemError):
        return exc.reason
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


def inspect(path: Path) -> int:
    """쪽수를 센다. 열 수 없으면 ItemError"""
    try:
        if kind_of(path) == "pdf":
            with pikepdf.open(path) as pdf:
                return len(pdf.pages)
        with Image.open(path) as im:
            if im.format in FIRST_FRAME_ONLY:
                return 1
            return getattr(im, "n_frames", 1)
    except Exception as exc:  # noqa: BLE001
        raise ItemError(path, reason_of(exc)) from exc


# ── 이미지 → PDF ──────────────────────────────────────────────
def _layout(page: str):
    if page == "a4":
        # A4 안에 비율 그대로 맞추고, 가로로 긴 이미지는 가로 A4로
        return img2pdf.get_layout_fun(A4, None, None, img2pdf.FitMode.into, auto_orient=True)
    return img2pdf.default_layout_fun  # 원본 크기 (이미지에 적힌 해상도 기준, 없으면 96dpi)


def image_pdf_bytes(path: Path, page: str) -> bytes:
    """이미지 한 개를 PDF로 만든 내용. JPEG·PNG는 화질 손실 없이 그대로 넣는다."""
    raw = path.read_bytes()
    with Image.open(BytesIO(raw)) as im:
        fmt = im.format
        rotated_tiff = fmt == "TIFF" and _tiff_has_orientation(im)
    layout = _layout(page)
    if not rotated_tiff:  # 회전 태그 TIFF는 Pillow가 열 때 이미 세우는데 img2pdf가 한 번 더 돌린다 → 바꿔서 넣는다
        try:
            return img2pdf.convert(raw, layout_fun=layout, first_frame_only=fmt in FIRST_FRAME_ONLY)
        except Exception:  # noqa: BLE001 - 그대로 못 넣는 이미지는 아래에서 바꿔서 넣는다
            pass
    return img2pdf.convert(_flatten(raw, fmt), layout_fun=layout)


def _tiff_has_orientation(im: Image.Image) -> bool:
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        if im.tag_v2.get(ORIENTATION, 1) != 1:
            return True
    return False


def _flatten(raw: bytes, fmt: str) -> list[bytes]:
    """그대로 못 넣는 이미지(투명 배경 WEBP, 뒤집힌 사진 정보, 특이한 색 형식 등)를 흰 바탕 PNG로 바꾼다"""
    out = []
    with Image.open(BytesIO(raw)) as im:
        frames = 1 if fmt in FIRST_FRAME_ONLY else getattr(im, "n_frames", 1)
        for i in range(frames):
            im.seek(i)
            dpi = im.info.get("dpi")
            im.load()  # TIFF는 여기서 Pillow가 회전 태그대로 세우고 태그를 지운다 → 아래 exif_transpose는 그 밖의 형식만 돌린다
            frame = ImageOps.exif_transpose(im)
            if frame.mode in ("RGBA", "LA", "PA") or (frame.mode == "P" and "transparency" in frame.info):
                rgba = frame.convert("RGBA")
                frame = Image.new("RGB", rgba.size, "white")
                frame.paste(rgba, mask=rgba.getchannel("A"))
            elif frame.mode not in ("1", "L", "RGB"):
                frame = frame.convert("RGB")
            buf = BytesIO()
            if dpi and min(dpi) >= 10:  # 해상도 정보가 없는 TIFF는 Pillow가 1dpi로 알려 준다 → 모르는 것으로 (96dpi)
                frame.save(buf, "PNG", dpi=dpi)
            else:
                frame.save(buf, "PNG")
            out.append(buf.getvalue())
    return out


def image_to_pdf(src: Path, target: Path, page: str) -> None:
    """이미지 한 개 → PDF 파일 한 개"""
    try:
        data = image_pdf_bytes(src, page)
    except Exception as exc:  # noqa: BLE001
        raise ItemError(src, reason_of(exc)) from exc
    _store(target, lambda part: part.write_bytes(data))


# ── 합치기 ───────────────────────────────────────────────────
def merge(items: list[Item], page: str, target: Path, progress: Progress) -> int:
    """items를 순서대로 PDF 1개로 합쳐 target에 저장하고 전체 쪽수를 돌려준다.
    PDF는 원래 모양 그대로, 이미지는 page("a4"/"original") 크기의 쪽으로 넣는다."""
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        dst = pikepdf.new()
        sources: list[pikepdf.Pdf] = []
        try:
            for i, item in enumerate(items):
                progress(i, len(items), item.path.name)
                try:
                    if item.kind == "pdf":
                        src = pikepdf.open(item.path)
                    else:
                        part = work / f"{i}.pdf"
                        part.write_bytes(image_pdf_bytes(item.path, page))
                        src = pikepdf.open(part)
                    sources.append(src)
                    dst.pages.extend(src.pages)
                except Exception as exc:  # noqa: BLE001
                    raise ItemError(item.path, reason_of(exc)) from exc
            pages = len(dst.pages)
            if not pages:
                raise SaveError("넣을 쪽이 하나도 없어요 (쪽이 없는 PDF만 들어 있어요)")
            progress(len(items), len(items), None)
            _store(target, dst.save)
            return pages
        finally:
            dst.close()
            for src in sources:
                src.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _store(target: Path, write: Callable[[Path], object]) -> None:
    """같은 폴더에 임시 이름으로 다 쓴 다음 바꿔 넣는다. 도중에 실패해도 반쯤 쓴 파일이 남지 않는다."""
    part = target.with_name(f"~{target.stem}.저장중.pdf")
    try:
        write(part)
        os.replace(part, target)
    except Exception as exc:  # noqa: BLE001
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, PermissionError):
            reason = "저장하지 못했어요. 같은 이름의 PDF가 열려 있으면 닫고 다시 해 주세요."
        elif isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
            reason = "저장할 공간이 부족해요."
        else:
            reason = f"저장하지 못했어요 ({reason_of(exc)})"
        raise SaveError(f"{target.name}: {reason}") from exc


def clean_old_temp(hours: float = 6) -> None:
    """예전에 프로그램이 갑자기 닫혀 남은 임시 폴더를 지운다"""
    base = Path(tempfile.gettempdir())
    for p in base.glob(TEMP_PREFIX + "*"):
        try:
            if time.time() - p.stat().st_mtime > hours * 3600:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
