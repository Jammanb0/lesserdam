"""시험용 파일 만들기 (개발용, exe에는 들어가지 않음)

    .venv\\Scripts\\python tools\\make_samples.py [폴더]      (기본: scratch\\samples)

- 이미지: 위쪽에 빨간 화살표가 있는 카드. 방향 정보(EXIF·TIFF)가 여러 가지
- 문서: 이 PC의 한글·워드·엑셀·파워포인트로 직접 만든다 (없는 프로그램은 건너뜀). 암호 걸린 것도 포함
  (한글은 일반 폴더에 저장하려 하면 접근 확인 창을 띄워서, 임시 폴더에 만든 뒤 옮긴다)
- 폴더: ③ 탭 시험용 한글·영어·숫자 폴더 (숫자 폴더만 하나 적음)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pikepdf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pdftool import office  # noqa: E402
from sample_metadata import clean_sample  # noqa: E402

FONT = r"C:\Windows\Fonts\malgun.ttf"


def card(w: int, h: int, label: str, color=(200, 230, 255)) -> Image.Image:
    font = ImageFont.truetype(FONT, 90)
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    d.rectangle([5, 5, w - 6, h - 6], outline=(0, 0, 0), width=10)
    d.polygon([(w // 2, 30), (w // 2 - 60, 140), (w // 2 + 60, 140)], fill=(220, 0, 0))  # 위쪽 표시
    d.text((40, 170), "위", font=font, fill=(0, 0, 0))
    d.text((40, h - 140), label, font=font, fill=(0, 0, 160))
    return im


def exif(orient: int) -> bytes:
    ex = Image.Exif()
    ex[0x0112] = orient
    return ex.tobytes()


def make_images(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    card(1600, 1000, "가로 사진").save(out / "가로.jpg", quality=90)
    card(1000, 1600, "세로 사진").save(out / "세로.jpg", quality=90)
    # 픽셀은 가로로 누워 있고 EXIF 6 → 보이는 모양은 세로
    card(1000, 1600, "EXIF6 세로").transpose(Image.Transpose.ROTATE_90).save(out / "exif6.jpg", quality=90, exif=exif(6))
    # 좌우가 뒤집힌 픽셀 + EXIF 2 → 보이는 모양은 정상
    card(1600, 1000, "거울상 바로").transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(
        out / "mirror2.jpg", quality=90, exif=exif(2))
    rgba = card(1200, 900, "투명 PNG").convert("RGBA")
    rgba.paste((255, 0, 0, 0), (0, 0, 300, 300))
    rgba.save(out / "투명.png")
    card(900, 1200, "16비트").convert("L").convert("I;16").save(out / "16bit.png")
    card(1600, 1000, "TIFF 1쪽 가로").save(out / "두쪽.tif", save_all=True,
                                       append_images=[card(1000, 1600, "TIFF 2쪽 세로")], compression="tiff_deflate")
    card(1000, 1600, "TIFF 태그6").transpose(Image.Transpose.ROTATE_90).save(
        out / "태그6.tif", tiffinfo={0x0112: 6}, compression="tiff_deflate")
    card(1200, 800, "CMYK").convert("CMYK").save(out / "cmyk.jpg", quality=90)
    card(800, 600, "GIF 1").convert("P").save(out / "움직임.gif", save_all=True,
                                             append_images=[card(800, 600, "GIF 2", (255, 220, 200)).convert("P")],
                                             duration=200, loop=0)
    card(800, 1000, "팔레트투명").convert("P").save(out / "팔레트.png", transparency=0)
    card(1000, 700, "BMP").save(out / "그림.bmp")
    card(700, 1000, "WEBP").save(out / "그림.webp", quality=90)


def make_docs(out: Path) -> None:
    """이 PC의 프로그램으로 문서를 만든다"""
    import pythoncom

    out.mkdir(parents=True, exist_ok=True)
    (out / "메모 utf8.txt").write_text("UTF-8 메모입니다.\n둘째 줄", encoding="utf-8")
    (out / "메모 cp949.txt").write_bytes("CP949 메모입니다.\n둘째 줄".encode("cp949"))
    pythoncom.CoInitialize()
    manager = office.Office()
    manager._com = True
    try:
        if office.installed("word"):
            word = manager._start("word").app
            word.Visible = False
            word.DisplayAlerts = 0
            for name, fmt, pw in (("워드 시험.docx", 16, None), ("옛날 워드.doc", 0, None), ("서식 문서.rtf", 6, None),
                                  ("오픈 문서.odt", 23, None), ("암호 워드.docx", 16, "1234")):
                doc = word.Documents.Add()
                doc.Content.Text = f"{name} 내용입니다."
                doc.RemovePersonalInformation = True
                if pw:
                    doc.Password = pw
                doc.SaveAs2(FileName=str(out / name), FileFormat=fmt)
                doc.Close(0)
            del word, doc  # 참조를 놓아야 프로그램이 닫힌다
        if office.installed("excel"):
            xl = manager._start("excel").app
            xl.Visible = False
            xl.DisplayAlerts = False
            for name, fmt, kw in (("엑셀 시험.xlsx", 51, {}), ("옛날 엑셀.xls", 56, {}),
                                  ("암호 엑셀.xlsx", 51, {"Password": "1234"}),
                                  ("암호 옛날 엑셀.xls", 56, {"Password": "1234"}),
                                  ("쓰기암호 엑셀.xlsx", 51, {"WriteResPassword": "1234"})):
                book = xl.Workbooks.Add()
                book.Worksheets(1).Range("A1").Value = name
                book.RemovePersonalInformation = True
                book.SaveAs(Filename=str(out / name), FileFormat=fmt, **kw)
                book.Close(False)
            del xl, book
        if office.installed("ppt"):
            pp = manager._start("ppt").app
            for name, fmt, pw in (("발표 시험.pptx", 24, None), ("옛날 발표.ppt", 1, None), ("암호 발표.pptx", 24, "1234")):
                pres = pp.Presentations.Add(WithWindow=False)
                pres.Slides.Add(1, 1).Shapes(1).TextFrame.TextRange.Text = name
                pres.RemovePersonalInformation = True
                if pw:
                    pres.Password = pw
                pres.SaveAs(str(out / name), fmt)
                pres.Close()
            del pp, pres
        if office.installed("hwp"):
            work = Path(tempfile.mkdtemp(prefix="pdftool_samples_"))
            hwp = manager._start("hwp").app
            hwp.XHwpWindows.Item(0).Visible = False
            act = hwp.CreateAction("InsertText")
            pset = act.CreateSet()
            act.GetDefault(pset)
            pset.SetItem("Text", "한글 시험 문서입니다.")
            act.Execute(pset)
            for name, fmt in (("한글 시험.hwp", "HWP"), ("한글 시험 x.hwpx", "HWPX")):
                hwp.SaveAs(str(work / name), fmt, "")
            hwp.Clear(1)
            del hwp, act, pset
            for f in work.iterdir():
                shutil.move(str(f), out / f.name)
            shutil.rmtree(work, ignore_errors=True)
        for path in out.iterdir():
            if path.is_file():
                clean_sample(path)
    finally:
        manager.close()


def make_folders(out: Path) -> None:
    """③ 탭 시험용: 한글 4개 · 영어 4개 · 숫자 3개"""
    names = {
        "한글": [f"가상도 예제시 샘플구 {d}.pdf" for d in ("가상가동 143", "가상나동 621", "가상다동 12-3", "가상라동 산45")],
        "영어": ["A.pdf", "B.pdf", "C.pdf", "D.pdf"],
        "숫자": ["1.pdf", "2.pdf", "3.pdf"],
    }
    for folder, files in names.items():
        (out / folder).mkdir(parents=True, exist_ok=True)
        for name in files:
            with pikepdf.new() as pdf:
                pdf.add_blank_page(page_size=(595, 842))
                pdf.save(out / folder / name)


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scratch" / "samples"
    base = base.resolve()
    if base.exists() and any(base.iterdir()):
        sys.exit("비어 있는 새 폴더를 골라 주세요. 기존 자료는 자동으로 덮어쓰거나 지우지 않아요.")
    make_images(base / "images")
    make_docs(base / "docs")
    make_folders(base / "folders")
    print(f"만들었어요: {base}")


if __name__ == "__main__":
    main()
