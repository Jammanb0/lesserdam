"""자동 점검 (개발용, exe에는 들어가지 않음)

    .venv\\Scripts\\python tools\\make_samples.py      (처음 한 번)
    .venv\\Scripts\\python tools\\check.py [시험 파일 폴더]   (기본: scratch\\samples)

이미지 방향, 이름 짓기, 폴더 짝짓기, 한글·오피스 변환(깔린 것만), 합치기·중지까지 확인한다.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path

import pikepdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pdftool import core, folders, naming, office  # noqa: E402
from pdftool.images import ImageOptions, image_pdf_bytes  # noqa: E402

failures: list[str] = []
launched: set[int] = set()   # 점검하면서 띄운 한글·오피스 프로세스 (같은 PC의 다른 프로그램 것은 세지 않는다)


def own_pids(off: office.Office) -> set[int]:
    return {pid for run in off._running.values() if not run.shared for pid in run.pids}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'통과' if ok else '실패'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def shapes(data: bytes) -> list[tuple[str, int]]:
    """쪽마다 (보이는 모양, 돌림 각도)"""
    out = []
    with pikepdf.open(BytesIO(data)) as pdf:
        for page in pdf.pages:
            x0, y0, x1, y1 = (float(v) for v in page.mediabox)
            rot = int(page.obj.get("/Rotate", 0)) % 360
            w, h = (y1 - y0, x1 - x0) if rot in (90, 270) else (x1 - x0, y1 - y0)
            out.append(("가로" if w > h else "세로", rot))
    return out


def check_images(base: Path) -> None:
    a4 = ImageOptions()
    cases = [
        ("가로.jpg", a4, 0, [("가로", 0)]),
        ("가로.jpg", ImageOptions("a4", "portrait"), 0, [("세로", 0)]),
        ("가로.jpg", ImageOptions("a4", "portrait", True), 0, [("세로", 270)]),
        ("가로.jpg", a4, 90, [("세로", 90)]),
        ("가로.jpg", ImageOptions("original"), 0, [("가로", 0)]),
        ("exif6.jpg", a4, 0, [("세로", 90)]),
        ("exif6.jpg", ImageOptions("a4", "landscape"), 0, [("가로", 90)]),
        ("mirror2.jpg", a4, 0, [("가로", 0)]),
        ("두쪽.tif", a4, 0, [("가로", 0), ("세로", 0)]),
        ("두쪽.tif", ImageOptions("a4", "portrait", True), 0, [("세로", 270), ("세로", 0)]),
        ("태그6.tif", a4, 0, [("세로", 0)]),
    ]
    for name, opts, turn, want in cases:
        got = shapes(image_pdf_bytes(base / name, opts, turn))
        check(f"이미지 {name} {opts.page}/{opts.orient}{'/돌려크게' if opts.fit_turn else ''} 돌림{turn}", got == want,
              f"{got} ≠ {want}")
    bad = []
    for f in sorted(base.iterdir()):
        for opts in (a4, ImageOptions("original"), ImageOptions("a4", "landscape", True)):
            try:
                image_pdf_bytes(f, opts)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{f.name}: {exc}")
    check("이미지 모든 형식 변환", not bad, "; ".join(bad))


def check_naming() -> None:
    cases = [
        (["가상도 예제시 샘플구 가상가동 143", "가상도 예제시 샘플구 가상나동 621"], ["가상가동 143", "가상나동 621"]),
        (["인쇄 토지이용계획(열람용) 805-1", "인쇄 토지이용계획(열람용) 산32-1"], ["805-1", "산32-1"]),
        (["토지 805-1", "토지 805-2"], ["805-1", "805-2"]),
        (["가상가동 143 토지대장", "가상나동 621 토지대장"], ["가상가동 143", "가상나동 621"]),
        (["가상도 예제시 샘플구 가상가동 143 토지대장 9001 시험", "가상도 예제시 샘플구 가상나동 621 토지대장 9002 시험"],
         ["가상가동 143 9001", "가상나동 621 9002"]),
        (["가상가동 산45", "가상나동 산12"], ["가상가동 산45", "가상나동 산12"]),
        (["가", "나"], ["가", "나"]),
        (["한 개뿐"], ["한 개뿐"]),
    ]
    for stems, want in cases:
        split = naming.split_names(stems)
        got = [split.pick(s, None) for s in stems]
        check(f"다른 부분 {stems[0]} …", got == want, f"{got}")
    split = naming.split_names(cases[4][0])
    shape = [("같음" if p.same else "다름", p.sample) for p in split.parts]
    check("구간: 반복 구간이 가운데에도 있을 때", shape == [("같음", "가상도 예제시 샘플구"), ("다름", "가상가동 143"),
                                                ("같음", "토지대장"), ("다름", "9001"), ("같음", "시험")], f"{shape}")
    check("구간: 고른 것만 넣기", split.pick(cases[4][0][0], (1,)) == "가상가동 143")
    rule = naming.NameRule(before="통합 ", middle="diff")
    check("이름: 정한 문구 + 다른 부분",
          naming.make(rule, cases[0][0][0], 0, naming.split_names(cases[0][0])) == "통합 가상가동 143")
    rule = naming.NameRule(before="통합 파일", middle="none", number="back")
    check("이름: 정한 문구 + 번호", [naming.make(rule, None, i) for i in range(2)] == ["통합 파일 1", "통합 파일 2"])
    check("이름: 쓸 수 없는 글자", naming.safe_name('a/b:c?.') == "a_b_c_")

    joined = [
        (naming.NameRule(before="통합", after="최종"), "도면", "통합도면최종"),
        (naming.NameRule(before="통합 ", after=" 최종"), "도면", "통합 도면 최종"),
        (naming.NameRule(before="통합  ", after="  최종"), "도면", "통합  도면  최종"),
        (naming.NameRule(before="앞", middle="none", after="뒤"), "도면", "앞뒤"),
        (naming.NameRule(before="[", after="]", number="front", digits=2, separator=". "), "도면", "01. [도면]"),
    ]
    for rule, stem, expected in joined:
        got = naming.make(rule, stem, 0)
        check(f"앞뒤 문구: {expected!r}", got == expected, f"{got!r} ≠ {expected!r}")

    numbered = [
        ("마침표와 공백을 번호 뒤에", naming.NameRule(number="front", digits=2, separator=". "), "도면", 0, "01. 도면"),
        ("밑줄을 번호 앞에", naming.NameRule(number="back", digits=2, separator="_"), "도면", 0, "도면_01"),
        ("직접 입력한 여러 문자", naming.NameRule(number="front", start=7, digits=3, separator=" - "), "도면", 1, "008 - 도면"),
        ("연결 문자 없이 번호 붙이기", naming.NameRule(number="back", digits=2, separator=""), "도면", 0, "도면01"),
        ("번호를 끄면 연결 문자도 생략", naming.NameRule(separator="_"), "도면", 0, "도면"),
        ("번호만 있을 때 앞 연결 문자 생략", naming.NameRule(middle="none", number="front", digits=2, separator=". "), "도면", 0, "01"),
        ("번호만 있을 때 뒤 연결 문자 생략", naming.NameRule(middle="none", number="back", digits=2, separator="_"), "도면", 0, "01"),
        ("연결 문자의 금지 문자 처리", naming.NameRule(number="back", digits=2, separator="/"), "도면", 0, "도면_01"),
    ]
    for label, rule, stem, index, expected in numbered:
        got = naming.make(rule, stem, index)
        check(f"번호: {label}", got == expected, f"{got!r} ≠ {expected!r}")


def check_folders(base: Path) -> None:
    scans = [folders.scan(base / n, {"pdf"}, "name", False) for n in ("한글", "영어", "숫자")]
    check("폴더 짝짓기: 개수", [len(s.files) for s in scans] == [4, 4, 3])
    check("폴더 짝짓기: 짧은 쪽까지", folders.row_count(scans, "shortest") == 3)
    check("폴더 짝짓기: 끝까지", folders.row_count(scans, "longest") == 4)
    check("폴더 짝짓기: 처음 빈 줄", folders.first_gap(scans) == 3)
    rows = folders.rows(scans)
    check("폴더 짝짓기: 4번째 줄에 숫자 없음", rows[3][2] is None and rows[0][1].name == "A.pdf")


def check_office(base: Path, out: Path) -> None:
    kinds = [k for k in office.APPS if office.installed(k)]
    print(f"     (이 PC에서 바꿀 수 있는 문서: {', '.join(office.APPS[k].label for k in kinds) or '없음'})")
    off = office.Office()
    try:
        for f in sorted(base.iterdir()):
            kind = office.DOC_EXTS.get(f.suffix.lower())
            if kind not in kinds:
                continue
            locked = f.name.startswith("암호")
            start = time.monotonic()
            try:
                off.to_pdf(kind, f, out / f"{f.stem}_{f.suffix[1:]}.pdf")
                ok, detail = not locked, "암호 파일인데 바뀜"
            except office.DocError as exc:
                ok, detail = locked and time.monotonic() - start < 10, str(exc)
            check(f"문서 {f.name}", ok, detail)
    finally:
        launched.update(own_pids(off))
        off.close()


def check_core(images: Path, docs: Path, out: Path) -> None:
    cache = core.DocCache()
    events: list[tuple] = []
    try:
        items = [core.Item(images / "가로.jpg", "image", mark="가로"),
                 core.Item(images / "두쪽.tif", "image", turn=90, mark="두쪽")]
        if office.installed("word"):
            items.append(core.Item(docs / "워드 시험.docx", "word", turn=180, mark="워드"))
        session = core.Session(events.append, cache)
        try:
            pages = core.merge(session, items, ImageOptions(), out / "합본.pdf")
        finally:
            launched.update(own_pids(session.office))
            session.close()
        with pikepdf.open(out / "합본.pdf") as pdf, pdf.open_outline() as outline:
            marks = [i.title for i in outline.root]
        check("합치기: 쪽수와 책갈피", pages == 3 + bool(office.installed("word"))
              and marks == [it.mark for it in items], f"{pages}쪽, 책갈피 {marks}")

        rows = [("가상가동 143", [core.Item(images / "가로.jpg", "image", mark="토지대장"),
                               core.Item(images / "세로.jpg", "image", mark="지적도")]),
                ("가상나동 621", [core.Item(images / "두쪽.tif", "image", mark="")])]
        session = core.Session(events.append, cache)
        try:
            pages = core.merge_rows(session, rows, ImageOptions(), out / "줄 합본.pdf")
        finally:
            launched.update(own_pids(session.office))
            session.close()
        with pikepdf.open(out / "줄 합본.pdf") as pdf, pdf.open_outline() as outline:
            tree = [(i.title, [c.title for c in i.children]) for i in outline.root]
        check("하나로 합치기: 줄 책갈피 아래 파일 책갈피",
              pages == 4 and tree == [("가상가동 143", ["토지대장", "지적도"]), ("가상나동 621", [])], f"{pages}쪽, {tree}")

        plan = [(core.Item(images / "세로.jpg", "image"), out / "1.pdf"),
                (core.Item(images / "없는 파일.jpg", "image"), out / "2.pdf")]
        session = core.Session(events.append, cache)
        try:
            report = core.convert_each(session, plan, ImageOptions())
        finally:
            launched.update(own_pids(session.office))
            session.close()
        check("파일마다: 하나가 안 돼도 계속", len(report.saved) == 1 and len(report.failed) == 1, f"{report}")

        sets = [([core.Item(images / "가로.jpg", "image")], out / "묶음1.pdf"),
                ([core.Item(images / "세로.jpg", "image")], out / "묶음2.pdf")]
        session = core.Session(events.append, cache)
        session.cancel.set()  # 시작하자마자 [중지]
        try:
            report = core.merge_sets(session, sets, ImageOptions())
        finally:
            launched.update(own_pids(session.office))
            session.close()
        check("묶음 합치기: 중지", report.stopped and not report.saved, f"{report}")

        if office.installed("ppt") and office._pids("POWERPNT.EXE"):
            print("     (파워포인트가 이미 켜져 있어서 '문서 변환 중 [중지]'는 건너뜀 — 켜 둔 파워포인트는 끄지 않으니까)")
        elif office.installed("ppt"):
            session = core.Session(events.append, core.DocCache())
            threading.Timer(0.3, session.stop).start()
            start = time.monotonic()
            try:
                report = core.merge_sets(session, [([core.Item(docs / "발표 시험.pptx", "ppt")], out / "중지1.pdf"),
                                                   ([core.Item(docs / "옛날 발표.ppt", "ppt")], out / "중지2.pdf")],
                                         ImageOptions())
            finally:
                launched.update(own_pids(session.office))
                session.close()
            check("문서 변환 중 [중지]", report.stopped and time.monotonic() - start < 20, f"{report}")
    finally:
        cache.clear()
    time.sleep(0.5)
    left = {pid for pid in launched if office._alive({pid})}
    check(f"점검이 띄운 한글·오피스 {len(launched)}개가 모두 닫힘", not left, f"남은 프로세스 {left}")


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scratch" / "samples"
    if not (base / "images").is_dir():
        sys.exit(f"시험 파일이 없어요. 먼저 tools\\make_samples.py를 실행해 주세요. ({base})")
    out = Path(tempfile.mkdtemp(prefix="pdftool_check_"))
    try:
        # 한글은 일반 폴더의 파일을 열 때 접근 확인 창을 띄워서, 자동 점검은 임시 폴더 복사본으로 한다
        docs = shutil.copytree(base / "docs", out / "docs")
        check_images(base / "images")
        check_naming()
        check_folders(base / "folders")
        check_office(docs, out)
        check_core(base / "images", docs, out)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    print()
    print("모두 통과" if not failures else f"실패 {len(failures)}개: {', '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
