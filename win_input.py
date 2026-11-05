"""Native Win32 SendInput synthesizer, Single-Instance Guard, Steam PS-Button Guard & Cursor Scaler."""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

import psutil

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

APP_DIR = Path(__file__).resolve().parent
RESTORE_STATE_PATH = APP_DIR / ".cursor_restore.json"

SPI_SETCURSORSIZE = 0x2029
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002
ERROR_ALREADY_EXISTS = 183
SW_MINIMIZE = 6
SW_RESTORE = 9

MUTEX_NAME = "Local\\DualSenseCouchControl_SingleInstance_Mutex"
SHOW_EVENT_NAME = "Local\\DualSenseCouchControl_ShowWindow_Event"
SHOW_ACK_EVENT_NAME = "Local\\DualSenseCouchControl_ShowAck_Event"
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_REG_NAME = "DualSenseCouchControl"


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ObsidianStudio.DualSenseCouchControl.Pro.1"
        )
    except Exception:
        pass
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class SingleInstanceGuard:
    """Ensures only ONE session of DualSense Couch Control can ever run at once.

    Whenever app.py is launched, any previous/background app.py instance is cleanly
    terminated first so the new launch ALWAYS opens a fresh, visible window and
    never allows 2 sessions to run simultaneously.
    """

    def __init__(self) -> None:
        self._mutex = None
        self._show_event = None
        self._ack_event = None
        self.already_running: bool = False

        if os.environ.get("COUCH_CONTROL_SMOKE_TEST") == "1":
            return

        # Always terminate any existing app.py instance first so reopening ALWAYS works!
        self._cleanup_legacy_duplicates()

        kernel32.CreateEventW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
        kernel32.SetEvent.restype = wintypes.BOOL
        kernel32.ResetEvent.argtypes = (wintypes.HANDLE,)
        kernel32.ResetEvent.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        self._show_event = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        self._ack_event = kernel32.CreateEventW(None, False, False, SHOW_ACK_EVENT_NAME)
        self._mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)

    @staticmethod
    def _cleanup_legacy_duplicates() -> None:
        my_pid = os.getpid()
        safe_pids = {my_pid}
        try:
            me = psutil.Process(my_pid)
            for parent in me.parents():
                safe_pids.add(parent.pid)
        except Exception:
            pass

        target_script = str((APP_DIR / "app.py").resolve()).lower()
        venv_prefix = str((APP_DIR / ".venv").resolve()).lower()
        to_stop: list[psutil.Process] = []

        for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
            try:
                if proc.info["pid"] in safe_pids:
                    continue
                pname = (proc.info["name"] or "").lower()
                if not pname.startswith("python"):
                    continue
                cmdline = proc.info["cmdline"] or []
                cmd_joined = " ".join(cmdline).lower()
                pexe = (proc.info.get("exe") or "").lower()

                matched = False
                if pexe.startswith(venv_prefix) and "app.py" in cmd_joined:
                    matched = True
                else:
                    for arg in cmdline:
                        try:
                            if str(Path(arg).resolve()).lower() == target_script:
                                matched = True
                                break
                        except Exception:
                            folder_name = APP_DIR.name.lower()
                            if folder_name in arg.lower() and arg.lower().endswith("app.py"):
                                matched = True
                                break
                if matched:
                    to_stop.append(proc)
            except Exception:
                continue

        for p in to_stop:
            try:
                p.terminate()
            except Exception:
                pass
        if to_stop:
            _, alive = psutil.wait_procs(to_stop, timeout=0.45)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
            if alive:
                psutil.wait_procs(alive, timeout=0.25)

    def check_show_requested(self) -> bool:
        """Non-blocking check if a second launch asked us to focus our window."""
        if not self._show_event:
            return False
        res = kernel32.WaitForSingleObject(self._show_event, 0)
        return res == 0

    def ack_show_requested(self) -> None:
        """Confirm to the second launch that our UI loop brought the window to front."""
        if self._ack_event:
            kernel32.SetEvent(self._ack_event)

    def release(self) -> None:
        try:
            if self._mutex:
                kernel32.CloseHandle(self._mutex)
                self._mutex = None
            if self._show_event:
                kernel32.CloseHandle(self._show_event)
                self._show_event = None
            if self._ack_event:
                kernel32.CloseHandle(self._ack_event)
                self._ack_event = None
        except Exception:
            pass


