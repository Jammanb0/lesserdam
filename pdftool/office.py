"""한글·워드·엑셀·파워포인트 문서 → PDF

이 PC에 깔린 프로그램을 뒤에서(창을 숨긴 채) 띄워 PDF로 저장한다 (pywin32).
한 작업 동안 프로그램마다 한 번만 띄우고, 작업이 끝나면 닫는다.

- 암호 걸린 문서: 워드·파워포인트는 일부러 틀린 암호를 넘겨 바로 실패하게 하고,
  엑셀은 틀린 암호를 넘겨도 암호 창을 띄우고 멈추므로 열기 전에 파일 머리를 보고 걸러 낸다.
- 그래도 프로그램이 확인 창을 띄우면 그 창을 앞으로 꺼내고 화면에 알린다. 사용자가 창에서 고르거나 [중지]를 누른다.
  (오래 걸리는 변환을 잘못 끊지 않도록 저절로 끄지는 않는다)
"""
from __future__ import annotations

import ctypes
import mmap
import os
import threading
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DUMMY_PASSWORD = "pdf-tool-no-password"  # 암호가 없는 문서는 무시하고, 암호가 있으면 '틀린 암호'로 바로 실패한다


@dataclass(frozen=True)
class AppInfo:
    label: str
    progid: str
    exe: str
    exts: frozenset[str]


