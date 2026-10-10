"""이미지 → PDF (img2pdf)

JPEG·PNG는 다시 압축하지 않고 그대로 넣는다. 그대로 못 넣는 이미지(거울상 사진 정보, 16비트, 투명 배경 등)만
풀어서 다시 담는다. 쪽 방향은 img2pdf가 쪽에 '돌림' 정보를 붙이는 방식이라, 돌림까지 계산해서 쪽 크기를 정한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import img2pdf
import pikepdf
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None  # 큰 스캔 이미지도 연다 (내 PC에 있는 파일만 다룸)
logging.getLogger("img2pdf").setLevel(logging.ERROR)

IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
A4 = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
DEFAULT_DPI = 96  # 해상도 정보가 없거나 터무니없을 때 (img2pdf 기본값과 같음)
ORIENTATION = 0x0112
_TURN = {1: 0, 3: 180, 6: 90, 8: 270}  # EXIF 방향값 → 시계 방향으로 돌릴 각도
_MIRRORED = {2, 4, 5, 7}                # 거울상: 쪽 돌리기로는 안 되므로 픽셀을 바로잡아 다시 담는다
_DEEP_MODES = ("I;16", "I;16B", "I;16L", "I;16N", "I", "F")
_ROTATION = {0: img2pdf.Rotation["0"], 90: img2pdf.Rotation["90"],
             180: img2pdf.Rotation["180"], 270: img2pdf.Rotation["270"]}


@dataclass(frozen=True)
class ImageOptions:
    page: str = "a4"         # "a4": A4 한 장에 맞춤 / "original": 이미지 크기 그대로
    orient: str = "auto"     # A4 방향 — "auto": 이미지 모양대로 / "portrait": 세로 / "landscape": 가로
    fit_turn: bool = False   # 방향을 정했을 때, 모양이 반대인 이미지는 90° 돌려서 크게 넣는다


@dataclass
class _Part:
    """img2pdf에 한 번에 넘기는 덩어리"""
    data: bytes
    turn: int                      # 사진 정보대로 세우려면 돌릴 각도 (시계 방향)
    size: tuple[int, int] | None   # 픽셀 크기 (돌리기 전). 여러 쪽 TIFF처럼 쪽마다 다를 수 있으면 None
    first_frame_only: bool = False
    repacked: bool = False


def count_pages(path: Path) -> int:
    """이미지가 PDF 몇 쪽이 되는지 (여러 쪽 TIFF만 여러 쪽)"""
    with Image.open(path) as im:
        return getattr(im, "n_frames", 1) if im.format == "TIFF" else 1


def image_pdf_bytes(path: Path, opts: ImageOptions, turn: int = 0) -> bytes:
    """이미지 한 개를 PDF로 만든 내용. turn: 사용자가 더 돌린 각도 (시계 방향, 90의 배수)"""
    raw = path.read_bytes()
    docs: list[bytes] = []
    for part in _parts(raw, opts):
        try:
            docs.append(_convert(part, opts, turn))
        except Exception:  # noqa: BLE001 - 그대로 못 넣는 이미지는 아래에서 풀어서 다시 담는다
            if part.repacked:
                raise
            for again in _repack_all(raw, part.first_frame_only):
                docs.append(_convert(again, opts, turn))
    return docs[0] if len(docs) == 1 else _join(docs)


def _convert(part: _Part, opts: ImageOptions, turn: int) -> bytes:
    rot = (part.turn + turn) % 360
    rot = (rot + _fit_turn(opts, part.size, rot)) % 360
    return img2pdf.convert(part.data, layout_fun=_layout(opts, rot), rotation=_ROTATION[rot],
                           first_frame_only=part.first_frame_only)


def _fit_turn(opts: ImageOptions, size: tuple[int, int] | None, rot: int) -> int:
    """'돌려서 크게 넣기': 정한 용지 방향과 이미지 모양이 반대면 90° 더 돌린다"""
    if opts.page != "a4" or opts.orient == "auto" or not opts.fit_turn or size is None:
        return 0
    w, h = size if rot in (0, 180) else (size[1], size[0])  # 보이는 모양
    if w == h or (w > h) == (opts.orient == "landscape"):
        return 0
    return 270 if w > h else 90  # 가로로 긴 건 왼쪽으로, 세로로 긴 건 오른쪽으로 눕힌다


def _layout(opts: ImageOptions, rot: int):
    if opts.page != "a4":
        base = img2pdf.default_layout_fun  # 원본 크기 (이미지에 적힌 해상도 기준, 없으면 96dpi)
    elif opts.orient == "auto":
        # 가로로 긴 이미지는 가로 A4. 쪽과 이미지가 함께 돌아가므로 보이는 모양 그대로 맞는다
        base = img2pdf.get_layout_fun(A4, None, None, img2pdf.FitMode.into, auto_orient=True)
    else:
        # 쪽은 돌리기 전 모양으로 만들어진 뒤 rot만큼 돌아간다 → 90°·270°면 반대 방향으로 만들어 둔다
        landscape = (opts.orient == "landscape") != (rot in (90, 270))
        base = img2pdf.get_layout_fun((A4[1], A4[0]) if landscape else A4, None, None, img2pdf.FitMode.into)

    def layout(width, height, ndpi):
        x, y = ndpi
        if not (10 <= x <= 20000 and 10 <= y <= 20000 and 0.1 <= x / y <= 10):
            ndpi = (DEFAULT_DPI, DEFAULT_DPI)  # 해상도 값이 터무니없으면 무시 (해상도 없는 TIFF는 1dpi로 읽힌다)
        return base(width, height, ndpi)

    return layout


# ── 어떻게 넣을지 정하기 ──────────────────────────────────────
def _parts(raw: bytes, opts: ImageOptions) -> list[_Part]:
    with Image.open(BytesIO(raw)) as im:
        fmt = im.format
        frames = getattr(im, "n_frames", 1)
        orient = _orientation(im)
        size = im.size
        if fmt == "TIFF":
            tagged = _tiff_tagged(im)
            deep = _tiff_bits(im) > 8
    if fmt == "TIFF":
        # Pillow는 TIFF를 풀면서 방향을 이미 바로 세우는데 img2pdf는 쪽을 또 돌린다 → 방향값이 있으면 풀어서 담는다.
        # 쪽마다 돌려서 넣을지 따로 정해야 할 때도 한 장씩 담는다.
        split = frames > 1 and opts.page == "a4" and opts.orient != "auto" and opts.fit_turn
        if tagged or deep or split:
            return _repack_all(raw, first_frame_only=False)
        return [_Part(raw, 0, size if frames == 1 else None)]
    if orient in _MIRRORED:
        return _repack_all(raw, first_frame_only=True)
    if fmt == "MPO":  # 휴대폰 사진에 붙은 보조 이미지는 떼고 본 사진만
        primary = _primary_jpeg(raw)
        if primary is not None:
            return [_Part(primary, _TURN.get(orient, 0), size)]
        return _repack_all(raw, first_frame_only=True)
    return [_Part(raw, _TURN.get(orient, 0), size, first_frame_only=frames > 1)]  # 움직이는 그림은 첫 장면만


def _repack_all(raw: bytes, first_frame_only: bool) -> list[_Part]:
    """한 장씩 풀어서 똑바로 세운 뒤 다시 담는다"""
    out = []
    with Image.open(BytesIO(raw)) as im:
        n = 1 if first_frame_only or im.format != "TIFF" else getattr(im, "n_frames", 1)
        for i in range(n):
            im.seek(i)
            data, size = _repack(im)
            out.append(_Part(data, 0, size, repacked=True))
    return out


def _repack(im: Image.Image) -> tuple[bytes, tuple[int, int]]:
    """지금 장을 바로 세워 다시 담는다. 사진은 고화질 JPEG, 그 밖은 무손실 PNG(CMYK는 TIFF), 투명한 곳은 흰색."""
    orient = _orientation(im)  # TIFF는 풀기 전에 읽어야 한다 (풀고 나면 Pillow가 지운다)
    photo = im.format in ("JPEG", "MPO")
    dpi = _dpi(im)
    icc = im.info.get("icc_profile")
    im.load()  # TIFF는 여기서 Pillow가 방향대로 세운다 → 아래 exif_transpose는 그 밖의 형식만 돌린다
    frame = ImageOps.exif_transpose(im)
    if orient >= 5 and dpi:
        dpi = (dpi[1], dpi[0])
    mode = frame.mode
    if mode in _DEEP_MODES:
        frame = _to_8bit(frame)
    elif mode in ("RGBA", "LA", "PA", "La", "RGBa") or (mode == "P" and "transparency" in frame.info):
        rgba = frame.convert("RGBA")
        frame = Image.new("RGB", rgba.size, "white")
        frame.paste(rgba, mask=rgba.getchannel("A"))
    elif mode not in ("1", "L", "P", "RGB", "CMYK"):
        frame = frame.convert("RGB")
    opts: dict = {}
    if dpi:
        opts["dpi"] = dpi
    if icc and frame.mode == mode:
        opts["icc_profile"] = icc
    buf = BytesIO()
    if photo and frame.mode in ("L", "RGB", "CMYK"):
        frame.save(buf, "JPEG", quality=95, subsampling=0, **opts)
    elif frame.mode == "CMYK":
        frame.save(buf, "TIFF", compression="tiff_adobe_deflate", **opts)
    else:
        frame.save(buf, "PNG", **opts)
    return buf.getvalue(), frame.size


def _join(docs: list[bytes]) -> bytes:
    with pikepdf.new() as dst:
        sources = [pikepdf.open(BytesIO(d)) for d in docs]
        try:
            for src in sources:
                dst.pages.extend(src.pages)
            buf = BytesIO()
            dst.save(buf, fix_metadata_version=False)
            return buf.getvalue()
        finally:
            for src in sources:
                src.close()


# ── 이미지 정보 ──────────────────────────────────────────────
def _orientation(im: Image.Image) -> int:
    """EXIF 방향값 (1~8). TIFF는 풀기(load) 전에 읽어야 한다."""
    try:
        value = int(im.tag_v2.get(ORIENTATION, 1)) if im.format == "TIFF" else int(im.getexif().get(ORIENTATION, 1))
    except Exception:  # noqa: BLE001
        return 1
    return value if 1 <= value <= 8 else 1


def _tiff_tagged(im: Image.Image) -> bool:
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        if im.tag_v2.get(ORIENTATION, 1) != 1:
            im.seek(0)
            return True
    im.seek(0)
    return False


def _tiff_bits(im: Image.Image) -> int:
    try:
        bits = im.tag_v2.get(258, 1)
        return max(bits) if isinstance(bits, (tuple, list)) else int(bits)
    except Exception:  # noqa: BLE001
        return 8


def _dpi(im: Image.Image) -> tuple[float, float] | None:
    try:
        x, y = (float(v) for v in im.info["dpi"])
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y) if x >= 10 and y >= 10 else None  # 해상도 없는 TIFF는 Pillow가 1dpi로 알려 준다 → 모르는 것으로


def _to_8bit(im: Image.Image) -> Image.Image:
    """16비트 흑백 등을 8비트 흑백으로"""
    if im.mode != "F":
        im = im.convert("I")
    hi = im.getextrema()[1]
    if hi > 255:
        scale = 255 / (65535 if hi <= 65535 else hi)
        im = im.point(lambda v: v * scale)
    return im.convert("L")


def _primary_jpeg(data: bytes) -> bytes | None:
    """MPO에서 본 사진 JPEG만 떼어 내고 MPF 표시를 지워 보통 JPEG로 만든다 (다시 압축하지 않음)"""
    try:
        with Image.open(BytesIO(data)) as im:
            size = int(im.mpinfo[0xB002][0]["Size"])
    except Exception:  # noqa: BLE001
        size = 0
    if not 0 < size <= len(data):
        size = len(data)
    out = bytearray(data[:2])
    i = 2
    while i + 4 <= size and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xFF:  # 채움 바이트
            i += 1
            continue
        if marker == 0xDA:  # 압축 데이터 시작: 여기부터는 그대로
            break
        end = i + 2 + int.from_bytes(data[i + 2:i + 4], "big")
        if not (marker == 0xE2 and data[i + 4:i + 8] == b"MPF\x00"):
            out += data[i:end]
        i = end
    out += data[i:size]
    try:
        with Image.open(BytesIO(bytes(out))) as check:
            if check.format == "JPEG":
                return bytes(out)
    except Exception:  # noqa: BLE001
        pass
    return None