class SteamPSButtonGuard:
    """Prevents pressing the PS Button from popping up Steam or Big Picture Mode
    while Couch Control is active.
    """

    def __init__(self) -> None:
        self._last_non_steam_hwnd: int = 0
        self._guard_until: float = 0.0
        self._last_sample_t: float = 0.0
        self._pid_is_steam_cache: dict[int, bool] = {}
        self._orig_gamebar_nexus: int | None = None
        self._suppress_gamebar_nexus()
        atexit.register(self.restore)

    def _suppress_gamebar_nexus(self) -> None:
        """Prevent Xbox Game Bar from hijacking the PS Guide button while active."""
        try:
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar"
            ) as k:
                try:
                    val, _ = winreg.QueryValueEx(k, "UseNexusForGameBarEnabled")
                    self._orig_gamebar_nexus = int(val)
                except FileNotFoundError:
                    self._orig_gamebar_nexus = None
                winreg.SetValueEx(k, "UseNexusForGameBarEnabled", 0, winreg.REG_DWORD, 0)
        except Exception:
            pass

    def restore(self) -> None:
        if self._orig_gamebar_nexus is not None:
            try:
                with winreg.CreateKey(
                    winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar"
                ) as k:
                    winreg.SetValueEx(
                        k,
                        "UseNexusForGameBarEnabled",
                        0,
                        winreg.REG_DWORD,
                        self._orig_gamebar_nexus,
                    )
            except Exception:
                pass

    def _hwnd_is_steam(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        p = int(pid.value)
        if not p:
            return False
        cached = self._pid_is_steam_cache.get(p)
        if cached is not None:
            return cached
        is_steam = False
        try:
            name = psutil.Process(p).name().lower()
            is_steam = name in ("steam.exe", "steamwebhelper.exe")
        except Exception:
            is_steam = False
        if len(self._pid_is_steam_cache) > 256:
            self._pid_is_steam_cache.clear()
        self._pid_is_steam_cache[p] = is_steam
        return is_steam

    def notify_ps_button_pressed(self) -> None:
        """Arm a 1.6-second high-speed guard window right when the PS button is pressed."""
        self._guard_until = time.perf_counter() + 1.6

    def tick(self, now: float, enabled: bool) -> bool:
        """Call inside the 120 Hz loop. Returns True if a Steam popup was intercepted."""
        if not enabled:
            return False

        # During guard window, check every single frame (~8ms) for Steam stealing focus!
        if now <= self._guard_until:
            fg = user32.GetForegroundWindow()
            if fg and self._hwnd_is_steam(fg):
                try:
                    user32.ShowWindow(fg, SW_MINIMIZE)
                    if self._last_non_steam_hwnd and user32.IsWindow(self._last_non_steam_hwnd):
                        user32.SetForegroundWindow(self._last_non_steam_hwnd)
                except Exception:
                    pass
                return True
            return False

        # Outside guard window, sample non-Steam foreground window every 150ms
        if now - self._last_sample_t >= 0.15:
            self._last_sample_t = now
            fg = user32.GetForegroundWindow()
            if fg and not self._hwnd_is_steam(fg):
                self._last_non_steam_hwnd = fg
        return False


class StartupManager:
    """Manages 'Launch at Windows Startup' registry entry cleanly."""

    @staticmethod
    def is_enabled() -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH) as k:
                val, _ = winreg.QueryValueEx(k, RUN_REG_NAME)
                return bool(val)
        except Exception:
            return False

    @staticmethod
    def set_enabled(enable: bool) -> bool:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH) as k:
                if enable:
                    pythonw = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else Path(sys.executable))
                    script = str((APP_DIR / "app.py").resolve())
                    cmd = f'"{exe}" "{script}"'
                    winreg.SetValueEx(k, RUN_REG_NAME, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(k, RUN_REG_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except Exception:
            return False


class CursorSizeManager:
    """Dynamically enlarges the Windows system cursor while Couch Control is active
    and guarantees restoring normal size (32px) on pause, close, crash, or kill.
    """

    def __init__(self, normal_size: int = 32) -> None:
        self.normal_size: int = max(32, min(128, int(normal_size)))
        self._currently_applied_size: int | None = None
        self._watchdog_spawned: bool = False
        self._smoke_test: bool = os.environ.get("COUCH_CONTROL_SMOKE_TEST") == "1"

        # Clean up any legacy poisoned .cursor_restore.json file
        try:
            if RESTORE_STATE_PATH.exists():
                RESTORE_STATE_PATH.unlink()
        except Exception:
            pass

        atexit.register(self.restore)
        self._register_console_ctrl_handler()

    def _register_console_ctrl_handler(self) -> None:
        """Restore normal cursor immediately if console/terminal/logoff/shutdown occurs."""
        if self._smoke_test:
            return
        try:
            handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def _ctrl_handler(_ctrl_type: int) -> bool:
                try:
                    self.restore()
                except Exception:
                    pass
                return False

            self._console_ctrl_cb = handler_type(_ctrl_handler)
            kernel32.SetConsoleCtrlHandler(self._console_ctrl_cb, True)
        except Exception:
            pass

    def _ensure_watchdog(self) -> None:
        """Spawn a zero-CPU kernel watchdog so even Task Manager End Task restores 32px."""
        if self._watchdog_spawned or self._smoke_test:
            return
        self._watchdog_spawned = True
        try:
            watchdog_script = APP_DIR / "cursor_watchdog.py"
            if not watchdog_script.exists():
                return
            pythonw = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"
            exe = str(pythonw if pythonw.exists() else Path(sys.executable))
            cmd = [exe, str(watchdog_script), str(os.getpid()), str(self.normal_size)]
            try:
                subprocess.Popen(
                    cmd,
                    creationflags=0x01000000 | 0x08000000,  # CREATE_BREAKAWAY_FROM_JOB | CREATE_NO_WINDOW
                    close_fds=True,
                )
            except Exception:
                subprocess.Popen(
                    cmd,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                    close_fds=True,
                )
        except Exception:
            pass

    @staticmethod
    def _apply_win32_cursor_size(size_px: int, acc_scale: int) -> None:
        size_px = max(32, min(256, int(size_px)))
        acc_scale = max(1, min(15, int(acc_scale)))
        try:
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors"
            ) as k:
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

    def apply_couch_size(self, size_px: int) -> None:
        if self._smoke_test:
            return
        size_px = max(32, min(256, int(size_px)))
        self._ensure_watchdog()
        if self._currently_applied_size == size_px:
            return
        scale = max(1, min(15, round((size_px - 32) / 16) + 1))
        self._apply_win32_cursor_size(size_px, scale)
        self._currently_applied_size = size_px

    def restore(self) -> None:
        if self._smoke_test:
            return
        normal_px = max(32, min(128, int(self.normal_size)))
        normal_scale = max(1, min(15, round((normal_px - 32) / 16) + 1))
        self._apply_win32_cursor_size(normal_px, normal_scale)
        self._currently_applied_size = None
        try:
            if RESTORE_STATE_PATH.exists():
                RESTORE_STATE_PATH.unlink()
        except Exception:
            pass


class ExternalWindowTracker:
    """Remembers the most recently active window outside our own Control Panel
    so panel toolbar buttons (like Zoom In / Out / Reset) target your active app!
    """

    def __init__(self) -> None:
        self._my_pid = os.getpid()
        self._last_ext_hwnd: int = 0

    def sample(self) -> None:
        try:
            fg = user32.GetForegroundWindow()
            if not fg:
                return
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if int(pid.value) != self._my_pid:
                self._last_ext_hwnd = fg
        except Exception:
            pass

    def focus_last_external(self) -> None:
        try:
            fg = user32.GetForegroundWindow()
            pid = wintypes.DWORD(0)
            if fg:
                user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if int(pid.value) == self._my_pid and self._last_ext_hwnd and user32.IsWindow(self._last_ext_hwnd):
                user32.SetForegroundWindow(self._last_ext_hwnd)
                time.sleep(0.03)
        except Exception:
            pass


def get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


def restore_antigravity_zoom_if_needed(synth: "InputSynthesizer") -> None:
    """If Antigravity's Electron zoom level was zoomed out (< 0), automatically focus
    Antigravity once and send Ctrl + 0 (Reset Zoom) so the user can read their screen!
    """
    if os.environ.get("COUCH_CONTROL_SMOKE_TEST") == "1":
        return
    try:
        pref_path = (
            Path(os.environ.get("APPDATA", ""))
            / "Antigravity"
            / "Preferences"
        )
        if not pref_path.exists():
            return
        raw = pref_path.read_text(encoding="utf-8", errors="ignore")
        if '"127.0.0.1":-' not in raw and '"127.0.0.1": -' not in raw:
            return

        target_hwnds: list[int] = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd: int, _lparam: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if "antigravity" in title.lower():
                        target_hwnds.append(hwnd)
                        return False
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    try:
                        pname = psutil.Process(int(pid.value)).name().lower()
                        if "antigravity" in pname:
                            target_hwnds.append(hwnd)
                            return False
                    except Exception:
                        pass
            return True

        cb = WNDENUMPROC(_enum_cb)
        user32.EnumWindows(cb, 0)
        if target_hwnds:
            ag_hwnd = target_hwnds[0]
            user32.ShowWindow(ag_hwnd, SW_RESTORE)
            user32.SetForegroundWindow(ag_hwnd)
            time.sleep(0.08)
            synth.zoom_reset()
            time.sleep(0.06)
    except Exception:
        pass


ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_LWIN = 0x5B
VK_OEM_PLUS = 0xBB
VK_OEM_MINUS = 0xBD
VK_0 = 0x30

VK_C = 0x43
VK_D = 0x44
VK_H = 0x48
VK_O = 0x4F
VK_S = 0x53
VK_T = 0x54
VK_V = 0x56
VK_Z = 0x5A
VK_F11 = 0x7A
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_PLAY_PAUSE = 0xB3

EXTENDED_VKS = {VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_LWIN}

SHELL_NAV_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "SecondaryTrayWnd",
    "XamlExplorerHostIslandWindow",
    "MultitaskingViewFrame",
    "Windows.UI.Core.CoreWindow",
    "CabinetWClass",
}


