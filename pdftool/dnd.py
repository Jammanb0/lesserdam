"""탐색기에서 파일·폴더를 창에 끌어다 놓기 (Windows WM_DROPFILES)

창 안의 모든 칸(목록, 버튼, 빈 곳…)이 각자 파일을 받게 하고, 창 프로시저를 바꿔 끼워 WM_DROPFILES만 받아 둔다.
이 콜백은 Tcl이 메시지를 처리하는 도중에 불리므로 여기서는 tkinter를 부르지 않고, 받은 경로를 쌓아 두기만 한다.
화면 쪽에서 take()로 꺼내 간다.
"""
from __future__ import annotations

import ctypes
from collections import deque
from ctypes import wintypes

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32")
_user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
_user32.SetWindowLongPtrW.restype = ctypes.c_void_p
_user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.CallWindowProcW.restype = LRESULT
_user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.DefWindowProcW.restype = LRESULT
_shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
_shell32.DragAcceptFiles.restype = None
_shell32.DragQueryFileW.argtypes = (wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT)
_shell32.DragQueryFileW.restype = wintypes.UINT
_shell32.DragFinish.argtypes = (wintypes.HANDLE,)
_shell32.DragFinish.restype = None


class FileDrop:
    """hwnds 창들에 놓인 파일 경로를 모은다"""

    def __init__(self, hwnds: list[int]) -> None:
        self._dropped: deque[list[str]] = deque()
        self._proc = WNDPROC(self._wndproc)  # 창이 살아 있는 동안 참조를 붙잡아 둬야 한다
        self._old: dict[int, int] = {}
        for hwnd in dict.fromkeys(hwnds):
            old = _user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p))
            if old:
                self._old[hwnd] = old
                _shell32.DragAcceptFiles(hwnd, True)
        if not self._old:
            raise ctypes.WinError(ctypes.get_last_error())

    @property
    def hwnds(self) -> list[int]:
        return list(self._old)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                paths = []
                for i in range(_shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)):
                    size = _shell32.DragQueryFileW(wparam, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(size)
                    _shell32.DragQueryFileW(wparam, i, buf, size)
                    paths.append(buf.value)
                if paths:
                    self._dropped.append(paths)
            finally:
                _shell32.DragFinish(wparam)
            return 0
        old = self._old.get(hwnd)
        if old is None:
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        return _user32.CallWindowProcW(old, hwnd, msg, wparam, lparam)

    def take(self) -> list[list[str]]:
        """그동안 놓인 파일 묶음들 (한 번 놓을 때마다 한 묶음)"""
        out = []
        while self._dropped:
            out.append(self._dropped.popleft())
        return out

    def close(self) -> None:
        """원래 창 프로시저로 되돌린다 (창을 닫기 전에 부른다). 콜백 자체는 계속 살려 둔다."""
        for hwnd, old in self._old.items():
            _shell32.DragAcceptFiles(hwnd, False)
            _user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, old)
