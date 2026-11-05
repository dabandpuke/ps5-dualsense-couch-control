"""PS5 DualSense Couch Control — Obsidian Minimal Pro Studio, Tray, Cursor Halo & TV HUD."""

from __future__ import annotations

import ctypes
import math
import os
import queue
import signal
import sys
import threading
import tkinter as tk
from typing import Any, Callable
import webbrowser

import pystray

from audio_manager import AudioManager, MicInfo
from config import AppConfig, CONFIG_PATH, HALO_COLORS, LIGHTBAR_PRESETS
from controller_engine import ControllerEngine
from obsidian_widgets import (
    ACCENT,
    ACCENT_LIGHT,
    BG_ACTIVE_PILL,
    BG_APP,
    BG_CARD,
    BG_DOCK,
    BG_ELEVATED,
    BG_HOVER,
    BORDER_CARD,
    BORDER_HOVER,
    BORDER_SUBTLE,
    DpiScaler,
    FONT_MONO,
    FONT_UI,
    LOGO_ICO_PATH,
    PrecisionSlider,
    ProSelect,
    ProToggle,
    SegmentedBar,
    STATUS_DANGER_BG,
    STATUS_DANGER_BORDER,
    STATUS_OK,
    STATUS_OK_BG,
    STATUS_PEAK,
    STATUS_WARN,
    STATUS_WARN_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    VectorIconCache,
    create_tray_icon_image,
    format_clean_toast,
    load_master_logo,
)
from win_input import (
    CursorSizeManager,
    ExternalWindowTracker,
    InputSynthesizer,
    SingleInstanceGuard,
    StartupManager,
    enable_dpi_awareness,
    get_cursor_pos,
)

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

enable_dpi_awareness()

user32 = ctypes.WinDLL("user32", use_last_error=True)
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
TRANSPARENT_KEY = "#010203"


