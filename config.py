"""Persistent configuration for PS5 DualSense Couch Control."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

LIGHTBAR_PRESETS: dict[str, tuple[int, int, int]] = {
    "PS Blue": (45, 108, 223),
    "Cyan": (0, 210, 235),
    "Emerald": (16, 185, 129),
    "Purple": (168, 85, 247),
    "Gold": (245, 158, 11),
    "Off (Save Battery)": (0, 0, 0),
}

HALO_COLORS: dict[str, str] = {
    "PlayStation Blue": "#3b82f6",
    "Neon Yellow": "#facc15",
    "Emerald Green": "#10b981",
    "Cyan": "#06b6d4",
    "Hot Magenta": "#ec4899",
}


@dataclass
class AppConfig:
    # Cursor & Stick Movement
    cursor_speed: float = 7.5            # Base cursor speed (1.5 - 25.0)
    precision_multiplier: float = 0.35   # L2 hold slow-down factor (0.15 - 0.70)
    turbo_multiplier: float = 2.20       # R2 hold speed-up factor (1.30 - 3.50)
    scroll_speed: float = 12.0           # Smooth chat scroll speed (3.0 - 35.0)
    deadzone: float = 0.11               # Stick radial deadzone (0.04 - 0.30)
    invert_scroll: bool = False          # Natural vs classic vertical scroll

    # Cursor Size & Couch Visibility
    enlarge_cursor: bool = True          # Enlarge Windows cursor while active
    couch_cursor_size: int = 80          # CursorBaseSize (32=1x, 64=2x, 80=2.5x, 112=3.5x, 160=5x, 192=6x)
    normal_cursor_size: int = 32         # Normal cursor size restored on close / pause (32 = 1x Windows default)
    cursor_halo_enabled: bool = False    # Optional glowing spotlight ring around cursor
    cursor_halo_color: str = "PlayStation Blue"
    cursor_halo_size: int = 56           # Spotlight ring diameter in px (36 - 100)

    # Touchpad Settings
    touchpad_enabled: bool = True        # Use DualSense touchpad swipe & 2-finger scroll
    touchpad_tap_click: bool = True      # Light tap on touchpad = Left Click
    touchpad_sensitivity: float = 0.65   # Touchpad cursor speed (0.20 - 2.00)

    # Customizable Button Actions
    touchpad_press_action: str = "task_view"     # task_view | taskbar | desktop | left_click | middle_click | play_pause | fullscreen | voice_typing | zoom_in | zoom_out | zoom_reset
    ps_button_action: str = "toggle_panel"       # toggle_panel | none | task_view | toggle_hud | game_mode | play_pause | fullscreen | zoom_in | zoom_reset
    create_button_action: str = "taskbar"        # taskbar | desktop | task_view | screenshot | play_pause | fullscreen | volume_mute | zoom_in | zoom_out | zoom_reset
    triangle_button_action: str = "voice_typing" # voice_typing | cycle_mic | play_pause | fullscreen | copy | paste | zoom_in | zoom_out | zoom_reset
    l3_button_action: str = "osk"                # osk | play_pause | middle_click | fullscreen | volume_down | volume_mute | zoom_out | zoom_in | zoom_reset | copy | paste
    r3_button_action: str = "cycle_mic"          # cycle_mic | play_pause | middle_click | fullscreen | volume_up | volume_mute | zoom_in | zoom_out | zoom_reset | copy | paste

    # Text Zoom Settings
    l2_rstick_zoom: bool = True          # Hold L2 + Right Stick Up/Down to Zoom Text (Ctrl + / Ctrl -)
    zoom_mode: str = "ctrl_plus"         # ctrl_plus (Ctrl + +/-) | ctrl_wheel (Ctrl + Scroll Wheel)

    # Audio, Steam Guard, Feedback & Startup
    auto_switch_usb_mic: bool = True     # Auto-select DualSense USB mic when plugged in
    block_steam_ps_button: bool = True   # Prevent PS button from popping up Steam / Big Picture
    haptics_enabled: bool = True         # Controller rumble feedback
    lightbar_preset: str = "PS Blue"     # Lightbar LED color (or Off to save Bluetooth battery)
    hud_scale: str = "Large"             # Normal | Large | XL TV
    start_minimized: bool = False        # Start minimized to system tray
    run_at_startup: bool = False         # Launch automatically when Windows logs in
    show_hud_on_connect: bool = True     # Show toast when controller connects

    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                valid_keys = {f for f in cls.__dataclass_fields__}
                filtered = {k: v for k, v in raw.items() if k in valid_keys}
                return cls(**filtered)
            except Exception:
                pass
        cfg = cls()
        cfg.save()
        return cfg

    def save(self) -> None:
        try:
            CONFIG_PATH.write_text(
                json.dumps(asdict(self), indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