APPS = {
    "hwp": AppInfo("한글", "HWPFrame.HwpObject", "Hwp.exe", frozenset({".hwp", ".hwpx"})),
    "word": AppInfo("워드", "Word.Application", "WINWORD.EXE",
                    frozenset({".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".rtf", ".odt", ".txt"})),
    "excel": AppInfo("엑셀", "Excel.Application", "EXCEL.EXE",
                     frozenset({".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".xltm", ".ods"})),
    "ppt": AppInfo("파워포인트", "PowerPoint.Application", "POWERPNT.EXE",
                   frozenset({".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".ppsm", ".pot", ".potx", ".potm", ".odp"})),
}
DOC_EXTS = {ext: kind for kind, info in APPS.items() for ext in info.exts}

_installed: dict[str, bool] = {}


def installed(kind: str) -> bool:
    """그 프로그램이 이 PC에 깔려 있어 자동으로 부를 수 있는지"""
    if kind not in _installed:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, APPS[kind].progid + r"\CLSID"))
            _installed[kind] = True
        except OSError:
            _installed[kind] = False
    return _installed[kind]


def i_ga(word: str) -> str:
    """받침에 맞춰 '이/가'를 붙인다 (한글이, 워드가, 엑셀이, 파워포인트가)"""
    last = word[-1:]
    if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28:
        return word + "이"
    return word + "가"


class DocError(Exception):
    """문서 하나를 바꾸지 못했을 때 (화면에 보여 줄 이유)"""


class Stopped(Exception):
    """[중지]로 프로그램을 닫았을 때"""


def check(kind: str, path: Path) -> None:
    """바꾸기 전에 미리 알 수 있는 문제를 DocError로 알린다 (프로그램 없음, 엑셀 암호)"""
    if not installed(kind):
        raise DocError(f"이 PC에 {APPS[kind].label} 프로그램이 없어서 PDF로 바꿀 수 없어요")
    if kind == "excel" and _excel_locked(path):
        raise DocError("암호가 걸린 엑셀 파일이라 바꿀 수 없어요 (엑셀에서 암호를 풀고 다시 넣어 주세요)")


# ── 프로그램별로 바꾸는 방법 ──────────────────────────────────
def _word(app, src: Path, dst: Path) -> None:
    kw = dict(FileName=str(src), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
              PasswordDocument=DUMMY_PASSWORD, Visible=False, OpenAndRepair=False, NoEncodingDialog=True)
    if src.suffix.lower() == ".txt":
        kw["Encoding"] = _text_encoding(src)
    doc = app.Documents.Open(**kw)
    try:
        # 17: PDF, OptimizeFor 0: 인쇄용 화질, CreateBookmarks 1: 제목으로 책갈피
        doc.ExportAsFixedFormat(OutputFileName=str(dst), ExportFormat=17, OpenAfterExport=False, OptimizeFor=0,
                                CreateBookmarks=1, DocStructureTags=True, BitmapMissingFonts=True)
    finally:
        doc.Close(SaveChanges=0)


def _excel(app, src: Path, dst: Path) -> None:
    book = app.Workbooks.Open(Filename=str(src), UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True,
                              AddToMru=False, Notify=False)
    try:
        # 0: PDF. 시트마다 정해 둔 인쇄 영역·용지 설정을 따른다
        book.ExportAsFixedFormat(Type=0, Filename=str(dst), Quality=0, IncludeDocProperties=True,
                                 IgnorePrintAreas=False, OpenAfterPublish=False)
    finally:
        book.Close(SaveChanges=False)


def _ppt(app, src: Path, dst: Path) -> None:
    # 파일 이름 뒤 ::암호:: 로 열기 암호를 넘긴다 (틀리면 암호 창 없이 바로 실패)
    pres = app.Presentations.Open(FileName=f"{src}::{DUMMY_PASSWORD}::", ReadOnly=True, Untitled=False,
                                  WithWindow=False)
    try:
        pres.SaveAs(str(dst), 32)  # 32: PDF
    finally:
        pres.Close()


def _hwp(app, src: Path, dst: Path) -> None:
    # forceopen: 다른 곳에서 열려 있어도 읽기로 연다 / suspendpassword: 암호를 묻지 않고 실패 / versionwarning: 상위 버전 경고 끔
    if not app.Open(str(src), "", "forceopen:true;suspendpassword:true;versionwarning:false"):
        raise DocError("한글이 이 파일을 열지 못했어요 (암호가 걸렸거나 손상된 파일일 수 있어요)")
    try:
        if not app.SaveAs(str(dst), "PDF", ""):
            raise DocError("한글이 PDF로 저장하지 못했어요")
    finally:
        app.Clear(1)  # 1: 바뀐 내용 버리고 닫기


_CONVERT = {"hwp": _hwp, "word": _word, "excel": _excel, "ppt": _ppt}


# ── 작업 한 번 동안의 프로그램 관리 ──────────────────────────────
@dataclass
class _Running:
    kind: str
    app: object
    pids: set[int]           # 이번에 띄운 프로세스 (닫거나 [중지]로 끌 때 쓴다)
    shared: bool = False     # 사용자가 이미 켜 둔 프로그램을 같이 쓰는 중 (파워포인트) → 절대 끄지 않는다
    restore: dict = field(default_factory=dict)


class Office:
    """to_pdf()·close()는 작업 스레드에서만 부르고, stop()은 화면 스레드에서 불러도 된다.
    on_dialog(이름, 창 제목)는 프로그램이 확인 창을 띄웠을 때, on_dialog(None, None)은 그 창이 닫혔을 때 불린다."""

    def __init__(self, on_dialog: Callable[[str | None, str | None], None] | None = None) -> None:
        self._on_dialog = on_dialog or (lambda label, title: None)
        self._running: dict[str, _Running] = {}
        self._stopped = False
        self._com = False
        self._lock = threading.Lock()

    def to_pdf(self, kind: str, src: Path, dst: Path) -> None:
        import pythoncom
        import pywintypes

        if self._stopped:
            raise Stopped
        src, dst = Path(os.path.abspath(src)), Path(os.path.abspath(dst))  # 프로그램은 상대 경로를 자기 폴더 기준으로 읽는다
        check(kind, src)
        if not self._com:
            pythoncom.CoInitialize()
            self._com = True
        run = self._running.get(kind) or self._start(kind)
        watch = _Watch(run.pids if not run.shared else set(), APPS[kind].label, self._on_dialog)
        watch.start()
        try:
            _CONVERT[kind](run.app, src, dst)
        except DocError:
            raise
        except pywintypes.com_error as exc:
            if self._stopped:
                raise Stopped from exc
            if not _alive(run.pids) and not run.shared:
                self._running.pop(kind, None)  # 프로그램이 죽었으면 다음 파일에서 새로 띄운다
            raise DocError(_com_reason(APPS[kind].label, exc, watch.seen)) from exc
        finally:
            watch.stop()
            self._hide_again(run)
        if not dst.is_file() or dst.stat().st_size == 0:
            raise DocError(f"{i_ga(APPS[kind].label)} PDF를 만들지 않았어요 (인쇄할 내용이 없을 수 있어요)")

    def stop(self) -> None:
        """[중지]: 이번에 띄운 프로그램을 바로 끈다 (막혀 있는 변환도 풀린다)"""
        self._stopped = True
        with self._lock:
            runs = list(self._running.values())
        for run in runs:
            if not run.shared:
                _kill(run.pids)

    def close(self) -> None:
        """작업이 끝나면 띄운 프로그램을 닫는다. 안 닫히면 끈다.
        (엑셀이 닫기 명령에 1분 가까이 묶인 적이 있어서, 10초가 넘으면 기다리지 않고 끈다)"""
        with self._lock:
            runs = list(self._running.values())
            self._running.clear()
        own: set[int] = set()
        for run in runs:
            if not run.shared:
                own |= run.pids
        guard = threading.Timer(10, _kill, args=(own,))
        guard.daemon = True
        guard.start()
        for run in runs:
            if not self._stopped or run.shared:
                try:
                    _quit(run)
                except Exception:  # noqa: BLE001 - 닫기에 실패해도 아래에서 끈다
                    pass
            run.app = None
        deadline = time.monotonic() + 5
        while _alive(own) and time.monotonic() < deadline:
            time.sleep(0.1)
        guard.cancel()
        _kill(own)
        if self._com:
            import pythoncom

            pythoncom.CoUninitialize()
            self._com = False

    def _start(self, kind: str) -> _Running:
        import win32com.client

        info = APPS[kind]
        before = _pids(info.exe)
        if kind in ("hwp", "ppt") and before:
            raise DocError(f"열려 있는 {info.label}을 닫고 다시 시도해 주세요. 작업 중인 문서를 보호하기 위해 변환을 시작하지 않았어요.")
        if kind == "ppt":
            # 파워포인트는 한 대만 뜨는 프로그램이라, 사용자가 켜 둔 게 있으면 그걸 같이 쓴다
            app = win32com.client.Dispatch(info.progid)
        elif kind == "hwp":
            app = win32com.client.Dispatch(info.progid)
        else:
            app = win32com.client.DispatchEx(info.progid)  # 사용자가 쓰는 워드·엑셀과 섞이지 않게 새로 띄운다
        shared = kind == "ppt" and bool(before)
        run = _Running(kind, app, set() if shared else _own_pids(kind, app, info.exe, before), shared=shared)
        if not run.pids and not shared:
            # 소유권을 확인하지 못한 프로세스에는 Quit/강제 종료를 보내지 않는다.
            raise DocError(f"{APPS[kind].label}의 전용 실행 창을 확인하지 못했어요. 프로그램을 확인하고 다시 시도해 주세요.")
        with self._lock:
            self._running[kind] = run
            stopped = self._stopped
        if stopped:
            if not run.shared:
                _kill(run.pids)
            raise Stopped
        if kind == "word":
            app.Visible = False
            app.DisplayAlerts = 0              # 경고 창 끄기
            app.AutomationSecurity = 3         # 매크로 실행 안 함
        elif kind == "excel":
            app.Visible = False
            app.DisplayAlerts = False
            app.AutomationSecurity = 3
            # AskToUpdateLinks는 사용자의 엑셀 옵션에 남는 설정이라 건드리지 않는다 (열 때 UpdateLinks=0으로 충분)
        elif kind == "ppt":
            run.restore = {"AutomationSecurity": app.AutomationSecurity, "DisplayAlerts": app.DisplayAlerts}
            app.AutomationSecurity = 3
            app.DisplayAlerts = 1              # ppAlertsNone
        elif kind == "hwp":
            app.XHwpWindows.Item(0).Visible = False
        return run

    @staticmethod
    def _hide_again(run: _Running) -> None:
        """확인 창이 뜨면서 숨겨 둔 창이 드러났을 수 있다 (엑셀이 그랬다)"""
        try:
            if run.kind in ("word", "excel") and run.app.Visible:
                run.app.Visible = False
        except Exception:  # noqa: BLE001
            pass


def _own_pids(kind: str, app, exe: str, before: set[int]) -> set[int]:
    """이번에 띄운 프로그램의 프로세스. 창 번호로 정확히 찾는다 (같은 PC에서 다른 프로그램이 엑셀 등을 동시에 띄워도
    그걸 끄지 않게). 확인에 실패하면 다른 프로세스를 추측해서 종료하지 않는다."""
    import win32gui
    import win32process

    try:
        if kind == "excel":
            hwnd = int(app.Hwnd)
        elif kind in ("word", "ppt"):
            tag = f"pdftool-{os.getpid()}-{time.monotonic_ns()}"
            app.Caption = tag  # 고유한 제목으로 숨은 전용 창을 찾는다
            window_class = "OpusApp" if kind == "word" else "PPTFrameClass"
            hwnd = win32gui.FindWindow(window_class, tag)
            if not hwnd:
                matches = []
                def visit(handle, _):
                    if win32gui.GetClassName(handle) == window_class and tag in win32gui.GetWindowText(handle):
                        matches.append(handle)
                win32gui.EnumWindows(visit, None)
                hwnd = matches[0] if len(matches) == 1 else 0
        else:
            hwnd = int(app.XHwpWindows.Item(0).WindowHandle)
        if hwnd:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            return {pid} if pid not in before and pid in _pids(exe) else set()
    except Exception:  # noqa: BLE001
        pass
    return set()


def _quit(run: _Running) -> None:
    app = run.app
    if run.kind == "word":
        app.Quit(SaveChanges=0)
    elif run.kind == "excel":
        app.Quit()
    elif run.kind == "hwp":
        app.Clear(1)
        app.Quit()
    elif run.kind == "ppt":
        if run.shared:
            for name, value in run.restore.items():
                setattr(app, name, value)
        elif app.Presentations.Count == 0:
            app.Quit()


def _com_reason(label: str, exc: Exception, dialog: str | None) -> str:
    if dialog:
        return f"{i_ga(label)} '{dialog}' 창을 띄워서 바꾸지 못했어요"
    detail = ""
    try:
        detail = (exc.excepinfo[2] or "").strip()  # type: ignore[attr-defined]
    except (AttributeError, IndexError, TypeError):
        pass
    if "암호" in detail or "password" in detail.lower():
        return "암호가 걸린 문서라 바꿀 수 없어요"
    if detail:
        return f"{i_ga(label)} 이 파일을 바꾸지 못했어요: {detail.splitlines()[0][:120]}"
    return f"{i_ga(label)} 응답하지 않아 바꾸지 못했어요"


def _text_encoding(path: Path) -> int:
    """메모장 파일의 글자 인코딩 (워드에 알려 줄 번호). BOM이 없으면 UTF-8인지 보고, 아니면 한국어(CP949)"""
    limit = 4 << 20
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    if data.startswith(b"\xef\xbb\xbf"):
        return 65001
    if data.startswith(b"\xff\xfe"):
        return 1200
    if data.startswith(b"\xfe\xff"):
        return 1201
    cut = len(data) > limit
    data = data[:limit]
    try:
        data.decode("utf-8")
        return 65001
    except UnicodeDecodeError as exc:
        if cut and exc.start >= len(data) - 3:  # 잘라 읽은 끝에서 글자가 끊긴 것뿐
            return 65001
        return 949


# ── 엑셀 암호 미리 알아보기 (OLE 복합 문서 읽기) ─────────────────
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END = 0xFFFFFFFA  # 이 값 이상이면 사슬 끝·빈칸 표시


def _excel_locked(path: Path) -> bool:
    """엑셀 열기 암호가 걸렸는지. xlsx 등은 암호가 걸리면 zip이 아니라 OLE 파일로 바뀌고,
    옛 xls는 Workbook 스트림 첫머리에 FILEPASS 기록이 있다. 알 수 없으면 False (엑셀에 맡긴다)."""
    try:
        with open(path, "rb") as f:
            if f.read(8) != _OLE_MAGIC:
                return False
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
                streams = _ole_streams(data)
                if "EncryptedPackage" in streams or "EncryptionInfo" in streams:
                    return True
                for name in ("Workbook", "Book"):
                    if name in streams:
                        return _biff_filepass(streams[name]())
    except Exception:  # noqa: BLE001 - 망가진 파일 등은 엑셀이 판단하게 둔다
        return False
    return False


def _u32(data, pos: int) -> int:
    return int.from_bytes(data[pos:pos + 4], "little")


def _ole_streams(data) -> dict[str, Callable[[], bytes]]:
    """스트림 이름 → 앞부분(최대 8KB)을 읽는 함수"""
    sec = 1 << int.from_bytes(data[30:32], "little")
    mini = 1 << int.from_bytes(data[32:34], "little")
    first_dir, cutoff, first_minifat = _u32(data, 48), _u32(data, 56), _u32(data, 60)
    difat_sec, difat_count = _u32(data, 68), _u32(data, 72)
    fat_secs = [_u32(data, 76 + 4 * i) for i in range(109)]
    for _ in range(difat_count):
        if difat_sec >= _END:
            break
        base = (difat_sec + 1) * sec
        entries = [_u32(data, base + 4 * i) for i in range(sec // 4)]
        fat_secs.extend(entries[:-1])
        difat_sec = entries[-1]
    fat: list[int] = []
    for s in fat_secs:
        if s < _END:
            base = (s + 1) * sec
            fat.extend(_u32(data, base + 4 * i) for i in range(sec // 4))

    def chain(start: int, table: list[int]):
        seen = set()
        while start < _END and start not in seen and start < len(table):
            seen.add(start)
            yield start
            start = table[start]

    def read(start: int, limit: int | None = None) -> bytes:
        out = bytearray()
        for s in chain(start, fat):
            out += data[(s + 1) * sec:(s + 2) * sec]
            if limit is not None and len(out) >= limit:
                break
        return bytes(out)

    directory = read(first_dir)
    entries = []
    for i in range(len(directory) // 128):
        e = directory[i * 128:(i + 1) * 128]
        length = int.from_bytes(e[64:66], "little")
        name = e[:max(0, length - 2)].decode("utf-16-le", "replace")
        entries.append((name, e[66], _u32(e, 116), _u32(e, 120)))
    if not entries:
        return {}
    root_start = entries[0][2]

    def opener(start: int, size: int) -> Callable[[], bytes]:
        def head() -> bytes:
            limit = min(size, 8192)
            if size >= cutoff:
                return read(start, limit)[:limit]
            minifat_raw = read(first_minifat)
            minifat = [_u32(minifat_raw, 4 * i) for i in range(len(minifat_raw) // 4)]
            ministream = read(root_start)
            out = bytearray()
            for s in chain(start, minifat):
                out += ministream[s * mini:(s + 1) * mini]
                if len(out) >= limit:
                    break
            return bytes(out[:limit])
        return head

    return {name: opener(start, size) for name, kind, start, size in entries if kind == 2}


def _biff_filepass(head: bytes) -> bool:
    pos = 0
    for _ in range(64):
        if pos + 4 > len(head):
            break
        rtype = int.from_bytes(head[pos:pos + 2], "little")
        if rtype == 0x002F:  # FILEPASS: 암호화됨
            return True
        if rtype == 0x000A:  # EOF
            break
        pos += 4 + int.from_bytes(head[pos + 2:pos + 4], "little")
    return False


# ── 프로세스와 창 ────────────────────────────────────────────
class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def _pids(exe: str) -> set[int]:
    snap = _kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return set()
    out = set()
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe.lower():
                out.add(entry.th32ProcessID)
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return out


def _alive(pids: set[int]) -> bool:
    if not pids:
        return False
    running = set()
    for exe in {info.exe for info in APPS.values()}:
        running |= _pids(exe)
    return bool(pids & running)


def _kill(pids: set[int]) -> None:
    for pid in pids:
        handle = _kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            _kernel32.TerminateProcess(handle, 1)
            _kernel32.CloseHandle(handle)


def _dialog_of(pids: set[int]) -> tuple[int, str] | None:
    """그 프로세스가 띄운, 눈에 보이는 창 하나 (창 번호, 제목)"""
    import win32gui
    import win32process

    found: list[tuple[int, str]] = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:  # noqa: BLE001
                return True
            if pid in pids:
                found.append((hwnd, win32gui.GetWindowText(hwnd).strip()))
        return True

    try:
        win32gui.EnumWindows(visit, None)
    except Exception:  # noqa: BLE001
        return None
    found = [(hwnd, "".join(ch for ch in title if not "" <= ch <= "").strip())  # 아이콘용 글자는 뺀다
             for hwnd, title in found]
    titled = [f for f in found if f[1]]
    return (titled or found or [None])[0]


class _Watch(threading.Thread):
    """변환하는 동안 그 프로그램이 확인 창을 띄우는지 지켜본다 (1.5초 넘게 떠 있으면 알린다)"""

    def __init__(self, pids: set[int], label: str, on_dialog) -> None:
        super().__init__(daemon=True)
        self.pids, self.label, self.on_dialog = pids, label, on_dialog
        self.seen: str | None = None
        self._done = threading.Event()

    def run(self) -> None:
        if not self.pids:
            return
        since = None
        shown = False
        while not self._done.wait(0.5):
            dialog = _dialog_of(self.pids)
            if dialog is None:
                if shown:
                    self.on_dialog(None, None)
                since, shown = None, False
                continue
            since = since or time.monotonic()
            if not shown and time.monotonic() - since >= 1.5:
                hwnd, title = dialog
                self.seen = title or "확인"
                shown = True
                self.on_dialog(self.label, self.seen)
                try:
                    import win32gui

                    win32gui.SetForegroundWindow(hwnd)  # 사용자가 바로 볼 수 있게 앞으로
                except Exception:  # noqa: BLE001
                    pass
        if shown:
            self.on_dialog(None, None)

    def stop(self) -> None:
        self._done.set()