def _make_overlay_window_style(win: tk.Toplevel, click_through: bool = True) -> None:
    try:
        win.update_idletasks()
        wid = win.winfo_id()
        hwnd = user32.GetParent(wid) or wid
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.GetWindowLongW)
        style = get_long(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if click_through:
            style |= WS_EX_TRANSPARENT
        set_long(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


# =============================================================================
# ACTION OPTION TABLES & WORKFLOW PROFILES
# =============================================================================
TOUCHPAD_OPTIONS: list[tuple[str, str]] = [
    ("All Open Programs (Win + Tab)", "task_view"),
    ("Quick Taskbar (Win + T)", "taskbar"),
    ("Show Desktop (Win + D)", "desktop"),
    ("Left Mouse Click", "left_click"),
    ("Middle Mouse Click (Open/Close Tab)", "middle_click"),
    ("Media Play / Pause", "play_pause"),
    ("Fullscreen Toggle (F11)", "fullscreen"),
    ("Voice Typing (Win + H)", "voice_typing"),
    ("Cycle Activity Preset", "cycle_preset"),
    ("Zoom Text In (Ctrl +)", "zoom_in"),
    ("Zoom Text Out (Ctrl -)", "zoom_out"),
    ("Reset Text Zoom (Ctrl + 0)", "zoom_reset"),
]

PS_BUTTON_OPTIONS: list[tuple[str, str]] = [
    ("Show / Hide Control Panel", "toggle_panel"),
    ("Cycle Activity Preset", "cycle_preset"),
    ("Block Steam Only (No Action)", "none"),
    ("All Open Programs (Win + Tab)", "task_view"),
    ("Toggle Couch Guide HUD", "toggle_hud"),
    ("Pause / Resume Game Mode", "game_mode"),
    ("Media Play / Pause", "play_pause"),
    ("Fullscreen Toggle (F11)", "fullscreen"),
    ("Zoom Text In (Ctrl +)", "zoom_in"),
    ("Reset Text Zoom (Ctrl + 0)", "zoom_reset"),
]

CREATE_OPTIONS: list[tuple[str, str]] = [
    ("Quick Taskbar (Win + T)", "taskbar"),
    ("Show Desktop (Win + D)", "desktop"),
    ("All Open Programs (Win + Tab)", "task_view"),
    ("Screenshot (Win + Shift + S)", "screenshot"),
    ("Media Play / Pause", "play_pause"),
    ("Fullscreen Toggle (F11)", "fullscreen"),
    ("Mute / Unmute TV Audio", "volume_mute"),
    ("Cycle Activity Preset", "cycle_preset"),
    ("Zoom Text In (Ctrl +)", "zoom_in"),
    ("Zoom Text Out (Ctrl -)", "zoom_out"),
    ("Reset Text Zoom (Ctrl + 0)", "zoom_reset"),
]

TRIANGLE_OPTIONS: list[tuple[str, str]] = [
    ("Voice Typing (Win + H)", "voice_typing"),
    ("Cycle Active Microphone", "cycle_mic"),
    ("Media Play / Pause", "play_pause"),
    ("Fullscreen Toggle (F11)", "fullscreen"),
    ("Cycle Activity Preset", "cycle_preset"),
    ("Copy Selection (Ctrl + C)", "copy"),
    ("Paste Clipboard (Ctrl + V)", "paste"),
    ("Zoom Text In (Ctrl +)", "zoom_in"),
    ("Zoom Text Out (Ctrl -)", "zoom_out"),
    ("Reset Text Zoom (Ctrl + 0)", "zoom_reset"),
]

L3_OPTIONS: list[tuple[str, str]] = [
    ("On-Screen Keyboard", "osk"),
    ("Media Play / Pause", "play_pause"),
    ("Middle Mouse Click (Open/Close Tab)", "middle_click"),
    ("Fullscreen Toggle (F11)", "fullscreen"),
    ("Volume Down", "volume_down"),
    ("Mute / Unmute TV Audio", "volume_mute"),
    ("Cycle Activity Preset", "cycle_preset"),
    ("Zoom Text Out (Ctrl -)", "zoom_out"),
    ("Zoom Text In (Ctrl +)", "zoom_in"),
    ("Reset Text Zoom (Ctrl + 0)", "zoom_reset"),
    ("Copy Selection (Ctrl + C)", "copy"),
    ("Paste Clipboard (Ctrl + V)", "paste"),
]

R3_OPTIONS: list[tuple[str, str]] = [
    ("Cycle Active Microphone", "cycle_mic"),
    ("Media Play / Pause", "play_pause"),
    ("Middle Mouse Click (Open/Close Tab)", "middle_click"),
    ("Fullscreen Toggle (F11)", "fullscreen"),
    ("Volume Up", "volume_up"),
    ("Mute / Unmute TV Audio", "volume_mute"),
    ("Cycle Activity Preset", "cycle_preset"),
    ("Zoom Text In (Ctrl +)", "zoom_in"),
    ("Zoom Text Out (Ctrl -)", "zoom_out"),
    ("Reset Text Zoom (Ctrl + 0)", "zoom_reset"),
    ("Copy Selection (Ctrl + C)", "copy"),
    ("Paste Clipboard (Ctrl + V)", "paste"),
]

ZOOM_MODE_OPTIONS: list[tuple[str, str]] = [
    ("Ctrl + Plus / Minus (Apps & Chats)", "ctrl_plus"),
    ("Ctrl + Scroll Wheel (Web & Media)", "ctrl_wheel"),
]

HUD_SCALE_FONTS: dict[str, tuple[int, int]] = {
    "Normal": (12, 10),
    "Large": (14, 11),
    "XL TV": (18, 13),
}

WORKFLOW_PRESETS: list[dict[str, Any]] = [
    {
        "id": "ai_workspace",
        "name": "AI & Voice Chat",
        "spec": "80px · △ Voice · Pad Win+Tab · R3 Mic",
        "paused": False,
        "overrides": {
            "enlarge_cursor": True,
            "couch_cursor_size": 80,
            "cursor_halo_enabled": False,
            "cursor_speed": 7.5,
            "precision_multiplier": 0.35,
            "turbo_multiplier": 2.20,
            "scroll_speed": 12.0,
            "deadzone": 0.11,
            "touchpad_press_action": "task_view",
            "create_button_action": "taskbar",
            "triangle_button_action": "voice_typing",
            "l3_button_action": "osk",
            "r3_button_action": "cycle_mic",
            "lightbar_preset": "PS Blue",
            "hud_scale": "Large",
        },
    },
    {
        "id": "living_room_tv",
        "name": "10ft TV & Web Browsing",
        "spec": "160px+Halo · L3 MidClick · R3 Fullscreen",
        "paused": False,
        "overrides": {
            "enlarge_cursor": True,
            "couch_cursor_size": 160,
            "cursor_halo_enabled": True,
            "cursor_halo_color": "PlayStation Blue",
            "cursor_halo_size": 72,
            "cursor_speed": 10.5,
            "precision_multiplier": 0.35,
            "turbo_multiplier": 2.50,
            "scroll_speed": 16.0,
            "deadzone": 0.12,
            "touchpad_press_action": "task_view",
            "create_button_action": "taskbar",
            "triangle_button_action": "voice_typing",
            "l3_button_action": "middle_click",
            "r3_button_action": "fullscreen",
            "lightbar_preset": "Cyan",
            "hud_scale": "XL TV",
        },
    },
    {
        "id": "media_cinema",
        "name": "Cinema & Media Remote",
        "spec": "112px · △ Play/Pause · L3/R3 Vol -/+",
        "paused": False,
        "overrides": {
            "enlarge_cursor": True,
            "couch_cursor_size": 112,
            "cursor_halo_enabled": False,
            "cursor_speed": 6.5,
            "precision_multiplier": 0.35,
            "turbo_multiplier": 2.00,
            "scroll_speed": 10.0,
            "deadzone": 0.12,
            "touchpad_press_action": "fullscreen",
            "create_button_action": "volume_mute",
            "triangle_button_action": "play_pause",
            "l3_button_action": "volume_down",
            "r3_button_action": "volume_up",
            "lightbar_preset": "Purple",
            "hud_scale": "XL TV",
        },
    },
    {
        "id": "precision_desktop",
        "name": "Precision Desktop & Code",
        "spec": "64px · 5.5 px/f · △ Copy · R3 Paste",
        "paused": False,
        "overrides": {
            "enlarge_cursor": True,
            "couch_cursor_size": 64,
            "cursor_halo_enabled": False,
            "cursor_speed": 5.5,
            "precision_multiplier": 0.25,
            "turbo_multiplier": 1.90,
            "scroll_speed": 9.0,
            "deadzone": 0.08,
            "touchpad_press_action": "task_view",
            "create_button_action": "screenshot",
            "triangle_button_action": "copy",
            "l3_button_action": "osk",
            "r3_button_action": "paste",
            "lightbar_preset": "Emerald",
            "hud_scale": "Normal",
        },
    },
    {
        "id": "game_mode",
        "name": "Game Mode (Bypass)",
        "spec": "Synthesis Paused · 32px Native Cursor",
        "paused": True,
        "overrides": {},
    },
]


def _lookup_option_label(opts: list[tuple[str, str]], key: str) -> str:
    for lbl, k in opts:
        if k == key:
            return lbl
    return key


class CouchControlApp:
    """Obsidian Minimal Pro Single-Instance Studio for PS5 DualSense Couch Control."""

    def __init__(
        self,
        instance_guard: SingleInstanceGuard | None = None,
        smoke_test: bool = False,
    ) -> None:
        self.instance_guard = instance_guard
        self.smoke_test = smoke_test
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.config = AppConfig.load() if not smoke_test else self._load_config_readonly()
        if not smoke_test:
            self.config.run_at_startup = StartupManager.is_enabled()

        self.cursor_mgr = CursorSizeManager(
            normal_size=self.config.normal_cursor_size
        )
        self.ext_tracker = ExternalWindowTracker()
        self.synth = InputSynthesizer()
        self.audio = AudioManager(on_toast=self._enqueue_toast)
        self.engine = ControllerEngine(
            config=self.config,
            input_synth=self.synth,
            on_toast=self._enqueue_toast,
            on_toggle_hud=lambda: self.ui_queue.put(("toggle_hud", None)),
            on_toggle_panel=lambda: self.ui_queue.put(("toggle_panel", None)),
            on_cycle_mic=lambda: self.ui_queue.put(("cycle_mic", None)),
            on_cycle_preset=lambda: self.ui_queue.put(("cycle_preset", None)),
            on_pause_changed=lambda _paused: self.ui_queue.put(("sync_pause", None)),
        )

        if not smoke_test:
            for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
                sig = getattr(signal, sig_name, None)
                if sig is not None:
                    try:
                        signal.signal(sig, lambda _s, _f: self.ui_queue.put(("quit", None)))
                    except Exception:
                        pass

        self.root = tk.Tk()
        if smoke_test:
            self.root.withdraw()

        self.scaler = DpiScaler(self.root)
        self.icons = VectorIconCache(self.root, self.scaler)

        self._toast_after_id: str | None = None
        self._hud_visible: bool = False
        self._halo_shown: bool = False
        self._tray_notified_once: bool = False
        self._tray_ready: bool = False
        self._shutting_down: bool = False
        self._last_tray_state: tuple[bool, bool] | None = None
        self._last_engine_action: str = "Ready"

        # UI state
        self.active_preset_id: str | None = None
        self.active_category: str = "all"
        self.cheat_sheet_open: bool = False
        self.demo_telemetry: bool = False
        self._tick_count: int = 0
        self._peak_hold_seg: int = 0
        self._peak_decay: int = 0
        self._pulse_btn: str | None = None
        self._pulse_ticks: int = 0
        self._select_widgets: list[ProSelect] = []
        self._cards: list[dict[str, Any]] = []
        self._preset_rows: dict[str, dict[str, Any]] = {}
        self._mic_choices: list[tuple[str, str]] = [("Scanning Audio Endpoints...", "none")]

        self._configure_window()
        self._build_layout()
        self._build_toast_overlay()
        self._build_hud_overlay()
        self._build_cursor_halo()

        self.active_preset_id = self._detect_matching_preset()
        self._sync_controls_from_config(preset_id=self.active_preset_id, animate_toggles=False)

        if not smoke_test:
            self._start_tray()
            self._sync_cursor_size()
            self._refresh_audio_ui()
            self.engine.start()

            if self.config.start_minimized:
                self.root.withdraw()
            else:
                self.root.after(40, self.show_window)

            self.root.after(33, self._ui_fast_tick)
            self.root.after(2200, self._ui_audio_device_tick)

    @staticmethod
    def _load_config_readonly() -> AppConfig:
        if CONFIG_PATH.exists():
            try:
                import json

                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                valid_keys = set(AppConfig.__dataclass_fields__.keys())
                return AppConfig(**{k: v for k, v in raw.items() if k in valid_keys})
            except Exception:
                pass
        return AppConfig()

    @staticmethod
    def _pil_to_png_bytes(img) -> bytes:
        import io

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _px(self, v: float) -> int:
        return self.scaler.px(v)

    def _bd(self, v: int = 1) -> int:
        return self.scaler.border(v)

    def _enqueue_toast(self, msg: str) -> None:
        self.ui_queue.put(("toast", msg))

    # =========================================================================
    # WINDOW CONFIGURATION & MASTER SPLIT-PANE STUDIO
    # =========================================================================
    def _configure_window(self) -> None:
        self.root.title("PS5 DualSense Couch Control  //  Obsidian Studio")
        self.root.configure(bg=BG_APP)

        w = self._px(1030)
        h = self._px(680)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(self._px(20), (sw - w) // 2)
        y = max(self._px(20), (sh - h) // 2 - self._px(14))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(self._px(950), self._px(640))
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        try:
            if LOGO_ICO_PATH.exists():
                self.root.iconbitmap(default=str(LOGO_ICO_PATH))
        except Exception:
            pass

        try:
            master_logo = load_master_logo()
            if master_logo is not None:
                from PIL import Image

                self._tk_icons = [
                    tk.PhotoImage(
                        data=self._pil_to_png_bytes(master_logo.resize((sz, sz), Image.Resampling.LANCZOS)),
                        master=self.root,
                    )
                    for sz in (256, 64, 32)
                ]
                self.root.iconphoto(True, *self._tk_icons)
            else:
                self._tk_icon = tk.PhotoImage(
                    data=self._pil_to_png_bytes(create_tray_icon_image()),
                    master=self.root,
                )
                self.root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<Control-f>", self._focus_search)
        self.root.bind("<Escape>", self._on_escape)

    def _build_layout(self) -> None:
        root_split = tk.Frame(self.root, bg=BG_APP)
        root_split.pack(fill="both", expand=True)

        # Left Persistent Telemetry & Workflow Dock
        self.left_dock = tk.Frame(
            root_split,
            bg=BG_DOCK,
            width=self._px(312),
            padx=self._px(14),
            pady=self._px(10),
        )
        self.left_dock.pack(side="left", fill="y")
        self.left_dock.pack_propagate(False)

        # Crisp Structural Vertical Divider
        tk.Frame(root_split, bg=BORDER_CARD, width=self._bd(1)).pack(side="left", fill="y")

        # Right Segmented Precision Inspector
        self.right_pane = tk.Frame(root_split, bg=BG_APP)
        self.right_pane.pack(side="left", fill="both", expand=True)

        self._build_left_dock()
        self._build_right_inspector()
        self._build_cheat_sheet_drawer()

    # =========================================================================
    # LEFT DOCK: BRAND, LIVE CONNECTION, WORKFLOW PRESETS, SCOPES, AUDIO VU
    # =========================================================================
    def _build_left_dock(self) -> None:
        # 1. Brand Header
        hdr = tk.Frame(self.left_dock, bg=BG_DOCK)
        hdr.pack(fill="x", pady=(0, self._px(6)))

        mark_lbl = tk.Label(hdr, image=self.icons.brand_mark(34), bg=BG_DOCK)
        mark_lbl.pack(side="left", padx=(0, self._px(9)))

        brand_txt = tk.Frame(hdr, bg=BG_DOCK)
        brand_txt.pack(side="left", fill="x", expand=True)

        top_t = tk.Frame(brand_txt, bg=BG_DOCK)
        top_t.pack(anchor="w")
        tk.Label(
            top_t,
            text="COUCH CONTROL",
            font=(FONT_UI, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_DOCK,
        ).pack(side="left")
        tk.Label(
            top_t,
            text="PRO",
            font=(FONT_MONO, 8, "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_ACTIVE_PILL,
            padx=self._px(5),
            pady=0,
        ).pack(side="left", padx=(self._px(6), 0))

        tk.Label(
            brand_txt,
            text="OBSIDIAN STUDIO  ·  ANTIGRAVITY + CLAUDE",
            font=(FONT_MONO, 7),
            fg=TEXT_MUTED,
            bg=BG_DOCK,
        ).pack(anchor="w")

        # Live Connection Badge
        self.conn_badge = tk.Frame(
            self.left_dock,
            bg=STATUS_WARN_BG,
            highlightbackground="#523710",
            highlightthickness=self._bd(1),
            padx=self._px(8),
            pady=self._px(3),
        )
        self.conn_badge.pack(fill="x", pady=(0, self._px(6)))

        dot_sz = self._px(10)
        self.conn_dot_canvas = tk.Canvas(
            self.conn_badge,
            width=dot_sz,
            height=dot_sz,
            bg=STATUS_WARN_BG,
            highlightthickness=0,
        )
        self.conn_dot_canvas.pack(side="left", padx=(0, self._px(6)))
        pad_d = self._px(2)
        self._conn_dot_oval = self.conn_dot_canvas.create_oval(
            pad_d, pad_d, dot_sz - pad_d, dot_sz - pad_d, fill=STATUS_WARN, outline=""
        )

        self.conn_lbl = tk.Label(
            self.conn_badge,
            text="SEARCHING FOR DUALSENSE...",
            font=(FONT_MONO, 8, "bold"),
            fg=STATUS_WARN,
            bg=STATUS_WARN_BG,
        )
        self.conn_lbl.pack(side="left")

        self.conn_meta_lbl = tk.Label(
            self.conn_badge,
            text="120Hz",
            font=(FONT_MONO, 8),
            fg=TEXT_SECONDARY,
            bg=STATUS_WARN_BG,
        )
        self.conn_meta_lbl.pack(side="right")

        # 2. Instant Activity Control Presets
        preset_hdr = tk.Frame(self.left_dock, bg=BG_DOCK)
        preset_hdr.pack(fill="x", pady=(0, self._px(3)))
        tk.Label(
            preset_hdr,
            text="ACTIVITY PRESETS  (L2+PS)",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_MUTED,
            bg=BG_DOCK,
        ).pack(side="left")
        self.preset_state_lbl = tk.Label(
            preset_hdr,
            text="1-CLICK SYNC",
            font=(FONT_MONO, 8),
            fg=ACCENT_LIGHT,
            bg=BG_DOCK,
        )
        self.preset_state_lbl.pack(side="right")

        presets_box = tk.Frame(self.left_dock, bg=BG_DOCK)
        presets_box.pack(fill="x", pady=(0, self._px(6)))

        for preset in WORKFLOW_PRESETS:
            pid = preset["id"]
            row = tk.Frame(
                presets_box,
                bg=BG_CARD,
                highlightbackground=BORDER_CARD,
                highlightthickness=self._bd(1),
                cursor="hand2",
            )
            row.pack(fill="x", pady=self._px(1))

            bar = tk.Frame(row, bg=BG_CARD, width=self._px(3))
            bar.pack(side="left", fill="y")

            inner = tk.Frame(row, bg=BG_CARD, padx=self._px(8), pady=self._px(2))
            inner.pack(side="left", fill="both", expand=True)

            line1 = tk.Frame(inner, bg=BG_CARD)
            line1.pack(fill="x")
            title_lbl = tk.Label(
                line1,
                text=preset["name"],
                font=(FONT_UI, 9, "bold"),
                fg=TEXT_PRIMARY,
                bg=BG_CARD,
                anchor="w",
            )
            title_lbl.pack(side="left")

            tag_lbl = tk.Label(
                line1,
                text="",
                font=(FONT_MONO, 7, "bold"),
                fg=ACCENT_LIGHT,
                bg=BG_CARD,
            )
            tag_lbl.pack(side="right")

            spec_lbl = tk.Label(
                inner,
                text=preset["spec"],
                font=(FONT_MONO, 7),
                fg=TEXT_SECONDARY,
                bg=BG_CARD,
                anchor="w",
            )
            spec_lbl.pack(fill="x")

            for w in (row, bar, inner, line1, title_lbl, tag_lbl, spec_lbl):
                w.bind("<Button-1>", lambda _e, p=pid: self.apply_workflow_preset(p))
                w.bind("<Enter>", lambda _e, p=pid: self._hover_preset(p, True))
                w.bind("<Leave>", lambda _e, p=pid: self._hover_preset(p, False))

            self._preset_rows[pid] = {
                "row": row,
                "bar": bar,
                "inner": inner,
                "line1": line1,
                "title": title_lbl,
                "tag": tag_lbl,
                "spec": spec_lbl,
            }

        # 3. Live Vector Telemetry Scope
        tel_hdr = tk.Frame(self.left_dock, bg=BG_DOCK)
        tel_hdr.pack(fill="x", pady=(0, self._px(4)))
        tk.Label(
            tel_hdr,
            text="VECTOR TELEMETRY",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_MUTED,
            bg=BG_DOCK,
        ).pack(side="left")

        self.tel_mode_pill = tk.Label(
            tel_hdr,
            text="LIVE 120HZ",
            font=(FONT_MONO, 7, "bold"),
            fg=STATUS_OK,
            bg=STATUS_OK_BG,
            padx=self._px(6),
            pady=self._px(1),
            cursor="hand2",
        )
        self.tel_mode_pill.pack(side="right")
        self.tel_mode_pill.bind("<Button-1>", self._toggle_demo_telemetry)

        self._scope_w = self._px(282)
        self._scope_h = self._px(142)
        self.scope_canvas = tk.Canvas(
            self.left_dock,
            width=self._scope_w,
            height=self._scope_h,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
        )
        self.scope_canvas.pack(fill="x", pady=(0, self._px(6)))
        self.scope_canvas.bind("<Button-1>", self._on_scope_click)

        # 4. Audio Input Monitor
        aud_hdr = tk.Frame(self.left_dock, bg=BG_DOCK)
        aud_hdr.pack(fill="x", pady=(0, self._px(3)))
        tk.Label(
            aud_hdr,
            text="AUDIO INPUT MONITOR",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_MUTED,
            bg=BG_DOCK,
        ).pack(side="left")

        self.db_readout_lbl = tk.Label(
            aud_hdr,
            text="-60 dB",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_MUTED,
            bg=BG_DOCK,
        )
        self.db_readout_lbl.pack(side="right")

        mic_row = tk.Frame(self.left_dock, bg=BG_DOCK)
        mic_row.pack(fill="x", pady=(0, self._px(5)))

        self.mic_badge_ic = tk.Label(
            mic_row,
            image=self.icons.glyph("mic", size_logical=25, fg=ACCENT_LIGHT, bg=BG_CARD, border=BORDER_CARD),
            bg=BG_DOCK,
        )
        self.mic_badge_ic.pack(side="left", padx=(0, self._px(5)))

        self.ref_mic_btn = tk.Label(
            mic_row,
            image=self.icons.glyph("refresh", size_logical=25, fg=TEXT_SECONDARY, bg=BG_CARD, border=BORDER_CARD),
            bg=BG_DOCK,
            cursor="hand2",
        )
        self.ref_mic_btn.pack(side="right", padx=(self._px(5), 0))
        self.ref_mic_btn.bind("<Button-1>", lambda _e: self._manual_refresh_audio())

        self.mic_select = ProSelect(
            mic_row,
            self.icons,
            self.scaler,
            self._mic_choices,
            initial_key="none",
            on_change=self._on_mic_selected,
            width_logical=216,
            bg_surface=BG_CARD,
        )
        self.mic_select.pack(side="left", fill="x", expand=True)
        self._select_widgets.append(self.mic_select)

        # 24-Segment Peak-Hold LED Meter
        self.vu_canvas = tk.Canvas(
            self.left_dock,
            width=self._px(282),
            height=self._px(15),
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
        )
        self.vu_canvas.pack(fill="x", pady=(0, self._px(8)))

        # Bottom Dock Quick Controls: Pause/Game Mode & Reference Cheat-Sheet
        dock_btns = tk.Frame(self.left_dock, bg=BG_DOCK)
        dock_btns.pack(fill="x", side="bottom")
        dock_btns.columnconfigure(0, weight=1, uniform="dockb")
        dock_btns.columnconfigure(1, weight=1, uniform="dockb")

        self.pause_btn_frame = tk.Frame(
            dock_btns,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
            cursor="hand2",
            pady=self._px(5),
        )
        self.pause_btn_frame.grid(row=0, column=0, sticky="ew", padx=(0, self._px(4)))
        self.pause_btn_ic = tk.Label(
            self.pause_btn_frame,
            image=self.icons.glyph("pause", size_logical=14, fg=TEXT_PRIMARY, bg=None, border=None),
            bg=BG_CARD,
            cursor="hand2",
        )
        self.pause_btn_ic.pack(side="left", padx=(self._px(10), self._px(4)))
        self.pause_btn_lbl = tk.Label(
            self.pause_btn_frame,
            text="Game Mode",
            font=(FONT_UI, 8, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            cursor="hand2",
        )
        self.pause_btn_lbl.pack(side="left")
        for w in (self.pause_btn_frame, self.pause_btn_ic, self.pause_btn_lbl):
            w.bind("<Button-1>", lambda _e: self._toggle_pause_clicked())

        self.guide_btn_frame = tk.Frame(
            dock_btns,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
            cursor="hand2",
            pady=self._px(5),
        )
        self.guide_btn_frame.grid(row=0, column=1, sticky="ew", padx=(self._px(4), 0))
        self.guide_btn_ic = tk.Label(
            self.guide_btn_frame,
            image=self.icons.glyph("grid", size_logical=14, fg=ACCENT_LIGHT, bg=None, border=None),
            bg=BG_CARD,
            cursor="hand2",
        )
        self.guide_btn_ic.pack(side="left", padx=(self._px(10), self._px(4)))
        self.guide_btn_lbl = tk.Label(
            self.guide_btn_frame,
            text="Cheat-Sheet",
            font=(FONT_UI, 8, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            cursor="hand2",
        )
        self.guide_btn_lbl.pack(side="left")
        for w in (self.guide_btn_frame, self.guide_btn_ic, self.guide_btn_lbl):
            w.bind("<Button-1>", lambda _e: self.toggle_cheat_sheet())

    # =========================================================================
    # RIGHT PANE: STICKY HEADER + SEARCHABLE INSPECTOR + STICKY ACTION FOOTER
    # =========================================================================
    def _build_right_inspector(self) -> None:
        # 1. Sticky Top Filter & Search Bar
        self.top_bar = tk.Frame(self.right_pane, bg=BG_APP, padx=self._px(18), pady=self._px(12))
        self.top_bar.pack(fill="x", side="top")

        row_search = tk.Frame(self.top_bar, bg=BG_APP)
        row_search.pack(fill="x", pady=(0, self._px(8)))

        title_stack = tk.Frame(row_search, bg=BG_APP)
        title_stack.pack(side="left")
        tk.Label(
            title_stack,
            text="Precision Inspector",
            font=(FONT_UI, 13, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_APP,
        ).pack(side="left")
        self.match_badge = tk.Label(
            title_stack,
            text="7 CARDS",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            padx=self._px(6),
            pady=self._px(2),
        )
        self.match_badge.pack(side="left", padx=(self._px(8), 0))

        # Live Search Entry Box
        self.search_box = tk.Frame(
            row_search,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
            padx=self._px(8),
            pady=self._px(4),
        )
        self.search_box.pack(side="right")

        tk.Label(
            self.search_box,
            image=self.icons.glyph("search", size_logical=14, fg=TEXT_MUTED, bg=None, border=None),
            bg=BG_CARD,
        ).pack(side="left", padx=(0, self._px(6)))

        self.search_var = tk.StringVar(value="")
        self._search_placeholder_active = True
        self.search_entry = tk.Entry(
            self.search_box,
            textvariable=self.search_var,
            font=(FONT_UI, 9),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            insertbackground=ACCENT_LIGHT,
            relief="flat",
            bd=0,
            width=25,
        )
        self.search_entry.insert(0, "Filter settings... (Ctrl+F)")
        self.search_entry.pack(side="left")

        self.clear_search_lbl = tk.Label(
            self.search_box,
            image=self.icons.glyph("close", size_logical=12, fg=TEXT_MUTED, bg=None, border=None),
            bg=BG_CARD,
            cursor="hand2",
        )
        self.clear_search_lbl.pack(side="left", padx=(self._px(4), 0))
        self.clear_search_lbl.bind("<Button-1>", lambda _e: self.set_search_query(""))

        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        # Category Filter Pills + Quick Target Window Text Zoom Controls
        pill_row = tk.Frame(self.top_bar, bg=BG_APP)
        pill_row.pack(fill="x")

        self._cat_pills: dict[str, tk.Label] = {}
        categories = [
            ("all", "All Settings"),
            ("pointer", "Pointer & Halo"),
            ("bindings", "Controller Bindings"),
            ("system", "Audio & System"),
        ]
        for cid, clabel in categories:
            p = tk.Label(
                pill_row,
                text=clabel,
                font=(FONT_UI, 9, "bold"),
                padx=self._px(11),
                pady=self._px(4),
                cursor="hand2",
                highlightthickness=self._bd(1),
            )
            p.pack(side="left", padx=(0, self._px(6)))
            p.bind("<Button-1>", lambda _e, c=cid: self.set_category_filter(c))
            self._cat_pills[cid] = p
        self._refresh_category_pills()

        # Quick Target App Toolbar (Zoom + Media/Audio controls for active couch window)
        zoom_strip = tk.Frame(pill_row, bg=BG_APP)
        zoom_strip.pack(side="right")
        tk.Label(
            zoom_strip,
            text="QUICK:",
            font=(FONT_MONO, 7, "bold"),
            fg=TEXT_MUTED,
            bg=BG_APP,
        ).pack(side="left", padx=(0, self._px(5)))
        for z_lbl, z_cmd in (
            ("A-", lambda: self._quick_external_zoom("out")),
            ("100%", lambda: self._quick_external_zoom("reset")),
            ("A+", lambda: self._quick_external_zoom("in")),
            ("PLAY", lambda: self._quick_media_action("play_pause")),
            ("VOL-", lambda: self._quick_media_action("volume_down")),
            ("VOL+", lambda: self._quick_media_action("volume_up")),
            ("MUTE", lambda: self._quick_media_action("volume_mute")),
        ):
            zb = tk.Label(
                zoom_strip,
                text=z_lbl,
                font=(FONT_MONO, 8, "bold"),
                fg=TEXT_SECONDARY,
                bg=BG_CARD,
                padx=self._px(7),
                pady=self._px(3),
                cursor="hand2",
                highlightbackground=BORDER_CARD,
                highlightthickness=self._bd(1),
            )
            zb.pack(side="left", padx=(self._px(2), 0))
            zb.bind("<Button-1>", lambda _e, fn=z_cmd: fn())
            zb.bind("<Enter>", lambda _e, w=zb: w.configure(bg=BG_HOVER, fg=TEXT_PRIMARY, highlightbackground=ACCENT))
            zb.bind("<Leave>", lambda _e, w=zb: w.configure(bg=BG_CARD, fg=TEXT_SECONDARY, highlightbackground=BORDER_CARD))

        tk.Frame(self.right_pane, bg=BORDER_CARD, height=self._bd(1)).pack(fill="x", side="top")

        # 2. Sticky Bottom Action Footer
        tk.Frame(self.right_pane, bg=BORDER_CARD, height=self._bd(1)).pack(fill="x", side="bottom")
        self.footer = tk.Frame(self.right_pane, bg=BG_DOCK, padx=self._px(18), pady=self._px(9))
        self.footer.pack(fill="x", side="bottom")

        status_wrap = tk.Frame(self.footer, bg=BG_DOCK)
        status_wrap.pack(side="left", fill="x", expand=True)

        fdot_sz = self._px(8)
        self.footer_dot = tk.Canvas(status_wrap, width=fdot_sz, height=fdot_sz, bg=BG_DOCK, highlightthickness=0)
        self.footer_dot.pack(side="left", padx=(0, self._px(7)))
        self._footer_dot_id = self.footer_dot.create_oval(
            1, 1, fdot_sz - 1, fdot_sz - 1, fill=STATUS_OK, outline=""
        )

        self.status_lbl = tk.Label(
            status_wrap,
            text="AUTO-SAVE ACTIVE  ·  READY",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_SECONDARY,
            bg=BG_DOCK,
            anchor="w",
        )
        self.status_lbl.pack(side="left", fill="x", expand=True)

        def _make_footer_btn(
            text: str,
            cmd: Callable[[], None],
            bg: str = BG_CARD,
            fg: str = TEXT_SECONDARY,
            border: str = BORDER_CARD,
            hover_bg: str = BG_HOVER,
            hover_fg: str = TEXT_PRIMARY,
            hover_border: str = BORDER_HOVER,
        ) -> tk.Label:
            b = tk.Label(
                self.footer,
                text=text,
                font=(FONT_UI, 8, "bold"),
                fg=fg,
                bg=bg,
                padx=self._px(11),
                pady=self._px(5),
                cursor="hand2",
                highlightbackground=border,
                highlightthickness=self._bd(1),
            )
            b.bind("<Button-1>", lambda _e: cmd())
            b.bind(
                "<Enter>",
                lambda _e: b.configure(bg=hover_bg, fg=hover_fg, highlightbackground=hover_border),
            )
            b.bind(
                "<Leave>",
                lambda _e: b.configure(bg=bg, fg=fg, highlightbackground=border),
            )
            return b

        quit_btn = _make_footer_btn(
            "Quit",
            self.quit_app,
            bg=STATUS_DANGER_BG,
            fg="#FDA4AF",
            border=STATUS_DANGER_BORDER,
            hover_bg="#3B1520",
            hover_fg="#FFFFFF",
            hover_border=STATUS_PEAK,
        )
        quit_btn.pack(side="right")

        tray_btn = _make_footer_btn("Hide to Tray", self.hide_to_tray)
        tray_btn.pack(side="right", padx=(0, self._px(6)))

        hud_btn = _make_footer_btn(
            "TV HUD (Options)",
            self.toggle_hud,
            bg=BG_ACTIVE_PILL,
            fg=ACCENT_LIGHT,
            border=ACCENT,
            hover_bg=ACCENT,
            hover_fg="#FFFFFF",
            hover_border=ACCENT_LIGHT,
        )
        hud_btn.pack(side="right", padx=(0, self._px(6)))

        reset_btn = _make_footer_btn("Reset Defaults", self.reset_defaults)
        reset_btn.pack(side="right", padx=(0, self._px(6)))

        feedback_btn = _make_footer_btn(
            "Request Feature (@dabandpuke)",
            lambda: webbrowser.open("https://x.com/dabandpuke"),
            bg=BG_CARD,
            fg=ACCENT_LIGHT,
            border=BORDER_CARD,
            hover_bg=BG_ACTIVE_PILL,
            hover_fg="#FFFFFF",
            hover_border=ACCENT,
        )
        feedback_btn.pack(side="right", padx=(0, self._px(6)))

        # 3. Smooth-Scrolling Inspector Viewport
        self.inspector_body = tk.Frame(self.right_pane, bg=BG_APP)
        self.inspector_body.pack(fill="both", expand=True)

        self.scroll_canvas = tk.Canvas(
            self.inspector_body,
            bg=BG_APP,
            highlightthickness=0,
            bd=0,
            yscrollincrement=self._px(20),
        )
        self.scroll_canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar_canvas = tk.Canvas(
            self.inspector_body,
            width=self._px(8),
            bg=BG_APP,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar_canvas.pack(side="right", fill="y", padx=(0, self._px(2)), pady=self._px(6))
        self.scroll_canvas.configure(yscrollcommand=self._update_custom_scrollbar)
        self.scrollbar_canvas.bind("<Button-1>", self._on_scrollbar_click)
        self.scrollbar_canvas.bind("<B1-Motion>", self._on_scrollbar_click)

        self.cards_container = tk.Frame(self.scroll_canvas, bg=BG_APP, pady=self._px(12))
        self._cards_win_id = self.scroll_canvas.create_window(
            (0, 0), window=self.cards_container, anchor="nw"
        )

        self.scroll_canvas.bind("<Configure>", self._on_scroll_canvas_configure)
        self.cards_container.bind("<Configure>", self._on_cards_container_configure)

        self.empty_card = tk.Frame(
            self.cards_container,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
            padx=self._px(20),
            pady=self._px(26),
        )
        tk.Label(
            self.empty_card,
            text="NO MATCHING SETTINGS",
            font=(FONT_MONO, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack()
        tk.Label(
            self.empty_card,
            text="Try searching for cursor, halo, speed, touchpad, zoom, steam, mic, or lightbar.",
            font=(FONT_UI, 9),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            pady=self._px(4),
        ).pack()
        clr_filter_btn = tk.Label(
            self.empty_card,
            text="Clear Search Filter",
            font=(FONT_UI, 9, "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_ACTIVE_PILL,
            padx=self._px(12),
            pady=self._px(5),
            cursor="hand2",
        )
        clr_filter_btn.pack(pady=(self._px(6), 0))
        clr_filter_btn.bind("<Button-1>", lambda _e: self.set_search_query(""))

        self._build_inspector_cards()
        self._apply_filters()

    # =========================================================================
    # INSPECTOR CARDS (ALL LIVE APPCONFIG FIELDS)
    # =========================================================================
    def _register_card(
        self,
        category: str,
        code: str,
        title: str,
        subtitle: str,
        keywords: str,
        header_right_builder: Callable[[tk.Frame], None] | None = None,
    ) -> tk.Frame:
        card = tk.Frame(
            self.cards_container,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
            padx=self._px(16),
            pady=self._px(13),
        )
        hdr = tk.Frame(card, bg=BG_CARD)
        hdr.pack(fill="x", pady=(0, self._px(8)))

        left_h = tk.Frame(hdr, bg=BG_CARD)
        left_h.pack(side="left", fill="x", expand=True)

        top_line = tk.Frame(left_h, bg=BG_CARD)
        top_line.pack(anchor="w")
        tk.Label(
            top_line,
            text=code,
            font=(FONT_MONO, 8, "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_DOCK,
            padx=self._px(5),
            pady=self._px(1),
        ).pack(side="left", padx=(0, self._px(8)))
        tk.Label(
            top_line,
            text=title,
            font=(FONT_UI, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack(side="left")

        tk.Label(
            left_h,
            text=subtitle,
            font=(FONT_UI, 8),
            fg=TEXT_MUTED,
            bg=BG_CARD,
        ).pack(anchor="w", pady=(self._px(2), 0))

        if header_right_builder is not None:
            right_h = tk.Frame(hdr, bg=BG_CARD)
            right_h.pack(side="right", anchor="n")
            header_right_builder(right_h)

        tk.Frame(card, bg=BORDER_SUBTLE, height=self._bd(1)).pack(fill="x", pady=(0, self._px(8)))

        body = tk.Frame(card, bg=BG_CARD)
        body.pack(fill="x")

        self._cards.append(
            {
                "frame": card,
                "category": category,
                "search_blob": f"{code} {title} {subtitle} {keywords}".lower(),
            }
        )
        return body

    def _add_toggle_row(
        self,
        parent: tk.Frame,
        title: str,
        desc: str,
        initial: bool,
        on_change: Callable[[bool], None],
        pady_logical: tuple[int, int] = (3, 3),
    ) -> ProToggle:
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=(self._px(pady_logical[0]), self._px(pady_logical[1])))
        txt = tk.Frame(row, bg=BG_CARD)
        txt.pack(side="left", fill="x", expand=True, padx=(0, self._px(12)))
        tk.Label(txt, text=title, font=(FONT_UI, 9, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w").pack(fill="x")
        tk.Label(txt, text=desc, font=(FONT_UI, 8), fg=TEXT_MUTED, bg=BG_CARD, anchor="w").pack(fill="x")
        tog = ProToggle(row, self.icons, self.scaler, initial=initial, on_change=on_change, bg=BG_CARD)
        tog.pack(side="right", pady=self._px(4))
        return tog

    def _add_binding_row(
        self,
        parent: tk.Frame,
        glyph_kind: str,
        title: str,
        code: str,
        options: list[tuple[str, str]],
        initial: str,
        field: str,
    ) -> ProSelect:
        row = tk.Frame(parent, bg=BG_CARD, pady=self._px(3))
        row.pack(fill="x")

        ic = tk.Label(
            row,
            image=self.icons.glyph(glyph_kind, size_logical=24, fg=ACCENT_LIGHT, bg=BG_DOCK, border=BORDER_CARD),
            bg=BG_CARD,
        )
        ic.pack(side="left", padx=(0, self._px(9)))

        meta = tk.Frame(row, bg=BG_CARD)
        meta.pack(side="left", fill="x", expand=True)
        tk.Label(meta, text=title, font=(FONT_UI, 9, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w").pack(fill="x")
        tk.Label(meta, text=code, font=(FONT_MONO, 7), fg=TEXT_MUTED, bg=BG_CARD, anchor="w").pack(fill="x")

        sel = ProSelect(
            row,
            self.icons,
            self.scaler,
            options,
            initial_key=initial,
            on_change=lambda val, f=field: self._mutate_config(f, val),
            width_logical=275,
        )
        sel.pack(side="right")
        self._select_widgets.append(sel)
        return sel

    def _build_inspector_cards(self) -> None:
        # ---- CARD 01: CURSOR SCALE & HUD VISIBILITY ----
        b_cur = self._register_card(
            category="pointer",
            code="01 // SCALE",
            title="Cursor Size & Couch Visibility",
            subtitle="Dynamic Windows pointer scaling while active — auto-restores native 32px in Game Mode or exit.",
            keywords="cursor size enlarge visibility 32 64 80 112 160 192 px hud scale tv normal large xl",
        )
        self.tog_enlarge_cursor = self._add_toggle_row(
            b_cur,
            "Enlarge Windows Pointer While Active",
            "Automatically scales system pointer for 6ft-12ft viewing distance.",
            self.config.enlarge_cursor,
            lambda v: self._mutate_config("enlarge_cursor", v),
        )

        sz_row = tk.Frame(b_cur, bg=BG_CARD)
        sz_row.pack(fill="x", pady=(self._px(6), self._px(4)))
        tk.Label(sz_row, text="Cursor Base Size", font=(FONT_UI, 9), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left")
        self.cursor_mult_lbl = tk.Label(
            sz_row,
            text="2.5x SCALE",
            font=(FONT_MONO, 8, "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_DOCK,
            padx=self._px(6),
            pady=self._px(2),
        )
        self.cursor_mult_lbl.pack(side="right", padx=(self._px(8), 0))
        self.seg_cursor_size = SegmentedBar(
            sz_row,
            self.scaler,
            [("32", 32), ("64", 64), ("80", 80), ("112", 112), ("160", 160), ("192 px", 192)],
            initial=self._nearest_cursor_bucket(self.config.couch_cursor_size),
            on_change=lambda v: self._mutate_config("couch_cursor_size", int(v)),
        )
        self.seg_cursor_size.pack(side="right")

        norm_row = tk.Frame(b_cur, bg=BG_CARD)
        norm_row.pack(fill="x", pady=(self._px(4), self._px(4)))
        tk.Label(
            norm_row,
            text="Restore Size (Game Mode / Exit)",
            font=(FONT_UI, 9),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack(side="left")
        self.seg_normal_cursor_size = SegmentedBar(
            norm_row,
            self.scaler,
            [("32 px (1x)", 32), ("48 px (1.5x)", 48), ("64 px (2x)", 64)],
            initial=self._nearest_normal_cursor_bucket(self.config.normal_cursor_size),
            on_change=lambda v: self._mutate_config("normal_cursor_size", int(v)),
        )
        self.seg_normal_cursor_size.pack(side="right")

        hud_row = tk.Frame(b_cur, bg=BG_CARD)
        hud_row.pack(fill="x", pady=(self._px(4), self._px(2)))
        tk.Label(hud_row, text="Overlay & Toast HUD Scale", font=(FONT_UI, 9), fg=TEXT_PRIMARY, bg=BG_CARD).pack(
            side="left"
        )
        self.seg_hud_scale = SegmentedBar(
            hud_row,
            self.scaler,
            [("Normal", "Normal"), ("Large", "Large"), ("XL TV", "XL TV")],
            initial=self.config.hud_scale if self.config.hud_scale in HUD_SCALE_FONTS else "Large",
            on_change=lambda v: self._mutate_config("hud_scale", str(v)),
        )
        self.seg_hud_scale.pack(side="right")

        # ---- CARD 02: SPOTLIGHT HALO RING + INLINE LIVE PREVIEW ----
        b_halo = self._register_card(
            category="pointer",
            code="02 // HALO",
            title="Cursor Spotlight Halo & Live Preview",
            subtitle="Optional click-through concentric ring around pointer for instant tracking on large TVs.",
            keywords="spotlight halo ring glow color playstation blue neon yellow emerald cyan magenta diameter preview",
        )
        halo_split = tk.Frame(b_halo, bg=BG_CARD)
        halo_split.pack(fill="x")

        halo_left = tk.Frame(halo_split, bg=BG_CARD)
        halo_left.pack(side="left", fill="both", expand=True, padx=(0, self._px(14)))

        self.tog_halo = self._add_toggle_row(
            halo_left,
            "Enable Cursor Spotlight Ring",
            "Renders a high-contrast click-through ring locked to pointer coordinates.",
            self.config.cursor_halo_enabled,
            lambda v: self._mutate_config("cursor_halo_enabled", v),
            pady_logical=(0, 6),
        )

        col_row = tk.Frame(halo_left, bg=BG_CARD)
        col_row.pack(fill="x", pady=(self._px(2), self._px(6)))
        tk.Label(col_row, text="Halo Ring Color", font=(FONT_UI, 9), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left")

        self.halo_color_name_lbl = tk.Label(
            col_row,
            text=self.config.cursor_halo_color,
            font=(FONT_MONO, 8),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
        )
        self.halo_color_name_lbl.pack(side="right", padx=(self._px(8), 0))

        halo_sw_wrap = tk.Frame(col_row, bg=BG_CARD)
        halo_sw_wrap.pack(side="right")
        self._halo_swatch_lbls: dict[str, tk.Label] = {}
        for cname in HALO_COLORS:
            sl = tk.Label(halo_sw_wrap, bg=BG_CARD, cursor="hand2")
            sl.pack(side="left", padx=self._px(2))
            sl.bind("<Button-1>", lambda _e, n=cname: self._mutate_config("cursor_halo_color", n))
            self._halo_swatch_lbls[cname] = sl

        self.sld_halo_size = PrecisionSlider(
            halo_left,
            self.scaler,
            label="Halo Ring Diameter",
            min_val=36,
            max_val=104,
            step=4,
            initial=self.config.cursor_halo_size,
            fmt=lambda v: f"{int(round(v))} px",
            on_change=lambda v: self._mutate_config("cursor_halo_size", int(round(v))),
        )
        self.sld_halo_size.pack(fill="x", pady=(self._px(4), 0))

        self._halo_prev_w = self._px(156)
        self._halo_prev_h = self._px(112)
        self.halo_preview_canvas = tk.Canvas(
            halo_split,
            width=self._halo_prev_w,
            height=self._halo_prev_h,
            bg=BG_DOCK,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
        )
        self.halo_preview_canvas.pack(side="right")

        # ---- CARD 03: STICK VELOCITY, PRECISION & DEADZONE ----
        def _build_reset_speeds_btn(parent_hdr: tk.Frame) -> None:
            btn = tk.Label(
                parent_hdr,
                text="Reset Kinematics",
                font=(FONT_MONO, 8, "bold"),
                fg=TEXT_SECONDARY,
                bg=BG_DOCK,
                padx=self._px(8),
                pady=self._px(3),
                cursor="hand2",
                highlightbackground=BORDER_CARD,
                highlightthickness=self._bd(1),
            )
            btn.pack()
            btn.bind("<Button-1>", lambda _e: self._reset_kinematics())
            btn.bind("<Enter>", lambda _e: btn.configure(fg=TEXT_PRIMARY, highlightbackground=ACCENT))
            btn.bind("<Leave>", lambda _e: btn.configure(fg=TEXT_SECONDARY, highlightbackground=BORDER_CARD))

        b_spd = self._register_card(
            category="pointer",
            code="03 // KINEMATICS",
            title="Stick Velocity, Precision Modifiers & Scroll",
            subtitle="Response curve tuning for Left Stick pointer motion, L2/R2 speed clutch, and Right Stick chat scrolling.",
            keywords="cursor speed slow l2 precision fast r2 turbo chat scroll deadzone invert kinematics stick",
            header_right_builder=_build_reset_speeds_btn,
        )

        self.sld_cursor_speed = PrecisionSlider(
            b_spd,
            self.scaler,
            "Base Cursor Speed",
            1.5,
            25.0,
            0.5,
            self.config.cursor_speed,
            fmt=lambda v: f"{v:.1f} px/f",
            on_change=lambda v: self._mutate_config("cursor_speed", v),
        )
        self.sld_cursor_speed.pack(fill="x", pady=self._px(2))

        self.sld_precision = PrecisionSlider(
            b_spd,
            self.scaler,
            "L2 Precision Clutch",
            0.15,
            0.70,
            0.05,
            self.config.precision_multiplier,
            fmt=lambda v: f"{v:.2f}x",
            on_change=lambda v: self._mutate_config("precision_multiplier", v),
        )
        self.sld_precision.pack(fill="x", pady=self._px(2))

        self.sld_turbo = PrecisionSlider(
            b_spd,
            self.scaler,
            "R2 Turbo Multiplier",
            1.30,
            3.50,
            0.10,
            self.config.turbo_multiplier,
            fmt=lambda v: f"{v:.2f}x",
            on_change=lambda v: self._mutate_config("turbo_multiplier", v),
        )
        self.sld_turbo.pack(fill="x", pady=self._px(2))

        self.sld_scroll = PrecisionSlider(
            b_spd,
            self.scaler,
            "Right-Stick Scroll Rate",
            3.0,
            35.0,
            1.0,
            self.config.scroll_speed,
            fmt=lambda v: f"{v:.1f} ln/s",
            on_change=lambda v: self._mutate_config("scroll_speed", v),
        )
        self.sld_scroll.pack(fill="x", pady=self._px(2))

        self.sld_deadzone = PrecisionSlider(
            b_spd,
            self.scaler,
            "Radial Stick Deadzone",
            0.04,
            0.30,
            0.01,
            self.config.deadzone,
            fmt=lambda v: f"{v:.2f} dz",
            on_change=lambda v: self._mutate_config("deadzone", v),
        )
        self.sld_deadzone.pack(fill="x", pady=self._px(2))

        self.vel_summary_lbl = tk.Label(
            b_spd,
            text="",
            font=(FONT_MONO, 8),
            fg=TEXT_MUTED,
            bg=BG_DOCK,
            padx=self._px(8),
            pady=self._px(4),
            anchor="w",
        )
        self.vel_summary_lbl.pack(fill="x", pady=(self._px(6), self._px(4)))

        self.tog_invert_scroll = self._add_toggle_row(
            b_spd,
            "Invert Vertical Chat Scroll",
            "Reverses Right Stick Up/Down scroll direction (natural trackpad style).",
            self.config.invert_scroll,
            lambda v: self._mutate_config("invert_scroll", v),
        )

        # ---- CARD 04: TOUCHPAD SURFACE ----
        b_tp = self._register_card(
            category="pointer",
            code="04 // TOUCHPAD",
            title="DualSense Capacitive Touchpad",
            subtitle="1-finger precision swipe, light tap-to-click, and 2-finger inertial scrolling.",
            keywords="touchpad swipe tap click sensitivity trackpad",
        )
        self.tog_touchpad = self._add_toggle_row(
            b_tp,
            "Enable Touchpad Pointer & Scroll",
            "Use capacitive surface for fine cursor motion and two-finger scroll.",
            self.config.touchpad_enabled,
            lambda v: self._mutate_config("touchpad_enabled", v),
        )
        self.tog_tp_tap = self._add_toggle_row(
            b_tp,
            "Light Tap-to-Click",
            "Single capacitive tap triggers Left Mouse Click without pressing physical button.",
            self.config.touchpad_tap_click,
            lambda v: self._mutate_config("touchpad_tap_click", v),
        )
        self.sld_tp_sens = PrecisionSlider(
            b_tp,
            self.scaler,
            "Touchpad Sensitivity",
            0.20,
            2.00,
            0.05,
            self.config.touchpad_sensitivity,
            fmt=lambda v: f"{v:.2f}x",
            on_change=lambda v: self._mutate_config("touchpad_sensitivity", v),
        )
        self.sld_tp_sens.pack(fill="x", pady=(self._px(6), 0))

        # ---- CARD 05: PROGRAMMABLE CONTROLLER BINDINGS ----
        b_bind = self._register_card(
            category="bindings",
            code="05 // BINDINGS",
            title="Programmable Button Matrix",
            subtitle="Assign productivity shortcuts, voice dictation, window switching, or text zoom to special buttons.",
            keywords="bindings remap buttons touchpad press ps home create share triangle l3 r3 voice typing taskbar keyboard",
        )
        self.sel_touchpad = self._add_binding_row(
            b_bind,
            glyph_kind="touchpad",
            title="Touchpad Center Click",
            code="TP-PRESS",
            options=TOUCHPAD_OPTIONS,
            initial=self.config.touchpad_press_action,
            field="touchpad_press_action",
        )
        self.sel_ps = self._add_binding_row(
            b_bind,
            glyph_kind="ps",
            title="PS Home Button",
            code="PS-HOME",
            options=PS_BUTTON_OPTIONS,
            initial=self.config.ps_button_action,
            field="ps_button_action",
        )
        self.sel_create = self._add_binding_row(
            b_bind,
            glyph_kind="create",
            title="Create / Share Button",
            code="CREATE",
            options=CREATE_OPTIONS,
            initial=self.config.create_button_action,
            field="create_button_action",
        )
        self.sel_triangle = self._add_binding_row(
            b_bind,
            glyph_kind="triangle",
            title="Triangle Face Button",
            code="TRIANGLE",
            options=TRIANGLE_OPTIONS,
            initial=self.config.triangle_button_action,
            field="triangle_button_action",
        )
        self.sel_l3 = self._add_binding_row(
            b_bind,
            glyph_kind="l3",
            title="Left Stick Click",
            code="L3-CLICK",
            options=L3_OPTIONS,
            initial=self.config.l3_button_action,
            field="l3_button_action",
        )
        self.sel_r3 = self._add_binding_row(
            b_bind,
            glyph_kind="r3",
            title="Right Stick Click",
            code="R3-CLICK",
            options=R3_OPTIONS,
            initial=self.config.r3_button_action,
            field="r3_button_action",
        )

        # ---- CARD 06: TEXT ZOOM CHORD & STEAM FOCUS GUARD ----
        b_zoom_steam = self._register_card(
            category="bindings",
            code="06 // CHORDS & STEAM",
            title="Text Zoom Chord & Steam Big Picture Guard",
            subtitle="Instant couch readability scaling and background Steam PS-button interception.",
            keywords="zoom text ctrl plus wheel l2 right stick steam guard big picture ps button",
        )
        self.tog_l2_zoom = self._add_toggle_row(
            b_zoom_steam,
            "Hold L2 + Right Stick Up/Down to Zoom Text",
            "Smoothly scales text in Antigravity, Claude, VS Code, and browsers from the couch.",
            self.config.l2_rstick_zoom,
            lambda v: self._mutate_config("l2_rstick_zoom", v),
        )

        zm_row = tk.Frame(b_zoom_steam, bg=BG_CARD)
        zm_row.pack(fill="x", pady=(self._px(4), self._px(8)))
        tk.Label(zm_row, text="Zoom Synthesis Method", font=(FONT_UI, 9), fg=TEXT_PRIMARY, bg=BG_CARD).pack(
            side="left"
        )
        self.sel_zoom_mode = ProSelect(
            zm_row,
            self.icons,
            self.scaler,
            ZOOM_MODE_OPTIONS,
            initial_key=self.config.zoom_mode,
            on_change=lambda v: self._mutate_config("zoom_mode", v),
            width_logical=275,
        )
        self.sel_zoom_mode.pack(side="right")
        self._select_widgets.append(self.sel_zoom_mode)

        tk.Frame(b_zoom_steam, bg=BORDER_SUBTLE, height=self._bd(1)).pack(
            fill="x", pady=(self._px(2), self._px(6))
        )

        self.tog_block_steam = self._add_toggle_row(
            b_zoom_steam,
            "Steam Guide Button Focus Guard",
            "Prevents pressing the PS Home button from launching Steam Big Picture overlay.",
            self.config.block_steam_ps_button,
            lambda v: self._mutate_config("block_steam_ps_button", v),
        )

        steam_actions = tk.Frame(b_zoom_steam, bg=BG_CARD)
        steam_actions.pack(fill="x", pady=(self._px(6), self._px(2)))
        for btn_txt, fn in (
            ("Open Steam Controller Settings", self._open_steam_controller_settings),
            ("Close Background Steam Now", self._close_background_steam),
        ):
            sb = tk.Label(
                steam_actions,
                text=btn_txt,
                font=(FONT_UI, 8, "bold"),
                fg=TEXT_SECONDARY,
                bg=BG_DOCK,
                padx=self._px(10),
                pady=self._px(5),
                cursor="hand2",
                highlightbackground=BORDER_CARD,
                highlightthickness=self._bd(1),
            )
            sb.pack(side="left", padx=(0, self._px(8)))
            sb.bind("<Button-1>", lambda _e, action=fn: action())
            sb.bind("<Enter>", lambda _e, w=sb: w.configure(fg=TEXT_PRIMARY, highlightbackground=BORDER_HOVER))
            sb.bind("<Leave>", lambda _e, w=sb: w.configure(fg=TEXT_SECONDARY, highlightbackground=BORDER_CARD))

        # ---- CARD 07: AUDIO ROUTING, LIGHTBAR, HAPTICS & SYSTEM ----
        b_sys = self._register_card(
            category="system",
            code="07 // SYSTEM & LED",
            title="Audio Auto-Switch, Lightbar LED & Startup",
            subtitle="USB-C microphone handoff, DualSense lightbar battery/color presets, haptics, and tray lifecycle.",
            keywords="audio usb mic auto switch haptics rumble lightbar led color battery tray startup connect toast",
        )
        self.tog_auto_mic = self._add_toggle_row(
            b_sys,
            "Auto-Select DualSense Mic on USB-C Plug-In",
            "Switches Windows default voice input to controller mic when connected over USB-C.",
            self.config.auto_switch_usb_mic,
            lambda v: self._mutate_config("auto_switch_usb_mic", v),
        )
        self.tog_haptics = self._add_toggle_row(
            b_sys,
            "Tactile Haptic Detents",
            "Subtle DualSense rumble confirmation on profile switch, mic cycle, and mode toggle.",
            self.config.haptics_enabled,
            lambda v: self._mutate_config("haptics_enabled", v),
        )

        lb_row = tk.Frame(b_sys, bg=BG_CARD)
        lb_row.pack(fill="x", pady=(self._px(6), self._px(6)))
        tk.Label(lb_row, text="Lightbar LED Preset", font=(FONT_UI, 9), fg=TEXT_PRIMARY, bg=BG_CARD).pack(
            side="left"
        )

        self.lightbar_name_lbl = tk.Label(
            lb_row,
            text=self.config.lightbar_preset,
            font=(FONT_MONO, 8),
            fg=TEXT_SECONDARY,
            bg=BG_CARD,
        )
        self.lightbar_name_lbl.pack(side="right", padx=(self._px(8), 0))

        lb_sw_wrap = tk.Frame(lb_row, bg=BG_CARD)
        lb_sw_wrap.pack(side="right")
        self._lightbar_swatch_lbls: dict[str, tk.Label] = {}
        for lname in LIGHTBAR_PRESETS:
            sl = tk.Label(lb_sw_wrap, bg=BG_CARD, cursor="hand2")
            sl.pack(side="left", padx=self._px(2))
            sl.bind("<Button-1>", lambda _e, n=lname: self._mutate_config("lightbar_preset", n))
            self._lightbar_swatch_lbls[lname] = sl

        self.tog_connect_hud = self._add_toggle_row(
            b_sys,
            "Show Connection Status Toast",
            "Displays crisp top-center HUD confirmation when DualSense connects or changes mode.",
            self.config.show_hud_on_connect,
            lambda v: self._mutate_config("show_hud_on_connect", v),
        )
        self.tog_start_min = self._add_toggle_row(
            b_sys,
            "Start Minimized in System Tray",
            "Launches silently in background tray without opening studio window.",
            self.config.start_minimized,
            lambda v: self._mutate_config("start_minimized", v),
        )
        self.tog_startup = self._add_toggle_row(
            b_sys,
            "Launch at Windows Sign-In",
            "Registers Couch Control in current-user Windows Run startup key.",
            self.config.run_at_startup,
            lambda v: self._mutate_config("run_at_startup", v),
        )

    # =========================================================================
    # IN-STUDIO CHEAT-SHEET DRAWER (ZERO-EMOJI VECTOR BINDINGS MATRIX)
    # =========================================================================
    def _build_cheat_sheet_drawer(self) -> None:
        self.cheat_drawer = tk.Frame(self.right_pane, bg=BG_APP, padx=self._px(22), pady=self._px(14))

        hdr = tk.Frame(self.cheat_drawer, bg=BG_APP)
        hdr.pack(fill="x", pady=(0, self._px(10)))

        tk.Label(hdr, image=self.icons.brand_mark(34), bg=BG_APP).pack(side="left", padx=(0, self._px(10)))

        left = tk.Frame(hdr, bg=BG_APP)
        left.pack(side="left")
        tk.Label(
            left,
            text="REFERENCE DRAWER // ACTIVE BINDINGS MATRIX",
            font=(FONT_MONO, 8, "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_APP,
        ).pack(anchor="w")
        tk.Label(
            left,
            text="DualSense Couch Reference for Antigravity & Claude",
            font=(FONT_UI, 13, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_APP,
        ).pack(anchor="w")

        close_btn = tk.Label(
            hdr,
            text="Close Drawer  [ESC]",
            font=(FONT_MONO, 8, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            padx=self._px(12),
            pady=self._px(6),
            cursor="hand2",
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
        )
        close_btn.pack(side="right", anchor="n")
        close_btn.bind("<Button-1>", lambda _e: self.toggle_cheat_sheet(False))

        grid = tk.Frame(
            self.cheat_drawer,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=self._bd(1),
            padx=self._px(16),
            pady=self._px(10),
        )
        grid.pack(fill="both", expand=True)

        self._cheat_dynamic_labels: dict[str, tk.Label] = {}
        ref_rows = [
            ("cross", "CROSS  [PRIMARY]", "Left Click / Drag Selection  ·  Activate Highlighted App", None),
            ("square", "SQUARE  [SUBMIT]", "Send Prompt (Enter)  ·  Hold = New Line (Shift + Enter)", None),
            ("circle", "CIRCLE  [CONTEXT]", "Right Mouse Click  ·  Hold = Escape / Dismiss Menu", None),
            ("triangle", "TRIANGLE  [CUSTOM]", "", "triangle_button_action"),
            ("r1", "R1 / L2+R1  [FOCUS HOP]", "Tab / Shift+Tab — Hop Prompt & Code Boxes in Antigravity / Claude", None),
            ("l2", "L2 + R-STICK  [ZOOM]", "Text Zoom In / Out (Ctrl + / Ctrl -)  ·  L2 + D-Pad Left/Right = Copy/Paste", None),
            ("touchpad", "TOUCHPAD  [SURFACE]", "", "touchpad_press_action"),
            ("create", "CREATE  [SYSTEM]", "", "create_button_action"),
            ("ps", "PS HOME  [GUARDED]", "", "ps_button_action"),
            ("r3", "L3 / R3  [STICKS]", "", "sticks_combo"),
        ]

        for idx, (gkind, key_code, desc, dyn_key) in enumerate(ref_rows):
            r = tk.Frame(grid, bg=BG_CARD, pady=self._px(4))
            r.pack(fill="x")
            if idx > 0:
                tk.Frame(grid, bg=BORDER_SUBTLE, height=self._bd(1)).pack(fill="x", before=r)

            tk.Label(
                r,
                image=self.icons.glyph(gkind, size_logical=22, fg=ACCENT_LIGHT, bg=BG_DOCK, border=BORDER_CARD),
                bg=BG_CARD,
            ).pack(side="left", padx=(0, self._px(10)))

            tk.Label(
                r,
                text=key_code,
                font=(FONT_MONO, 8, "bold"),
                fg=TEXT_PRIMARY,
                bg=BG_CARD,
                width=23,
                anchor="w",
            ).pack(side="left")

            dlbl = tk.Label(
                r,
                text=desc,
                font=(FONT_UI, 9),
                fg=TEXT_SECONDARY,
                bg=BG_CARD,
                anchor="w",
            )
            dlbl.pack(side="left", fill="x", expand=True)
            if dyn_key is not None:
                self._cheat_dynamic_labels[dyn_key] = dlbl

    def _refresh_cheat_sheet_labels(self) -> None:
        if "triangle_button_action" in self._cheat_dynamic_labels:
            self._cheat_dynamic_labels["triangle_button_action"].configure(
                text=f"Bound Action: {_lookup_option_label(TRIANGLE_OPTIONS, self.config.triangle_button_action)}"
            )
        if "touchpad_press_action" in self._cheat_dynamic_labels:
            self._cheat_dynamic_labels["touchpad_press_action"].configure(
                text=f"Swipe = Move  ·  Center Click: {_lookup_option_label(TOUCHPAD_OPTIONS, self.config.touchpad_press_action)}"
            )
        if "create_button_action" in self._cheat_dynamic_labels:
            self._cheat_dynamic_labels["create_button_action"].configure(
                text=f"Tap: {_lookup_option_label(CREATE_OPTIONS, self.config.create_button_action)}  ·  Hold = Screenshot  ·  L2+Create = Desktop"
            )
        if "ps_button_action" in self._cheat_dynamic_labels:
            guard = "Steam Guard ON" if self.config.block_steam_ps_button else "Steam Guard OFF"
            self._cheat_dynamic_labels["ps_button_action"].configure(
                text=f"Tap: {_lookup_option_label(PS_BUTTON_OPTIONS, self.config.ps_button_action)}  ·  L2 + PS = Cycle Activity Preset  ({guard})"
            )
        if "sticks_combo" in self._cheat_dynamic_labels:
            self._cheat_dynamic_labels["sticks_combo"].configure(
                text=f"L3: {_lookup_option_label(L3_OPTIONS, self.config.l3_button_action)}  ·  R3: {_lookup_option_label(R3_OPTIONS, self.config.r3_button_action)}  ·  L2+MicBtn = Mute TV"
            )

    def toggle_cheat_sheet(self, force: bool | None = None) -> None:
        target = (not self.cheat_sheet_open) if force is None else bool(force)
        self.cheat_sheet_open = target
        if target:
            self._refresh_cheat_sheet_labels()
            self.inspector_body.pack_forget()
            self.cheat_drawer.pack(fill="both", expand=True)
            self.guide_btn_frame.configure(highlightbackground=ACCENT, bg=BG_ACTIVE_PILL)
            self.guide_btn_lbl.configure(bg=BG_ACTIVE_PILL, fg=ACCENT_LIGHT)
            self.guide_btn_ic.configure(bg=BG_ACTIVE_PILL)
            self._set_status("VIEWING CONTROLLER BINDINGS MATRIX  ·  PRESS ESC TO RETURN", ACCENT_LIGHT)
        else:
            self.cheat_drawer.pack_forget()
            self.inspector_body.pack(fill="both", expand=True)
            self.guide_btn_frame.configure(highlightbackground=BORDER_CARD, bg=BG_CARD)
            self.guide_btn_lbl.configure(bg=BG_CARD, fg=TEXT_PRIMARY)
            self.guide_btn_ic.configure(bg=BG_CARD)
            self._set_status("INSPECTOR ACTIVE  ·  AUTO-SAVE ENABLED", STATUS_OK)

    # =========================================================================
    # OBSIDIAN OVERLAYS: CLICK-THROUGH HALO, TOAST & TV CHEAT-SHEET HUD
    # =========================================================================
    def _build_cursor_halo(self) -> None:
        self.halo_win = tk.Toplevel(self.root)
        self.halo_win.overrideredirect(True)
        self.halo_win.attributes("-topmost", True)
        self.halo_win.configure(bg=TRANSPARENT_KEY)
        try:
            self.halo_win.attributes("-transparentcolor", TRANSPARENT_KEY)
            self.halo_win.attributes("-alpha", 0.86)
        except Exception:
            pass

        init_box = self._px(120)
        self.halo_canvas = tk.Canvas(
            self.halo_win,
            width=init_box,
            height=init_box,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
        )
        self.halo_canvas.pack()
        self._halo_oval = self.halo_canvas.create_oval(
            10, 10, 66, 66, outline=ACCENT, width=self._px(3)
        )
        self.halo_win.withdraw()
        self._halo_shown = False
        _make_overlay_window_style(self.halo_win, click_through=True)
        self._redraw_halo()

    def _redraw_halo(self) -> None:
        if not hasattr(self, "halo_canvas"):
            return
        d = self._px(max(32, min(110, int(self.config.cursor_halo_size))))
        col = HALO_COLORS.get(self.config.cursor_halo_color, ACCENT)
        pad = self._px(6)
        box_sz = d + pad * 2
        self._halo_box_half = box_sz // 2
        self.halo_canvas.configure(width=box_sz, height=box_sz)
        self.halo_canvas.coords(self._halo_oval, pad, pad, pad + d, pad + d)
        self.halo_canvas.itemconfigure(self._halo_oval, outline=col, width=self._px(3))

    def _build_toast_overlay(self) -> None:
        self.toast_win = tk.Toplevel(self.root)
        self.toast_win.overrideredirect(True)
        self.toast_win.attributes("-topmost", True)
        self.toast_win.attributes("-alpha", 0.95)
        self.toast_win.configure(bg=ACCENT)

        b_px = self._bd(1)
        wrap = tk.Frame(self.toast_win, bg=BG_DOCK)
        wrap.pack(padx=b_px, pady=b_px)

        self.toast_bar = tk.Frame(wrap, bg=ACCENT, width=self._px(4))
        self.toast_bar.pack(side="left", fill="y")

        inner = tk.Frame(wrap, bg=BG_DOCK, padx=self._px(18), pady=self._px(10))
        inner.pack(side="left")

        toast_pt, _ = HUD_SCALE_FONTS.get(self.config.hud_scale, (14, 11))
        self.toast_tag_lbl = tk.Label(
            inner,
            text="SYSTEM",
            font=(FONT_MONO, max(8, toast_pt - 4), "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_ACTIVE_PILL,
            padx=self._px(6),
            pady=self._px(2),
        )
        self.toast_tag_lbl.pack(side="left", padx=(0, self._px(10)))

        self.toast_lbl = tk.Label(
            inner,
            text="",
            font=(FONT_UI, toast_pt, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_DOCK,
        )
        self.toast_lbl.pack(side="left")
        self.toast_win.withdraw()
        _make_overlay_window_style(self.toast_win, click_through=True)

    def show_toast(self, message: str, duration_ms: int = 2300) -> None:
        if self._shutting_down or self.smoke_test:
            return
        tag, clean_msg = format_clean_toast(message)
        self.toast_tag_lbl.configure(text=tag)
        self.toast_lbl.configure(text=clean_msg)
        self.toast_win.deiconify()
        self.toast_win.update_idletasks()

        sw = self.root.winfo_screenwidth()
        w = self.toast_win.winfo_reqwidth()
        x = max(self._px(20), (sw - w) // 2)
        self.toast_win.geometry(f"+{x}+{self._px(34)}")
        _make_overlay_window_style(self.toast_win, click_through=True)

        if self._toast_after_id is not None:
            try:
                self.root.after_cancel(self._toast_after_id)
            except Exception:
                pass
        self._toast_after_id = self.root.after(duration_ms, self.toast_win.withdraw)

    def _build_hud_overlay(self) -> None:
        self.hud_win = tk.Toplevel(self.root)
        self.hud_win.overrideredirect(True)
        self.hud_win.attributes("-topmost", True)
        self.hud_win.attributes("-alpha", 0.96)
        self.hud_win.configure(bg=ACCENT)

        b_px = self._bd(1)
        box = tk.Frame(self.hud_win, bg=BG_APP, padx=self._px(24), pady=self._px(18))
        box.pack(padx=b_px, pady=b_px)

        hdr = tk.Frame(box, bg=BG_APP)
        hdr.pack(fill="x", pady=(0, self._px(10)))

        tk.Label(hdr, image=self.icons.brand_mark(36), bg=BG_APP).pack(side="left", padx=(0, self._px(10)))

        title_col = tk.Frame(hdr, bg=BG_APP)
        title_col.pack(side="left")
        tk.Label(
            title_col,
            text="OBSIDIAN COUCH HUD  //  OPTIONS TO DISMISS",
            font=(FONT_MONO, 8, "bold"),
            fg=ACCENT_LIGHT,
            bg=BG_APP,
        ).pack(anchor="w")
        tk.Label(
            title_col,
            text="PS5 DualSense Active Controls",
            font=(FONT_UI, 15, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_APP,
        ).pack(anchor="w")

        self.hud_status_lbl = tk.Label(
            hdr,
            text="ACTIVE",
            font=(FONT_MONO, 10, "bold"),
            fg=STATUS_OK,
            bg=STATUS_OK_BG,
            padx=self._px(10),
            pady=self._px(4),
        )
        self.hud_status_lbl.pack(side="right", padx=(self._px(20), 0))

        tk.Frame(box, bg=BORDER_CARD, height=b_px).pack(fill="x", pady=(0, self._px(8)))

        hud_specs = [
            ("stick", "LEFT STICK / PAD", "Move Pointer  (Hold L2 = Slow Precision  ·  R2 = Fast Turbo)", None),
            ("stick", "RIGHT STICK", "Smooth Scroll Chat & Code  (Up / Down / Left / Right)", None),
            ("touchpad", "TOUCHPAD CLICK", "", "touchpad"),
            ("create", "CREATE BUTTON", "", "create"),
            ("ps", "PS HOME BUTTON", "", "ps"),
            ("dpad", "D-PAD ARROWS", "Navigate Taskbar, Open Programs, Menus & Text Cursor", None),
            ("r1", "R1  (L2 + R1)", "Hop Between Prompt & Content Boxes (Tab / Shift + Tab)", None),
            ("cross", "CROSS", "Left Click / Drag Select  (or Open Highlighted Program)", None),
            ("triangle", "TRIANGLE", "", "triangle"),
            ("square", "SQUARE", "Send Message / Enter  ·  Hold = New Line (Shift + Enter)", None),
            ("circle", "CIRCLE  /  L1", "Right Click (Hold: Esc)   ·   L1: Backspace (L2+L1: Undo)", None),
            ("l2", "L2 + R-STICK / DPAD", "Zoom Text In / Out   ·   L2 + Left/Right: Copy / Paste   ·   L2 + Mic Btn: Mute TV", None),
            ("options", "L2 + OPTIONS", "Toggle Game Mode Bypass (Restores Native 32px Cursor)", None),
        ]

        _, row_pt = HUD_SCALE_FONTS.get(self.config.hud_scale, (14, 11))
        self._hud_row_labels: list[tuple[tk.Label, tk.Label]] = []
        self._hud_dyn_map: dict[str, tk.Label] = {}

        grid = tk.Frame(box, bg=BG_APP)
        grid.pack(fill="x")
        for idx, (gkind, btn_txt, desc_txt, dyn_id) in enumerate(hud_specs):
            ic = tk.Label(
                grid,
                image=self.icons.glyph(gkind, size_logical=20, fg=ACCENT_LIGHT, bg=BG_CARD, border=BORDER_CARD),
                bg=BG_APP,
            )
            ic.grid(row=idx, column=0, sticky="w", pady=self._px(2), padx=(0, self._px(8)))

            l1 = tk.Label(
                grid,
                text=btn_txt,
                font=(FONT_MONO, max(9, row_pt - 1), "bold"),
                fg=ACCENT_LIGHT,
                bg=BG_APP,
                anchor="w",
                padx=self._px(4),
            )
            l1.grid(row=idx, column=1, sticky="w", pady=self._px(2))

            l2 = tk.Label(
                grid,
                text=desc_txt,
                font=(FONT_UI, row_pt),
                fg=TEXT_PRIMARY,
                bg=BG_APP,
                anchor="w",
                padx=self._px(14),
            )
            l2.grid(row=idx, column=2, sticky="w", pady=self._px(2))
            self._hud_row_labels.append((l1, l2))
            if dyn_id:
                self._hud_dyn_map[dyn_id] = l2

        mic_bar = tk.Frame(
            box,
            bg=BG_CARD,
            highlightbackground=BORDER_CARD,
            highlightthickness=b_px,
            padx=self._px(12),
            pady=self._px(8),
        )
        mic_bar.pack(fill="x", pady=(self._px(10), 0))
        self.hud_mic_lbl = tk.Label(
            mic_bar,
            text="ACTIVE MIC // CHECKING...",
            font=(FONT_MONO, 9, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        )
        self.hud_mic_lbl.pack(side="left")

        self._hud_meter_w = self._px(180)
        self._hud_meter_h = self._px(12)
        self.hud_meter = tk.Canvas(
            mic_bar,
            width=self._hud_meter_w,
            height=self._hud_meter_h,
            bg=BG_DOCK,
            highlightthickness=0,
        )
        self.hud_meter.pack(side="right", padx=(self._px(12), 0))

        self._refresh_hud_dynamic_bindings()
        self.hud_win.withdraw()
        _make_overlay_window_style(self.hud_win, click_through=True)

    def _refresh_hud_dynamic_bindings(self) -> None:
        if not hasattr(self, "_hud_dyn_map"):
            return
        if "touchpad" in self._hud_dyn_map:
            self._hud_dyn_map["touchpad"].configure(
                text=_lookup_option_label(TOUCHPAD_OPTIONS, self.config.touchpad_press_action)
            )
        if "create" in self._hud_dyn_map:
            self._hud_dyn_map["create"].configure(
                text=f"{_lookup_option_label(CREATE_OPTIONS, self.config.create_button_action)}  ·  Hold = Screenshot (L2+Create = Desktop)"
            )
        if "ps" in self._hud_dyn_map:
            guard = "Steam Guard ON" if self.config.block_steam_ps_button else "Steam Guard OFF"
            self._hud_dyn_map["ps"].configure(
                text=f"{_lookup_option_label(PS_BUTTON_OPTIONS, self.config.ps_button_action)}  ·  L2 + PS: Cycle Activity Preset  ({guard})"
            )
        if "triangle" in self._hud_dyn_map:
            self._hud_dyn_map["triangle"].configure(
                text=f"{_lookup_option_label(TRIANGLE_OPTIONS, self.config.triangle_button_action)} — Speak into Antigravity / Claude"
            )

    def _apply_hud_font_scale(self) -> None:
        toast_pt, row_pt = HUD_SCALE_FONTS.get(self.config.hud_scale, (14, 11))
        self.toast_tag_lbl.configure(font=(FONT_MONO, max(8, toast_pt - 4), "bold"))
        self.toast_lbl.configure(font=(FONT_UI, toast_pt, "bold"))
        for l1, l2 in self._hud_row_labels:
            l1.configure(font=(FONT_MONO, max(9, row_pt - 1), "bold"))
            l2.configure(font=(FONT_UI, row_pt))

    def toggle_hud(self) -> None:
        if self._hud_visible:
            self._hud_visible = False
            self.hud_win.withdraw()
        else:
            self._refresh_hud_dynamic_bindings()
            self._hud_visible = True
            self.hud_win.deiconify()
            self.hud_win.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = self.hud_win.winfo_reqwidth()
            h = self.hud_win.winfo_reqheight()
            x = max(self._px(20), (sw - w) // 2)
            y = max(self._px(24), (sh - h) // 2)
            self.hud_win.geometry(f"+{x}+{y}")
            _make_overlay_window_style(self.hud_win, click_through=True)

    def toggle_panel(self) -> None:
        if self.root.state() in ("withdrawn", "iconic"):
            self.show_window()
        else:
            self.hide_to_tray()

    # =========================================================================
    # SETTINGS MUTATION, PRESETS & EXTERNAL ACTIONS
    # =========================================================================
    @staticmethod
    def _nearest_cursor_bucket(val: int) -> int:
        buckets = (32, 64, 80, 112, 160, 192)
        return min(buckets, key=lambda b: abs(b - int(val)))

    @staticmethod
    def _nearest_normal_cursor_bucket(val: int) -> int:
        buckets = (32, 48, 64)
        return min(buckets, key=lambda b: abs(b - int(val)))

    def _detect_matching_preset(self) -> str | None:
        is_paused = self.engine.paused
        for p in WORKFLOW_PRESETS:
            if p["paused"] != is_paused:
                continue
            if p["paused"]:
                return p["id"]
            matched = True
            for k, v in p["overrides"].items():
                cur = getattr(self.config, k, None)
                if isinstance(v, float):
                    if abs(float(cur) - v) > 1e-3:
                        matched = False
                        break
                elif cur != v:
                    matched = False
                    break
            if matched:
                return p["id"]
        return None

    def apply_workflow_preset(self, preset_id: str) -> None:
        preset = next((p for p in WORKFLOW_PRESETS if p["id"] == preset_id), None)
        if preset is None:
            return

        want_pause = bool(preset["paused"])
        for k, v in preset["overrides"].items():
            setattr(self.config, k, v)

        if self.engine.paused != want_pause:
            self.engine.set_paused(want_pause, notify=False)

        self.active_preset_id = preset_id
        self._apply_live_side_effects(changed_field="preset")
        self._sync_controls_from_config(preset_id=preset_id, animate_toggles=True)
        self._set_status(
            f"PROFILE ACTIVE: {preset['name'].upper()}  ({preset['spec']})",
            STATUS_WARN if want_pause else STATUS_OK,
        )
        self.show_toast(f"MODE // {preset['name']} ({preset['spec']})")

    def cycle_workflow_preset(self) -> None:
        """Cycle through active couch activity presets (L2 + PS Home Button or bound button)."""
        active_presets = [p for p in WORKFLOW_PRESETS if not p["paused"]]
        if not active_presets:
            return
        cur_id = self.active_preset_id
        idx = next((i for i, p in enumerate(active_presets) if p["id"] == cur_id), -1)
        next_preset = active_presets[(idx + 1) % len(active_presets)]
        self.apply_workflow_preset(next_preset["id"])

    def _mutate_config(self, field: str, value: Any) -> None:
        prev_val = getattr(self.config, field, None)
        if field == "run_at_startup":
            want = bool(value)
            if not self.smoke_test and want != self.config.run_at_startup:
                if StartupManager.set_enabled(want):
                    self.config.run_at_startup = want
            else:
                self.config.run_at_startup = want
        else:
            setattr(self.config, field, value)

        if field == "couch_cursor_size" and int(value) > 32 and not self.config.enlarge_cursor:
            self.config.enlarge_cursor = True
            self.tog_enlarge_cursor.set_value(True, animate=True, notify=False)

        if prev_val != value:
            self._apply_live_side_effects(changed_field=field)

        self.active_preset_id = self._detect_matching_preset()
        self._refresh_preset_pills()
        self._refresh_derived_visuals()
        self._set_status(f"SAVED // {field.upper().replace('_', ' ')} -> {value}", ACCENT_LIGHT)

    def _apply_live_side_effects(self, changed_field: str = "") -> None:
        if not self.smoke_test:
            self.config.save()
            self._sync_cursor_size()
            if changed_field in ("lightbar_preset", "preset", "reset"):
                self.engine.refresh_led_now()
            if changed_field == "auto_switch_usb_mic":
                self._refresh_audio_ui()

        if changed_field in ("hud_scale", "preset", "reset"):
            self._apply_hud_font_scale()
        self._redraw_halo()
        self._refresh_hud_dynamic_bindings()
        if self.cheat_sheet_open:
            self._refresh_cheat_sheet_labels()

    def _reset_kinematics(self) -> None:
        defaults = AppConfig()
        for k in (
            "cursor_speed",
            "precision_multiplier",
            "turbo_multiplier",
            "scroll_speed",
            "deadzone",
            "invert_scroll",
        ):
            setattr(self.config, k, getattr(defaults, k))
        self._apply_live_side_effects(changed_field="kinematics")
        self.active_preset_id = self._detect_matching_preset()
        self._sync_controls_from_config(preset_id=self.active_preset_id, animate_toggles=True)
        self._set_status("KINEMATICS RESET TO CALM COUCH DEFAULTS", STATUS_OK)
        self.show_toast("MODE // Movement speeds reset to calm couch defaults")

    def reset_defaults(self) -> None:
        keep_startup = self.config.run_at_startup
        self.config = AppConfig()
        self.config.run_at_startup = keep_startup
        self.engine.config = self.config
        if self.engine.paused:
            self.engine.set_paused(False, notify=False)
        self._apply_live_side_effects(changed_field="reset")
        self.active_preset_id = self._detect_matching_preset()
        self._sync_controls_from_config(preset_id=self.active_preset_id, animate_toggles=True)
        self._set_status("ALL SETTINGS RESET TO FACTORY DEFAULTS", STATUS_OK)
        self.show_toast("SYSTEM // Restored factory default configuration")

    def _quick_external_zoom(self, direction: str) -> None:
        if self.smoke_test:
            return
        self.ext_tracker.focus_last_external()
        use_wheel = self.config.zoom_mode == "ctrl_wheel"
        if direction == "in":
            self.synth.zoom_in(use_wheel=use_wheel)
            self.show_toast("ZOOM IN // Scaled External Window Text (+)")
        elif direction == "out":
            self.synth.zoom_out(use_wheel=use_wheel)
            self.show_toast("ZOOM OUT // Scaled External Window Text (-)")
        else:
            self.synth.zoom_reset()
            self.show_toast("ZOOM // Reset External Window Text (100%)")

    def _quick_media_action(self, action_key: str) -> None:
        if self.smoke_test:
            return
        self.engine._run_named_action(action_key)

    def _open_steam_controller_settings(self) -> None:
        if self.smoke_test:
            return
        try:
            os.startfile("steam://settings/controller")
            self.show_toast("STEAM // Opening Steam Controller Settings")
        except Exception:
            self.show_toast("NOTICE // Steam installation not detected")

    def _close_background_steam(self) -> None:
        if self.smoke_test:
            return
        try:
            os.startfile("steam://exit")
            self.show_toast("STEAM // Requesting background Steam shutdown")
        except Exception:
            self.show_toast("NOTICE // Steam does not appear to be running")

    def _sync_cursor_size(self) -> None:
        if self.smoke_test:
            return
        self.cursor_mgr.normal_size = max(32, min(128, int(self.config.normal_cursor_size)))
        if self._shutting_down or self.engine.paused or not self.config.enlarge_cursor:
            self.cursor_mgr.restore()
        else:
            self.cursor_mgr.apply_couch_size(self.config.couch_cursor_size)

    def _toggle_pause_clicked(self) -> None:
        self.engine.set_paused(not self.engine.paused, notify=not self.smoke_test)
        self._on_pause_synced()

    def _on_pause_synced(self) -> None:
        self._sync_cursor_size()
        self.active_preset_id = self._detect_matching_preset()
        self._refresh_preset_pills()
        self._refresh_derived_visuals()
        if self.engine.paused:
            self._set_status("SYNTHESIS PAUSED  ·  GAME MODE BYPASS ACTIVE", STATUS_WARN)
        else:
            self._set_status("SYNTHESIS ACTIVE  ·  DESKTOP POINTER ENABLED", STATUS_OK)

    # =========================================================================
    # SYNC CONTROLS & DERIVED VISUALS
    # =========================================================================
    def _sync_controls_from_config(self, preset_id: str | None = None, animate_toggles: bool = False) -> None:
        self.active_preset_id = preset_id
        self.tog_enlarge_cursor.set_value(self.config.enlarge_cursor, animate=animate_toggles)
        self.seg_cursor_size.set_value(self._nearest_cursor_bucket(self.config.couch_cursor_size))
        self.seg_normal_cursor_size.set_value(
            self._nearest_normal_cursor_bucket(self.config.normal_cursor_size)
        )
        self.seg_hud_scale.set_value(
            self.config.hud_scale if self.config.hud_scale in HUD_SCALE_FONTS else "Large"
        )

        self.tog_halo.set_value(self.config.cursor_halo_enabled, animate=animate_toggles)
        self.sld_halo_size.set_value(self.config.cursor_halo_size)

        self.sld_cursor_speed.set_value(self.config.cursor_speed)
        self.sld_precision.set_value(self.config.precision_multiplier)
        self.sld_turbo.set_value(self.config.turbo_multiplier)
        self.sld_scroll.set_value(self.config.scroll_speed)
        self.sld_deadzone.set_value(self.config.deadzone)
        self.tog_invert_scroll.set_value(self.config.invert_scroll, animate=animate_toggles)

        self.tog_touchpad.set_value(self.config.touchpad_enabled, animate=animate_toggles)
        self.tog_tp_tap.set_value(self.config.touchpad_tap_click, animate=animate_toggles)
        self.sld_tp_sens.set_value(self.config.touchpad_sensitivity)

        self.sel_touchpad.set_value(self.config.touchpad_press_action)
        self.sel_ps.set_value(self.config.ps_button_action)
        self.sel_create.set_value(self.config.create_button_action)
        self.sel_triangle.set_value(self.config.triangle_button_action)
        self.sel_l3.set_value(self.config.l3_button_action)
        self.sel_r3.set_value(self.config.r3_button_action)

        self.tog_l2_zoom.set_value(self.config.l2_rstick_zoom, animate=animate_toggles)
        self.sel_zoom_mode.set_value(self.config.zoom_mode)
        self.tog_block_steam.set_value(self.config.block_steam_ps_button, animate=animate_toggles)

        self.tog_auto_mic.set_value(self.config.auto_switch_usb_mic, animate=animate_toggles)
        self.tog_haptics.set_value(self.config.haptics_enabled, animate=animate_toggles)
        self.tog_connect_hud.set_value(self.config.show_hud_on_connect, animate=animate_toggles)
        self.tog_start_min.set_value(self.config.start_minimized, animate=animate_toggles)
        self.tog_startup.set_value(self.config.run_at_startup, animate=animate_toggles)

        self._refresh_preset_pills()
        self._refresh_derived_visuals()
        if self.cheat_sheet_open:
            self._refresh_cheat_sheet_labels()

    def _hover_preset(self, pid: str, entering: bool) -> None:
        if pid == self.active_preset_id:
            return
        info = self._preset_rows.get(pid)
        if not info:
            return
        bg = BG_ELEVATED if entering else BG_CARD
        info["row"].configure(bg=bg, highlightbackground=BORDER_HOVER if entering else BORDER_CARD)
        info["bar"].configure(bg=BORDER_HOVER if entering else BG_CARD)
        for k in ("inner", "line1", "title", "tag", "spec"):
            info[k].configure(bg=bg)

    def _refresh_preset_pills(self) -> None:
        if self.active_preset_id is None:
            self.preset_state_lbl.configure(text="CUSTOM TUNED", fg=STATUS_WARN)
        else:
            self.preset_state_lbl.configure(text="SYNCED", fg=STATUS_OK)

        for pid, info in self._preset_rows.items():
            selected = pid == self.active_preset_id
            bg = BG_ACTIVE_PILL if selected else BG_CARD
            border = ACCENT if selected else BORDER_CARD
            bar_col = ACCENT_LIGHT if selected else BG_CARD

            info["row"].configure(bg=bg, highlightbackground=border)
            info["bar"].configure(bg=bar_col)
            info["inner"].configure(bg=bg)
            info["line1"].configure(bg=bg)
            info["title"].configure(bg=bg, fg=TEXT_PRIMARY if selected else TEXT_SECONDARY)
            info["tag"].configure(bg=bg, text="ACTIVE" if selected else "")
            info["spec"].configure(bg=bg, fg=ACCENT_LIGHT if selected else TEXT_MUTED)

    def _refresh_derived_visuals(self) -> None:
        is_paused = self.engine.paused
        norm_px = max(32, int(self.config.normal_cursor_size))
        eff_px = self.config.couch_cursor_size if (self.config.enlarge_cursor and not is_paused) else norm_px
        mult = eff_px / 32.0
        restore_tag = "NATIVE 1x" if norm_px == 32 else f"RESTORE {mult:.1f}x".replace(".0x", "x")
        self.cursor_mult_lbl.configure(
            text=f"{mult:.1f}x SCALE".replace(".0x", "x")
            if (self.config.enlarge_cursor and not is_paused)
            else restore_tag
        )

        base = self.config.cursor_speed
        slow = base * self.config.precision_multiplier
        fast = base * self.config.turbo_multiplier
        self.vel_summary_lbl.configure(
            text=f"EFFECTIVE ENVELOPE  //  L2 SLOW: {slow:4.1f} px/f   ·   BASE: {base:4.1f} px/f   ·   R2 TURBO: {fast:4.1f} px/f"
        )

        self.halo_color_name_lbl.configure(text=self.config.cursor_halo_color)
        for cname, lbl in self._halo_swatch_lbls.items():
            chex = HALO_COLORS[cname]
            lbl.configure(
                image=self.icons.swatch(chex, selected=(cname == self.config.cursor_halo_color), size_logical=22)
            )

        self.lightbar_name_lbl.configure(text=self.config.lightbar_preset)
        for lname, lbl in self._lightbar_swatch_lbls.items():
            rgb = LIGHTBAR_PRESETS[lname]
            lhex = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            lbl.configure(
                image=self.icons.swatch(lhex, selected=(lname == self.config.lightbar_preset), size_logical=22)
            )

        if is_paused:
            self.pause_btn_frame.configure(bg=STATUS_WARN_BG, highlightbackground=STATUS_WARN)
            self.pause_btn_ic.configure(
                bg=STATUS_WARN_BG,
                image=self.icons.glyph("play", size_logical=14, fg=STATUS_WARN, bg=None, border=None),
            )
            self.pause_btn_lbl.configure(text="Resume", fg=STATUS_WARN, bg=STATUS_WARN_BG)
        else:
            self.pause_btn_frame.configure(bg=BG_CARD, highlightbackground=BORDER_CARD)
            self.pause_btn_ic.configure(
                bg=BG_CARD,
                image=self.icons.glyph("pause", size_logical=14, fg=TEXT_PRIMARY, bg=None, border=None),
            )
            self.pause_btn_lbl.configure(text="Game Mode", fg=TEXT_PRIMARY, bg=BG_CARD)

        self._redraw_halo_preview()
        self._redraw_telemetry_scope()

    def _redraw_halo_preview(self) -> None:
        c = self.halo_preview_canvas
        c.delete("all")
        w, h = self._halo_prev_w, self._halo_prev_h
        cx, cy = w // 2, h // 2 - self._px(4)
        is_paused = self.engine.paused

        step = self._px(20)
        for gx in range(self._px(16), w, step):
            c.create_line(gx, 0, gx, h, fill="#15151C", width=self._bd(1))
        for gy in range(self._px(16), h, step):
            c.create_line(0, gy, w, gy, fill="#15151C", width=self._bd(1))

        halo_col = HALO_COLORS.get(self.config.cursor_halo_color, ACCENT)
        if self.config.cursor_halo_enabled and not is_paused:
            r = self._px(self.config.cursor_halo_size * 0.42)
            g_pad = self._px(3)
            c.create_oval(
                cx - r - g_pad,
                cy - r - g_pad,
                cx + r + g_pad,
                cy + r + g_pad,
                outline="#1E2438",
                width=self._px(3),
            )
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=halo_col, width=self._px(2))

        eff_sz = self.config.couch_cursor_size if (self.config.enlarge_cursor and not is_paused) else 32
        scale = (0.55 + (eff_sz - 32) / 160.0 * 0.85) * self.scaler.scale
        pts = [
            (cx, cy),
            (cx, cy + int(22 * scale)),
            (cx + int(5.5 * scale), cy + int(17 * scale)),
            (cx + int(9.5 * scale), cy + int(25 * scale)),
            (cx + int(13 * scale), cy + int(23.5 * scale)),
            (cx + int(9 * scale), cy + int(15.5 * scale)),
            (cx + int(15.5 * scale), cy + int(15.5 * scale)),
        ]
        flat_pts = [coord for pt in pts for coord in pt]
        c.create_polygon(*flat_pts, fill=TEXT_PRIMARY, outline="#09090B", width=self._bd(1))

        halo_tag = (
            f"RING {self.config.cursor_halo_size}px"
            if (self.config.cursor_halo_enabled and not is_paused)
            else "HALO OFF"
        )
        bar_h = self._px(20)
        c.create_rectangle(0, h - bar_h, w, h, fill="#0B0B0F", outline="")
        c.create_text(
            w // 2,
            h - bar_h // 2,
            text=f"{eff_sz}px  ·  {halo_tag}",
            font=(FONT_MONO, 7, "bold"),
            fill=halo_col if (self.config.cursor_halo_enabled and not is_paused) else TEXT_MUTED,
        )

    def _set_status(self, message: str, color: str = ACCENT_LIGHT) -> None:
        self.status_lbl.configure(text=message, fg=TEXT_PRIMARY)
        self.footer_dot.itemconfigure(self._footer_dot_id, fill=color)

    # =========================================================================
    # LIVE SEARCH & CATEGORY FILTERING + CUSTOM SCROLLBAR
    # =========================================================================
    def _focus_search(self, _event: tk.Event | None = None) -> str:
        if self.cheat_sheet_open:
            self.toggle_cheat_sheet(False)
        self.search_entry.focus_set()
        if not self._search_placeholder_active:
            self.search_entry.selection_range(0, "end")
        return "break"

    def _on_escape(self, _event: tk.Event | None = None) -> None:
        for sel in self._select_widgets:
            sel.close_popover()
        if self._hud_visible:
            self.toggle_hud()
        elif self.cheat_sheet_open:
            self.toggle_cheat_sheet(False)
        elif self.get_search_query():
            self.set_search_query("")
            self.root.focus_set()

    def _on_search_focus_in(self, _event: tk.Event) -> None:
        self.search_box.configure(highlightbackground=ACCENT)
        if self._search_placeholder_active:
            self._search_placeholder_active = False
            self.search_var.set("")
            self.search_entry.configure(fg=TEXT_PRIMARY)

    def _on_search_focus_out(self, _event: tk.Event) -> None:
        self.search_box.configure(highlightbackground=BORDER_CARD)
        if not self.search_var.get().strip():
            self._search_placeholder_active = True
            self.search_var.set("Filter settings... (Ctrl+F)")
            self.search_entry.configure(fg=TEXT_MUTED)

    def _on_search_key(self, _event: tk.Event) -> None:
        if self._search_placeholder_active:
            return
        self._apply_filters()

    def get_search_query(self) -> str:
        if self._search_placeholder_active:
            return ""
        return self.search_var.get().strip()

    def set_search_query(self, query: str) -> None:
        q = query.strip()
        if q:
            self._search_placeholder_active = False
            self.search_var.set(q)
            self.search_entry.configure(fg=TEXT_PRIMARY)
        else:
            if self.root.focus_get() is self.search_entry:
                self._search_placeholder_active = False
                self.search_var.set("")
                self.search_entry.configure(fg=TEXT_PRIMARY)
            else:
                self._search_placeholder_active = True
                self.search_var.set("Filter settings... (Ctrl+F)")
                self.search_entry.configure(fg=TEXT_MUTED)
        if self.cheat_sheet_open:
            self.toggle_cheat_sheet(False)
        self._apply_filters()

    def set_category_filter(self, category: str) -> None:
        self.active_category = category
        if self.cheat_sheet_open:
            self.toggle_cheat_sheet(False)
        self._refresh_category_pills()
        self._apply_filters()

    def _refresh_category_pills(self) -> None:
        for cid, pill in self._cat_pills.items():
            active = cid == self.active_category
            pill.configure(
                bg=BG_ACTIVE_PILL if active else BG_CARD,
                fg=ACCENT_LIGHT if active else TEXT_SECONDARY,
                highlightbackground=ACCENT if active else BORDER_CARD,
            )

    def _apply_filters(self) -> None:
        tokens = [t for t in self.get_search_query().lower().split() if t]
        self.empty_card.pack_forget()
        for item in self._cards:
            item["frame"].pack_forget()

        matched = 0
        for item in self._cards:
            cat_ok = self.active_category == "all" or item["category"] == self.active_category
            search_ok = all(tok in item["search_blob"] for tok in tokens)
            if cat_ok and search_ok:
                item["frame"].pack(fill="x", padx=self._px(18), pady=(0, self._px(10)))
                matched += 1

        if matched == 0:
            self.empty_card.pack(fill="x", padx=self._px(18), pady=self._px(12))

        total = len(self._cards)
        if tokens or self.active_category != "all":
            self.match_badge.configure(
                text=f"{matched} / {total} MATCHED",
                fg=ACCENT_LIGHT if matched > 0 else STATUS_WARN,
            )
        else:
            self.match_badge.configure(text=f"{total} CARDS", fg=TEXT_MUTED)

        self.scroll_canvas.yview_moveto(0.0)
        self.cards_container.update_idletasks()
        self._on_cards_container_configure(None)

    def _on_scroll_canvas_configure(self, event: tk.Event) -> None:
        self.scroll_canvas.itemconfigure(self._cards_win_id, width=event.width)

    def _on_cards_container_configure(self, _event: tk.Event | None) -> None:
        bbox = self.scroll_canvas.bbox("all")
        if bbox:
            self.scroll_canvas.configure(scrollregion=bbox)
        first, last = self.scroll_canvas.yview()
        self._update_custom_scrollbar(first, last)

    def _update_custom_scrollbar(self, first: str | float, last: str | float) -> None:
        f, l = float(first), float(last)
        self.scrollbar_canvas.delete("all")
        h = max(self._px(40), self.scrollbar_canvas.winfo_height())
        if l - f >= 0.995:
            return
        cx = self._px(4)
        w_line = self._px(4)
        y1 = int(f * h)
        y2 = max(y1 + self._px(24), int(l * h))
        self.scrollbar_canvas.create_line(
            cx, self._px(4), cx, h - self._px(4), fill="#13131A", width=w_line, capstyle="round"
        )
        self.scrollbar_canvas.create_line(
            cx, y1 + self._px(2), cx, y2 - self._px(2), fill="#323242", width=w_line, capstyle="round"
        )

    def _on_scrollbar_click(self, event: tk.Event) -> None:
        h = max(1, self.scrollbar_canvas.winfo_height())
        frac = max(0.0, min(1.0, event.y / h))
        self.scroll_canvas.yview_moveto(frac)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self.cheat_sheet_open:
            return
        try:
            rx = self.right_pane.winfo_rootx()
            if event.x_root < rx:
                return
        except Exception:
            pass
        first, last = self.scroll_canvas.yview()
        if last - first >= 0.995:
            return
        steps = -int(event.delta / 40) if event.delta else 0
        if steps != 0:
            self.scroll_canvas.yview_scroll(steps, "units")

    # =========================================================================
    # AUDIO ROUTING & REAL-TIME TELEMETRY LOOP
    # =========================================================================
    def _manual_refresh_audio(self) -> None:
        self._refresh_audio_ui()
        self._set_status("AUDIO ENDPOINTS REFRESHED", ACCENT_LIGHT)

    def _refresh_audio_ui(self) -> None:
        mics: list[MicInfo] = self.audio.refresh_devices(
            auto_switch_usb=self.config.auto_switch_usb_mic
        )
        choices: list[tuple[str, str]] = []
        selected_id = "none"
        for m in mics:
            tag = " [USB-C]" if m.is_dualsense else ""
            choices.append((f"{m.name}{tag}", m.id))
            if m.is_default:
                selected_id = m.id

        if not choices:
            choices = [("No Active Microphone Detected", "none")]
            selected_id = "none"
        elif selected_id == "none":
            selected_id = choices[0][1]

        self._mic_choices = choices
        self.mic_select.set_options(choices, selected_key=selected_id)

        if self.audio.dualsense_usb_mic_available:
            self.mic_badge_ic.configure(
                image=self.icons.glyph("mic", size_logical=25, fg=STATUS_OK, bg=STATUS_OK_BG, border="#174636")
            )
        else:
            self.mic_badge_ic.configure(
                image=self.icons.glyph("mic", size_logical=25, fg=ACCENT_LIGHT, bg=BG_CARD, border=BORDER_CARD)
            )

        def_name = self.audio.default_mic.name if self.audio.default_mic else "None"
        usb_tag = " [USB-C]" if (self.audio.default_mic and self.audio.default_mic.is_dualsense) else ""
        self.hud_mic_lbl.configure(text=f"ACTIVE MIC // {def_name}{usb_tag}")

    def _on_mic_selected(self, dev_id: str) -> None:
        if dev_id and dev_id != "none" and not self.smoke_test:
            self.audio.set_default_microphone(dev_id, notify=True)
            self._refresh_audio_ui()

    def _toggle_demo_telemetry(self, _event: tk.Event | None = None) -> None:
        self.demo_telemetry = not self.demo_telemetry
        if self.demo_telemetry:
            self.tel_mode_pill.configure(text="SIM: DEMO", fg=ACCENT_LIGHT, bg=BG_ACTIVE_PILL)
            self._set_status("TELEMETRY PREVIEW SIMULATION ACTIVE", ACCENT_LIGHT)
        else:
            self.tel_mode_pill.configure(text="LIVE 120HZ", fg=STATUS_OK, bg=STATUS_OK_BG)
            self._set_status("LIVE HARDWARE TELEMETRY ACTIVE", STATUS_OK)
        self._redraw_telemetry_scope()

    def _on_scope_click(self, event: tk.Event) -> None:
        if self._px(112) <= event.y <= self._px(142):
            idx = int((event.x - self._px(14)) // max(1, self._px(64)))
            btns = ("cross", "circle", "square", "triangle")
            if 0 <= idx < len(btns):
                self._pulse_btn = btns[idx]
                self._pulse_ticks = 8
                self._redraw_telemetry_scope()

    def _ui_audio_device_tick(self) -> None:
        if self._shutting_down:
            return
        self._refresh_audio_ui()
        self.root.after(2200, self._ui_audio_device_tick)

    def _ui_fast_tick(self) -> None:
        if self._shutting_down:
            return

        self.ext_tracker.sample()

        if self.instance_guard and self.instance_guard.check_show_requested():
            self.instance_guard.ack_show_requested()
            self.show_window()
            self.show_toast("SYSTEM // Couch Control Studio Focused")

        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "toast":
                self.show_toast(str(payload))
            elif kind == "toggle_hud":
                self.toggle_hud()
            elif kind == "toggle_panel":
                self.toggle_panel()
            elif kind == "cycle_mic":
                self.audio.cycle_microphone()
                self._refresh_audio_ui()
            elif kind == "cycle_preset":
                self.cycle_workflow_preset()
            elif kind == "apply_preset":
                self.apply_workflow_preset(str(payload))
            elif kind == "sync_pause":
                self._on_pause_synced()
            elif kind == "show_window":
                self.show_window()
            elif kind == "quit":
                self.quit_app()
                return

        self.step_telemetry_and_overlays()
        self.root.after(33, self._ui_fast_tick)

    def step_telemetry_and_overlays(self) -> None:
        """Single UI refresh frame for live controller telemetry, VU meter, and cursor halo."""
        self._tick_count += 1
        if self._pulse_ticks > 0:
            self._pulse_ticks -= 1
            if self._pulse_ticks == 0:
                self._pulse_btn = None

        tel = self.engine.telemetry
        conn_label = "USB-C" if self.audio.dualsense_usb_mic_available else "BLUETOOTH"

        # Auto-disengage demo simulation the moment real DualSense motion arrives
        if self.demo_telemetry and tel.connected and (
            abs(tel.lx) > 0.08 or abs(tel.ly) > 0.08 or tel.l2 > 0.1 or tel.r2 > 0.1 or bool(tel.active_buttons)
        ):
            self.demo_telemetry = False
            self.tel_mode_pill.configure(text="LIVE 120HZ", fg=STATUS_OK, bg=STATUS_OK_BG)

        # Connection Status Badge & HUD Header
        if not tel.connected:
            self.conn_badge.configure(bg=STATUS_WARN_BG, highlightbackground="#523710")
            self.conn_dot_canvas.configure(bg=STATUS_WARN_BG)
            self.conn_dot_canvas.itemconfigure(self._conn_dot_oval, fill=STATUS_WARN)
            self.conn_lbl.configure(text="SEARCHING FOR DUALSENSE...", fg=STATUS_WARN, bg=STATUS_WARN_BG)
            self.conn_meta_lbl.configure(text="PRESS PS", fg=TEXT_SECONDARY, bg=STATUS_WARN_BG)
            self.hud_status_lbl.configure(text="DISCONNECTED", fg=STATUS_WARN, bg=STATUS_WARN_BG)
        elif tel.paused_game_mode:
            self.conn_badge.configure(bg=STATUS_WARN_BG, highlightbackground="#523710")
            self.conn_dot_canvas.configure(bg=STATUS_WARN_BG)
            self.conn_dot_canvas.itemconfigure(self._conn_dot_oval, fill=STATUS_WARN)
            self.conn_lbl.configure(text=f"BYPASS · {conn_label} · PAUSED", fg=STATUS_WARN, bg=STATUS_WARN_BG)
            self.conn_meta_lbl.configure(text="GAME", fg=STATUS_WARN, bg=STATUS_WARN_BG)
            self.hud_status_lbl.configure(text=f"PAUSED · {conn_label}", fg=STATUS_WARN, bg=STATUS_WARN_BG)
        else:
            if tel.precision_active:
                meta_txt, meta_col = "L2 SLOW", ACCENT_LIGHT
            elif tel.turbo_active:
                meta_txt, meta_col = "R2 TURBO", STATUS_OK
            elif tel.power_level not in ("unknown", ""):
                meta_txt, meta_col = f"BAT:{tel.power_level[:4].upper()}", TEXT_SECONDARY
            else:
                meta_txt, meta_col = "120HZ", TEXT_SECONDARY

            self.conn_badge.configure(bg=STATUS_OK_BG, highlightbackground="#174636")
            self.conn_dot_canvas.configure(bg=STATUS_OK_BG)
            self.conn_dot_canvas.itemconfigure(self._conn_dot_oval, fill=STATUS_OK)
            self.conn_lbl.configure(text=f"DUALSENSE · {conn_label} · ACTIVE", fg=STATUS_OK, bg=STATUS_OK_BG)
            self.conn_meta_lbl.configure(text=meta_txt, fg=meta_col, bg=STATUS_OK_BG)
            self.hud_status_lbl.configure(text=f"ACTIVE · {conn_label}", fg=STATUS_OK, bg=STATUS_OK_BG)

        if tel.last_action != self._last_engine_action:
            self._last_engine_action = tel.last_action
            tag, clean_act = format_clean_toast(tel.last_action)
            self._set_status(f"{tag} // {clean_act}", STATUS_OK)

        # Only redraw main window canvases if window is mapped (saves CPU while minimized to tray)
        is_visible = self.smoke_test or (self.root.state() not in ("withdrawn", "iconic"))
        if is_visible:
            self._redraw_telemetry_scope()

        # Live Microphone VU Meter
        if self.demo_telemetry and not tel.paused_game_mode:
            t = self._tick_count * 0.14
            raw_peak = max(0.05, min(0.95, 0.42 + 0.30 * math.sin(t * 1.1) + 0.18 * math.sin(t * 2.9 + 0.7)))
        else:
            raw_peak = self.audio.get_peak_level() if not self.smoke_test else 0.0
        vis_level = min(1.0, raw_peak ** 0.62) if raw_peak > 0.0 else 0.0

        if is_visible:
            self._redraw_vu_meter(vis_level)

        if self._hud_visible:
            self._redraw_hud_vu(vis_level)

        # Click-Through Cursor Spotlight Halo
        should_show_halo = (
            not self.smoke_test and self.config.cursor_halo_enabled and not tel.paused_game_mode
        )
        if should_show_halo:
            cx, cy = get_cursor_pos()
            offset = getattr(self, "_halo_box_half", self._px(34))
            if not self._halo_shown:
                self._halo_shown = True
                self.halo_win.deiconify()
                _make_overlay_window_style(self.halo_win, click_through=True)
            self.halo_win.geometry(f"+{cx - offset}+{cy - offset}")
        elif self._halo_shown:
            self._halo_shown = False
            self.halo_win.withdraw()

        # System Tray State Icon
        cur_tray_state = (tel.paused_game_mode, tel.connected)
        if cur_tray_state != self._last_tray_state and hasattr(self, "tray_icon"):
            self._last_tray_state = cur_tray_state
            try:
                self.tray_icon.icon = create_tray_icon_image(
                    paused=tel.paused_game_mode, connected=tel.connected
                )
            except Exception:
                pass

    def _redraw_telemetry_scope(self) -> None:
        c = self.scope_canvas
        c.delete("all")
        w = max(self._scope_w, c.winfo_width())
        tel = self.engine.telemetry

        if self.demo_telemetry:
            t = self._tick_count * 0.075
            lx = 0.68 * math.cos(t) * (0.75 + 0.25 * math.sin(t * 0.4))
            ly = 0.62 * math.sin(t * 1.35)
            rx = 0.22 * math.sin(t * 0.7)
            ry = 0.58 * math.sin(t * 0.95 + 1.1)
            l2 = max(0.0, min(1.0, 0.5 + 0.48 * math.sin(t * 0.55 - 0.8)))
            r2 = max(0.0, min(1.0, 0.45 + 0.50 * math.cos(t * 0.42 + 0.5)))
            phase = (self._tick_count // 22) % 6
            demo_btn = ("cross", "triangle", "square", "circle", None, None)[phase]
            lit_set = {demo_btn} if demo_btn else set()
        else:
            lx, ly, rx, ry, l2, r2 = tel.lx, tel.ly, tel.rx, tel.ry, tel.l2, tel.r2
            lit_set = set()
            for b in tel.active_buttons:
                low = b.lower()
                if "cross" in low:
                    lit_set.add("cross")
                elif "circle" in low:
                    lit_set.add("circle")
                elif "square" in low:
                    lit_set.add("square")
                elif "triangle" in low:
                    lit_set.add("triangle")
            if not self.demo_telemetry:
                other_btns = [
                    b
                    for b in tel.active_buttons
                    if not any(f in b.lower() for f in ("cross", "circle", "square", "triangle"))
                ]
                if other_btns:
                    self.tel_mode_pill.configure(
                        text=" + ".join(other_btns[:2]).upper(),
                        fg=ACCENT_LIGHT,
                        bg=BG_ACTIVE_PILL,
                    )
                else:
                    self.tel_mode_pill.configure(text="LIVE 120HZ", fg=STATUS_OK, bg=STATUS_OK_BG)

        if self._pulse_btn:
            lit_set.add(self._pulse_btn)

        dz = self.config.deadzone
        rad = self._px(28)
        cy = self._px(38)
        scopes = [
            (int(w * 0.26), cy, lx, ly, "L-STICK", ACCENT_LIGHT),
            (int(w * 0.74), cy, rx, ry, "R-STICK", STATUS_OK),
        ]
        for cx, sy_c, sx, sy, label, dot_col in scopes:
            c.create_oval(
                cx - rad, sy_c - rad, cx + rad, sy_c + rad, fill=BG_DOCK, outline="#282834", width=self._bd(1)
            )
            p3 = self._px(3)
            c.create_line(cx - rad + p3, sy_c, cx + rad - p3, sy_c, fill="#1B1B24", width=self._bd(1))
            c.create_line(cx, sy_c - rad + p3, cx, sy_c + rad - p3, fill="#1B1B24", width=self._bd(1))

            dz_r = max(self._px(3), int(round(dz * rad)))
            c.create_oval(
                cx - dz_r,
                sy_c - dz_r,
                cx + dz_r,
                sy_c + dz_r,
                outline="#38384A",
                dash=(self._px(2), self._px(2)),
                width=self._bd(1),
            )

            px_dot = cx + sx * (rad - self._px(5))
            py_dot = sy_c + sy * (rad - self._px(5))
            v_col = TEXT_MUTED if math.hypot(sx, sy) < dz else dot_col
            c.create_line(cx, sy_c, px_dot, py_dot, fill=v_col, width=self._px(2))
            dr = self._px(3.5)
            c.create_oval(
                px_dot - dr, py_dot - dr, px_dot + dr, py_dot + dr, fill=v_col, outline=BG_DOCK, width=self._bd(1)
            )
            c.create_text(
                cx,
                sy_c + rad + self._px(9),
                text=f"{label} {sx:+.2f},{sy:+.2f}",
                font=(FONT_MONO, 7),
                fill=TEXT_SECONDARY,
            )

        # L2 / R2 Linear Analog Trigger Meters
        trig_y = self._px(94)
        half = w // 2
        triggers = [
            (self._px(12), half - self._px(6), "L2", l2, ACCENT),
            (half + self._px(6), w - self._px(12), "R2", r2, STATUS_OK),
        ]
        bh = self._px(4)
        for x1, x2, name, val, col in triggers:
            c.create_text(x1, trig_y, text=name, font=(FONT_MONO, 7, "bold"), fill=TEXT_MUTED, anchor="w")
            bx1 = x1 + self._px(20)
            bx2 = x2 - self._px(30)
            c.create_rectangle(bx1, trig_y - bh, bx2, trig_y + bh, fill=BG_DOCK, outline="#252530")
            fw = int(round((bx2 - bx1) * max(0.0, min(1.0, val))))
            if fw > 1:
                c.create_rectangle(bx1, trig_y - bh, bx1 + fw, trig_y + bh, fill=col, outline="")
            c.create_text(
                x2, trig_y, text=f"{int(val * 100):3d}%", font=(FONT_MONO, 7), fill=TEXT_SECONDARY, anchor="e"
            )

        c.create_line(self._px(12), self._px(107), w - self._px(12), self._px(107), fill=BORDER_SUBTLE)

        # Pure Geometric Face-Button Indicators
        face_specs = [
            ("cross", "CROS", 0.145, ACCENT_LIGHT),
            ("circle", "CIRC", 0.382, "#F43F5E"),
            ("square", "SQUA", 0.618, "#A855F7"),
            ("triangle", "TRIA", 0.855, STATUS_OK),
        ]
        by = self._px(125)
        pw_half = self._px(28)
        ph_half = self._px(11)
        lw_g = self._px(2)
        rg = self._px(4.2)
        for kind, short_lbl, x_frac, active_col in face_specs:
            bx = int(w * x_frac)
            lit = kind in lit_set
            pill_fill = BG_ACTIVE_PILL if lit else BG_DOCK
            pill_out = active_col if lit else "#252530"
            fg = active_col if lit else TEXT_MUTED

            c.create_rectangle(
                bx - pw_half, by - ph_half, bx + pw_half, by + ph_half, fill=pill_fill, outline=pill_out, width=self._bd(1)
            )
            gx = bx - self._px(15)
            if kind == "cross":
                c.create_line(gx - rg, by - rg, gx + rg, by + rg, fill=fg, width=lw_g)
                c.create_line(gx - rg, by + rg, gx + rg, by - rg, fill=fg, width=lw_g)
            elif kind == "circle":
                c.create_oval(gx - rg, by - rg, gx + rg, by + rg, outline=fg, width=lw_g)
            elif kind == "square":
                c.create_rectangle(gx - rg, by - rg, gx + rg, by + rg, outline=fg, width=lw_g)
            elif kind == "triangle":
                c.create_polygon(gx, by - rg, gx + rg, by + rg, gx - rg, by + rg, outline=fg, fill="", width=lw_g)

            c.create_text(
                bx + self._px(8),
                by,
                text=short_lbl,
                font=(FONT_MONO, 7, "bold"),
                fill=TEXT_PRIMARY if lit else TEXT_MUTED,
            )

    def _redraw_vu_meter(self, level: float) -> None:
        c = self.vu_canvas
        c.delete("all")
        w = max(self._px(200), c.winfo_width())
        h = self._px(15)
        segs = 24
        pad_x = self._px(4)
        gap = self._px(2)
        seg_w = max(2.0, (w - 2 * pad_x - (segs - 1) * gap) / segs)

        lit_count = int(round(max(0.0, min(1.0, level)) * segs))
        if lit_count >= self._peak_hold_seg:
            self._peak_hold_seg = lit_count
            self._peak_decay = 10
        else:
            if self._peak_decay > 0:
                self._peak_decay -= 1
            elif self._peak_hold_seg > 0:
                self._peak_hold_seg -= 1

        pad_y = self._px(3)
        for i in range(segs):
            x1 = pad_x + i * (seg_w + gap)
            x2 = x1 + seg_w
            on_col = STATUS_OK if i < 16 else (STATUS_WARN if i < 21 else STATUS_PEAK)
            is_lit = i < lit_count
            is_peak = (i == self._peak_hold_seg - 1) and self._peak_hold_seg > 0
            fill = on_col if (is_lit or is_peak) else "#1D1D26"
            c.create_rectangle(x1, pad_y, x2, h - pad_y, fill=fill, outline="")

        if level <= 0.03:
            db = -60
        else:
            db = max(-60, min(0, int(round(20.0 * math.log10(level)))))
        col = STATUS_PEAK if db > -4 else (STATUS_WARN if db > -10 else (STATUS_OK if db > -45 else TEXT_MUTED))
        self.db_readout_lbl.configure(text=f"{db:3d} dB", fg=col)

    def _redraw_hud_vu(self, level: float) -> None:
        c = self.hud_meter
        c.delete("all")
        segs = 18
        pad = self._px(2)
        gap = self._px(2)
        seg_w = max(2.0, (self._hud_meter_w - 2 * pad - (segs - 1) * gap) / segs)
        lit_count = int(round(max(0.0, min(1.0, level)) * segs))
        for i in range(segs):
            x1 = pad + i * (seg_w + gap)
            col = STATUS_OK if i < 12 else (STATUS_WARN if i < 16 else STATUS_PEAK)
            c.create_rectangle(
                x1, pad, x1 + seg_w, self._hud_meter_h - pad, fill=col if i < lit_count else "#1D1D26", outline=""
            )

    # =========================================================================
    # SYSTEM TRAY & LIFECYCLE
    # =========================================================================
    def _start_tray(self) -> None:
        def _make_preset_tray_action(pid: str):
            return lambda _icon, _item: self.ui_queue.put(("apply_preset", pid))

        preset_submenu = pystray.Menu(
            pystray.MenuItem(
                "Cycle Activity Preset (L2 + PS)",
                lambda _icon, _item: self.ui_queue.put(("cycle_preset", None)),
            ),
            pystray.Menu.SEPARATOR,
            *[
                pystray.MenuItem(
                    preset["name"],
                    _make_preset_tray_action(preset["id"]),
                )
                for preset in WORKFLOW_PRESETS
            ],
        )
        menu = pystray.Menu(
            pystray.MenuItem(
                "Open Obsidian Studio",
                lambda _icon, _item: self.ui_queue.put(("show_window", None)),
                default=True,
            ),
            pystray.MenuItem(
                "Activity Control Presets",
                preset_submenu,
            ),
            pystray.MenuItem(
                "Toggle TV Couch HUD (Options)",
                lambda _icon, _item: self.ui_queue.put(("toggle_hud", None)),
            ),
            pystray.MenuItem(
                "Pause / Resume (Game Mode)",
                lambda _icon, _item: self.engine.set_paused(not self.engine.paused, notify=True),
            ),
            pystray.MenuItem(
                "Cycle Microphone",
                lambda _icon, _item: self.ui_queue.put(("cycle_mic", None)),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Media Play / Pause",
                lambda _icon, _item: self.synth.media_play_pause(),
            ),
            pystray.MenuItem(
                "Mute / Unmute TV Audio",
                lambda _icon, _item: self.synth.volume_mute(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Quit Couch Control",
                lambda _icon, _item: self.ui_queue.put(("quit", None)),
            ),
        )
        self.tray_icon = pystray.Icon(
            "dualsense_couch_control",
            create_tray_icon_image(),
            "PS5 DualSense Couch Control",
            menu,
        )

        def _run_tray() -> None:
            def _on_setup(icon: pystray.Icon) -> None:
                icon.visible = True
                self._tray_ready = True

            try:
                self.tray_icon.run(setup=_on_setup)
            except Exception:
                self._tray_ready = False

        threading.Thread(target=_run_tray, name="SystemTrayThread", daemon=True).start()

    def show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.update_idletasks()
            wid = self.root.winfo_id()
            hwnd = user32.GetParent(wid) or wid
            if hwnd:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(220, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    def hide_to_tray(self) -> None:
        for sel in self._select_widgets:
            sel.close_popover()
        if not self._tray_ready:
            self.root.iconify()
            return
        self.root.withdraw()
        if not self._tray_notified_once:
            self._tray_notified_once = True
            self.show_toast("TRAY // Minimized to System Tray — Press PS Button to Reopen")

    def quit_app(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        for sel in self._select_widgets:
            sel.close_popover()
        if not self.smoke_test:
            try:
                self.cursor_mgr.restore()
            except Exception:
                pass
            try:
                self.config.save()
            except Exception:
                pass
            try:
                if self.instance_guard:
                    self.instance_guard.release()
            except Exception:
                pass
            try:
                self.engine.stop()
            except Exception:
                pass
            try:
                if hasattr(self, "tray_icon"):
                    self.tray_icon.stop()
            except Exception:
                pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        if not self.smoke_test and os.environ.get("COUCH_CONTROL_SMOKE_TEST") != "1":
            def _hard_exit() -> None:
                import time as _t

                _t.sleep(0.15)
                os._exit(0)

            threading.Thread(target=_hard_exit, daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()


def _run_self_test() -> int:
    os.environ["COUCH_CONTROL_SMOKE_TEST"] = "1"
    before_bytes = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None

    app = CouchControlApp(instance_guard=None, smoke_test=True)
    app._start_tray()
    if hasattr(app, "tray_icon"):
        app.tray_icon.stop()
    app.root.update_idletasks()

    # Verify DPI-scaled Left Dock geometry fits inside main window height with zero clipping
    win_h = app._px(680)
    dock_req_h = app.left_dock.winfo_reqheight()
    assert dock_req_h <= win_h, f"Left dock clipped: {dock_req_h} > {win_h}"

    # Verify Workflow Presets
    for p in WORKFLOW_PRESETS:
        app.apply_workflow_preset(p["id"])
        app.root.update_idletasks()
        assert app.active_preset_id == p["id"], f"Preset failed: {p['id']}"
    app.apply_workflow_preset("ai_workspace")
    app.cycle_workflow_preset()
    assert app.active_preset_id == "living_room_tv"
    app.cycle_workflow_preset()
    assert app.active_preset_id == "media_cinema"
    app.apply_workflow_preset("ai_workspace")

    # Verify Search & Category Filters
    app.set_search_query("halo")
    app.root.update_idletasks()
    vis_halo = sum(1 for c in app._cards if str(c["frame"].winfo_manager()) == "pack")
    assert 1 <= vis_halo < len(app._cards), f"Unexpected halo filter count: {vis_halo}"

    app.set_search_query("nonexistent_token_999")
    app.root.update_idletasks()
    assert str(app.empty_card.winfo_manager()) == "pack"

    app.set_search_query("")
    app.set_category_filter("bindings")
    app.set_category_filter("all")

    # Verify In-Studio Cheat-Sheet Drawer & TV HUD Overlay
    app.toggle_cheat_sheet(True)
    assert app.cheat_sheet_open is True
    app.toggle_cheat_sheet(False)

    app.toggle_hud()
    assert app._hud_visible is True
    app.toggle_hud()
    assert app._hud_visible is False

    # Verify Telemetry & Demo Simulation ticks
    app._toggle_demo_telemetry()
    for _ in range(4):
        app.step_telemetry_and_overlays()
        app.root.update_idletasks()

    app.quit_app()

    after_bytes = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None
    assert before_bytes == after_bytes, "Self-test mutated config.json!"
    print(f"APP_SELF_TEST_OK (dpi_scale={app.scaler.scale:.2f}, win_px={app._px(1030)}x{win_h})")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_run_self_test())

    guard = SingleInstanceGuard()
    if guard.already_running:
        sys.exit(0)
    app = CouchControlApp(instance_guard=guard)
    app.run()
