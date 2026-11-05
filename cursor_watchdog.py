"""Zero-CPU kernel watchdog that guarantees Windows cursor size resets to normal (32px)
whenever DualSense Couch Control closes — even on crash, terminal close, or Task Manager End Task.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time
import winreg

SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF
SPI_SETCURSORSIZE = 0x2029
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002
MUTEX_NAME = "Local\\DualSenseCouchControl_SingleInstance_Mutex"


def _force_cursor_size(size_px: int) -> None:
    size_px = max(32, min(256, int(size_px)))
    acc_scale = max(1, min(15, round((size_px - 32) / 16) + 1))
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as k:
            winreg.SetValueEx(k, "CursorBaseSize", 0, winreg.REG_DWORD, size_px)
    except Exception:
        pass
    try:
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility"
        ) as k:
            winreg.SetValueEx(k, "CursorSize", 0, winreg.REG_DWORD, acc_scale)
    except Exception:
        pass
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SystemParametersInfoW.argtypes = (
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            wintypes.UINT,
        )
        user32.SystemParametersInfoW.restype = wintypes.BOOL
        user32.SystemParametersInfoW(
            SPI_SETCURSORSIZE,
            0,
            ctypes.c_void_p(size_px),
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
        )
    except Exception:
        pass
    try:
        restore_file = Path(__file__).resolve().parent / ".cursor_restore.json"
        if restore_file.exists():
            restore_file.unlink()
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) < 2:
        return
    try:
        parent_pid = int(sys.argv[1])
    except ValueError:
        return
    normal_size = 32
    if len(sys.argv) >= 3:
        try:
            normal_size = int(sys.argv[2])
        except ValueError:
            normal_size = 32

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    h_proc = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
    if h_proc:
        kernel32.WaitForSingleObject(h_proc, INFINITE)
        kernel32.CloseHandle(h_proc)

    # Brief settle delay in case a new launch replaced the old instance
    time.sleep(0.35)

    # Only restore if no active Couch Control instance is currently holding the mutex
    h_mutex = kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
    if h_mutex:
        kernel32.CloseHandle(h_mutex)
        return

    _force_cursor_size(normal_size)


if __name__ == "__main__":
    main()