def is_shell_navigation_foreground() -> bool:
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, buf, 128)
        return buf.value in SHELL_NAV_CLASSES
    except Exception:
        return False


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _send_inputs(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return int(user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)))


def _make_key(vk: int, up: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, 0) & 0xFFFF
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _make_mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(
        dx=dx,
        dy=dy,
        mouseData=data & 0xFFFFFFFF,
        dwFlags=flags,
        time=0,
        dwExtraInfo=0,
    )
    return inp


class InputSynthesizer:
    """Stateful input helper with sub-pixel cursor & smooth-scroll accumulators."""

    def __init__(self) -> None:
        self._rem_x: float = 0.0
        self._rem_y: float = 0.0
        self._rem_vscroll: float = 0.0
        self._rem_hscroll: float = 0.0
        self._left_down: bool = False
        self._right_down: bool = False
        self._middle_down: bool = False

    def move_relative(self, dx: float, dy: float) -> None:
        self._rem_x += dx
        self._rem_y += dy
        ix = int(self._rem_x)
        iy = int(self._rem_y)
        if ix != 0 or iy != 0:
            self._rem_x -= ix
            self._rem_y -= iy
            _send_inputs([_make_mouse(MOUSEEVENTF_MOVE, dx=ix, dy=iy)])

    def scroll(self, vertical: float = 0.0, horizontal: float = 0.0) -> None:
        inputs: list[INPUT] = []
        if vertical != 0.0:
            self._rem_vscroll += vertical
            iv = int(self._rem_vscroll)
            if iv != 0:
                self._rem_vscroll -= iv
                inputs.append(_make_mouse(MOUSEEVENTF_WHEEL, data=iv))
        if horizontal != 0.0:
            self._rem_hscroll += horizontal
            ih = int(self._rem_hscroll)
            if ih != 0:
                self._rem_hscroll -= ih
                inputs.append(_make_mouse(MOUSEEVENTF_HWHEEL, data=ih))
        if inputs:
            _send_inputs(inputs)

    def set_left_button(self, pressed: bool) -> None:
        if pressed and not self._left_down:
            self._left_down = True
            _send_inputs([_make_mouse(MOUSEEVENTF_LEFTDOWN)])
        elif not pressed and self._left_down:
            self._left_down = False
            _send_inputs([_make_mouse(MOUSEEVENTF_LEFTUP)])

    def click_left(self) -> None:
        _send_inputs([
            _make_mouse(MOUSEEVENTF_LEFTDOWN),
            _make_mouse(MOUSEEVENTF_LEFTUP),
        ])

    def click_right(self) -> None:
        _send_inputs([
            _make_mouse(MOUSEEVENTF_RIGHTDOWN),
            _make_mouse(MOUSEEVENTF_RIGHTUP),
        ])

    def click_middle(self) -> None:
        _send_inputs([
            _make_mouse(MOUSEEVENTF_MIDDLEDOWN),
            _make_mouse(MOUSEEVENTF_MIDDLEUP),
        ])

    def release_all_buttons(self) -> None:
        if self._left_down:
            self.set_left_button(False)
        if self._right_down:
            self._right_down = False
            _send_inputs([_make_mouse(MOUSEEVENTF_RIGHTUP)])
        if self._middle_down:
            self._middle_down = False
            _send_inputs([_make_mouse(MOUSEEVENTF_MIDDLEUP)])

    def tap_key(self, vk: int) -> None:
        _send_inputs([_make_key(vk, up=False), _make_key(vk, up=True)])

    def send_combo(self, *vks: int, hold_ms: int = 18) -> None:
        if not vks:
            return
        downs = [_make_key(vk, up=False) for vk in vks]
        ups = [_make_key(vk, up=True) for vk in reversed(vks)]
        _send_inputs(downs)
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        _send_inputs(ups)

    def toggle_voice_typing(self) -> None:
        self.send_combo(VK_LWIN, VK_H, hold_ms=25)

    def send_enter(self, newline_only: bool = False) -> None:
        if newline_only:
            self.send_combo(VK_SHIFT, VK_RETURN, hold_ms=10)
        else:
            self.tap_key(VK_RETURN)

    def send_backspace(self, delete_word: bool = False) -> None:
        if delete_word:
            self.send_combo(VK_CONTROL, VK_BACK, hold_ms=10)
        else:
            self.tap_key(VK_BACK)

    def send_escape(self) -> None:
        self.tap_key(VK_ESCAPE)

    def send_copy(self) -> None:
        self.send_combo(VK_CONTROL, VK_C, hold_ms=12)

    def send_paste(self) -> None:
        self.send_combo(VK_CONTROL, VK_V, hold_ms=12)

    def send_undo(self) -> None:
        self.send_combo(VK_CONTROL, VK_Z, hold_ms=12)

    def zoom_in(self, use_wheel: bool = False) -> None:
        if use_wheel:
            _send_inputs([_make_key(VK_CONTROL, up=False)])
            time.sleep(0.01)
            _send_inputs([_make_mouse(MOUSEEVENTF_WHEEL, data=120)])
            time.sleep(0.01)
            _send_inputs([_make_key(VK_CONTROL, up=True)])
        else:
            # Electron (Antigravity / Claude) & browsers require Ctrl+Shift+= (Ctrl + Plus) for role:zoomIn!
            self.send_combo(VK_CONTROL, VK_SHIFT, VK_OEM_PLUS, hold_ms=14)

    def zoom_out(self, use_wheel: bool = False) -> None:
        if use_wheel:
            _send_inputs([_make_key(VK_CONTROL, up=False)])
            time.sleep(0.01)
            _send_inputs([_make_mouse(MOUSEEVENTF_WHEEL, data=-120)])
            time.sleep(0.01)
            _send_inputs([_make_key(VK_CONTROL, up=True)])
        else:
            self.send_combo(VK_CONTROL, VK_OEM_MINUS, hold_ms=14)

    def zoom_reset(self) -> None:
        self.send_combo(VK_CONTROL, VK_0, hold_ms=14)

    def focus_next_box(self) -> None:
        self.tap_key(VK_TAB)

    def focus_prev_box(self) -> None:
        self.send_combo(VK_SHIFT, VK_TAB, hold_ms=10)

    def next_tab(self) -> None:
        self.send_combo(VK_CONTROL, VK_TAB, hold_ms=12)

    def prev_tab(self) -> None:
        self.send_combo(VK_CONTROL, VK_SHIFT, VK_TAB, hold_ms=12)

    def open_task_view(self) -> None:
        self.send_combo(VK_LWIN, VK_TAB, hold_ms=25)

    def focus_taskbar(self) -> None:
        self.send_combo(VK_LWIN, VK_T, hold_ms=25)

    def show_desktop(self) -> None:
        self.send_combo(VK_LWIN, VK_D, hold_ms=25)

    def take_screenshot(self) -> None:
        self.send_combo(VK_LWIN, VK_SHIFT, VK_S, hold_ms=25)

    def toggle_onscreen_keyboard(self) -> None:
        self.send_combo(VK_LWIN, VK_CONTROL, VK_O, hold_ms=25)

    def media_play_pause(self) -> None:
        self.tap_key(VK_MEDIA_PLAY_PAUSE)

    def volume_up(self) -> None:
        self.tap_key(VK_VOLUME_UP)

    def volume_down(self) -> None:
        self.tap_key(VK_VOLUME_DOWN)

    def volume_mute(self) -> None:
        self.tap_key(VK_VOLUME_MUTE)

    def toggle_fullscreen(self) -> None:
        self.tap_key(VK_F11)

