"""Obsidian Minimal Pro — DPI-Aware Vector Icon Cache & Custom Precision Controls."""

from __future__ import annotations

from pathlib import Path
import re
import tkinter as tk
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageEnhance, ImageTk

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PNG_PATH = ASSETS_DIR / "app_logo.png"
LOGO_ICO_PATH = ASSETS_DIR / "app_logo.ico"
_MASTER_LOGO_CACHE: Image.Image | None = None


def load_master_logo() -> Image.Image | None:
    """Load and cache the flagship 1024x1024 RGBA Obsidian Minimal Pro squircle logo."""
    global _MASTER_LOGO_CACHE
    if _MASTER_LOGO_CACHE is not None:
        return _MASTER_LOGO_CACHE
    if LOGO_PNG_PATH.exists():
        try:
            _MASTER_LOGO_CACHE = Image.open(LOGO_PNG_PATH).convert("RGBA")
            return _MASTER_LOGO_CACHE
        except Exception:
            return None
    return None

# =============================================================================
# OBSIDIAN ZINC & INDIGO PALETTE
# =============================================================================
BG_APP = "#09090B"          # Zinc 950
BG_DOCK = "#0E0E12"         # Persistent Left Telemetry & Workflow Dock
BG_CARD = "#141419"         # Inspector Cards
BG_ELEVATED = "#1B1B23"     # Interactive Inputs / Segments
BG_HOVER = "#24242F"        # Subtle Hover Surface
BG_ACTIVE_PILL = "#1D1F3A"  # Indigo Tinted Active Pill

BORDER_CARD = "#24242C"     # Crisp 1px Structural Border
BORDER_SUBTLE = "#1C1C24"   # Hairline Internal Divider
BORDER_HOVER = "#343442"    # Hover Border

ACCENT = "#6366F1"          # Indigo 500
ACCENT_LIGHT = "#818CF8"    # Indigo 400
STATUS_OK = "#10B981"       # Emerald 500
STATUS_OK_BG = "#0C211B"
STATUS_WARN = "#F59E0B"     # Amber 500
STATUS_WARN_BG = "#261B0A"
STATUS_PEAK = "#F43F5E"     # Rose 500 (Audio Peak / Quit Hover)
STATUS_DANGER_BG = "#251016"
STATUS_DANGER_BORDER = "#4C1D29"

TEXT_PRIMARY = "#F4F4F5"    # Zinc 100
TEXT_SECONDARY = "#A1A1AA"  # Zinc 400
TEXT_MUTED = "#71717A"      # Zinc 500
TEXT_DIM = "#52525B"        # Zinc 600

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def blend_hex(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    r = int(round(r1 + (r2 - r1) * t))
    g = int(round(g1 + (g2 - g1) * t))
    b = int(round(b1 + (b2 - b1) * t))
    return f"#{r:02x}{g:02x}{b:02x}"


# Clean zero-emoji formatter for engine/audio toast strings
_TOAST_PREFIX_MAP: list[tuple[str, str]] = [
    ("🎙️", "VOICE // "),
    ("📡", "AUDIO // "),
    ("🛋️", "MODE // "),
    ("🎮", "MODE // "),
    ("🪟", "TASK VIEW // "),
    ("📌", "TASKBAR // "),
    ("🖥️", "DESKTOP // "),
    ("📸", "CAPTURE // "),
    ("📋", "CLIPBOARD // "),
    ("🔍+", "ZOOM IN // "),
    ("🔍−", "ZOOM OUT // "),
    ("🔍", "ZOOM // "),
    ("⌨️", "INPUT // "),
    ("⏮️", "TAB // "),
    ("⏭️", "TAB // "),
    ("⚠️", "NOTICE // "),
    ("⚙️", "STEAM // "),
    ("💤", "STEAM // "),
    ("🗕", "TRAY // "),
    ("⏯️", "MEDIA // "),
    ("🔊", "AUDIO // "),
    ("🔉", "AUDIO // "),
    ("🔇", "AUDIO // "),
    ("⛶", "VIEW // "),
    ("🖱️", "POINTER // "),
]

_EMOJI_STRIP_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\uFE0F"
    "]+"
)


def format_clean_toast(raw: str) -> tuple[str, str]:
    """Convert any emoji-prefixed engine message into crisp zero-emoji tag + body."""
    msg = (raw or "").strip()
    tag = "SYSTEM"
    for prefix, mapped in _TOAST_PREFIX_MAP:
        if msg.startswith(prefix):
            tag = mapped.replace("//", "").strip()
            msg = msg[len(prefix) :].strip()
            break
    # Replace controller symbol characters with clean text tokens
    msg = (
        msg.replace("✕", "Cross")
        .replace("□", "Square")
        .replace("○", "Circle")
        .replace("△", "Triangle")
    )
    msg = _EMOJI_STRIP_RE.sub("", msg).strip()
    return tag, msg


class DpiScaler:
    """Computes native Per-Monitor DPI factor so pixel layouts match typographic point scaling."""

    def __init__(self, root: tk.Misc) -> None:
        try:
            tk_sc = float(root.tk.call("tk", "scaling"))
            self.scale = max(1.0, min(3.5, tk_sc / (96.0 / 72.0)))
        except Exception:
            self.scale = 1.0

    def px(self, val: float) -> int:
        if val == 0:
            return 0
        sign = -1 if val < 0 else 1
        return sign * max(1, int(round(abs(val) * self.scale)))

    def border(self, val: int = 1) -> int:
        # Keep structural borders razor-sharp (1px up to 175% DPI, 2px on 200%-250% 4K)
        if val <= 0:
            return 0
        if self.scale >= 1.85:
            return max(1, int(round(val * 1.6)))
        return val


def create_tray_icon_image(paused: bool = False, connected: bool = True) -> Image.Image:
    """Render Obsidian Minimal Pro DualSense emblem for Windows System Tray & taskbar."""
    size = 64
    master = load_master_logo()
    if master is not None:
        s = 2
        S = size * s
        icon = master.resize((S, S), Image.Resampling.LANCZOS)
        if not connected:
            icon = ImageEnhance.Brightness(icon).enhance(0.75)
        d = ImageDraw.Draw(icon)
        dot_col = (
            (*hex_to_rgb(STATUS_WARN), 255)
            if paused
            else ((*hex_to_rgb(STATUS_OK), 255) if connected else (113, 113, 122, 255))
        )
        # Clean status indicator badge in bottom-right corner
        r = 8 * s
        cx, cy = S - 12 * s, S - 12 * s
        d.ellipse(
            (cx - r - 2 * s, cy - r - 2 * s, cx + r + 2 * s, cy + r + 2 * s),
            fill=(9, 9, 11, 245),
        )
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=dot_col)
        return icon.resize((size, size), Image.Resampling.LANCZOS)

    s = 4
    S = size * s
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if not connected:
        accent_rgb = hex_to_rgb("#52525B")
        bg_rgb = hex_to_rgb("#141419")
        fg_rgb = (161, 161, 170, 255)
    elif paused:
        accent_rgb = hex_to_rgb(STATUS_WARN)
        bg_rgb = hex_to_rgb("#1F160A")
        fg_rgb = (244, 244, 245, 255)
    else:
        accent_rgb = hex_to_rgb(ACCENT)
        bg_rgb = hex_to_rgb("#131424")
        fg_rgb = (244, 244, 245, 255)

    d.rounded_rectangle(
        (4 * s, 4 * s, S - 4 * s - 1, S - 4 * s - 1),
        radius=14 * s,
        fill=(*bg_rgb, 255),
        outline=(*accent_rgb, 245),
        width=int(2.5 * s),
    )

    cx, cy = S // 2, S // 2 + 2 * s
    # Controller body
    d.rounded_rectangle(
        (cx - 16 * s, cy - 10 * s, cx + 16 * s, cy + 5 * s),
        radius=7 * s,
        outline=fg_rgb,
        width=int(3.0 * s),
    )
    # Left & right handles
    d.line(
        [(cx - 14 * s, cy), (cx - 19 * s, cy + 12 * s), (cx - 9 * s, cy + 10 * s)],
        fill=fg_rgb,
        width=int(3.0 * s),
    )
    d.line(
        [(cx + 14 * s, cy), (cx + 19 * s, cy + 12 * s), (cx + 9 * s, cy + 10 * s)],
        fill=fg_rgb,
        width=int(3.0 * s),
    )
    # Top lightbar strip
    lb_col = (*hex_to_rgb(STATUS_WARN if paused else (ACCENT_LIGHT if connected else "#71717A")), 255)
    d.line(
        [(cx - 9 * s, cy - 10 * s), (cx + 9 * s, cy - 10 * s)],
        fill=lb_col,
        width=int(3.5 * s),
    )
    # Status dot in top-right corner
    dot_col = (
        (*hex_to_rgb(STATUS_WARN), 255)
        if paused
        else ((*hex_to_rgb(STATUS_OK), 255) if connected else (113, 113, 122, 255))
    )
    d.ellipse((S - 17 * s, 9 * s, S - 9 * s, 17 * s), fill=dot_col)

    return img.resize((size, size), Image.Resampling.LANCZOS)


class VectorIconCache:
    """Supersampled Pillow vector renderer keeping persistent PhotoImage references."""

    def __init__(self, master: tk.Misc, scaler: DpiScaler) -> None:
        self._master = master
        self._sc = scaler
        self._cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}

    def clear(self) -> None:
        self._cache.clear()

    def pill(
        self,
        w_logical: int,
        h_logical: int,
        fill: str,
        outline: str | None = None,
        outline_w: int = 1,
        radius: int = 6,
    ) -> ImageTk.PhotoImage:
        w = self._sc.px(w_logical)
        h = self._sc.px(h_logical)
        rad = self._sc.px(radius)
        key = ("pill", w, h, fill, outline, outline_w, rad)
        if key in self._cache:
            return self._cache[key]
        s = 2
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f_rgba = (*hex_to_rgb(fill), 255)
        o_rgba = (*hex_to_rgb(outline), 255) if outline else None
        d.rounded_rectangle(
            (s // 2, s // 2, w * s - s // 2 - 1, h * s - s // 2 - 1),
            radius=rad * s,
            fill=f_rgba,
            outline=o_rgba,
            width=max(1, outline_w * s) if o_rgba else 0,
        )
        photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS), master=self._master)
        self._cache[key] = photo
        return photo

    def toggle_frame(self, progress: float, hovered: bool = False) -> ImageTk.PhotoImage:
        p_quant = round(max(0.0, min(1.0, progress)), 2)
        w = self._sc.px(38)
        h = self._sc.px(20)
        key = ("toggle", w, h, p_quant, hovered)
        if key in self._cache:
            return self._cache[key]
        s = 3
        W, H = w * s, h * s
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        off_bg = "#262630" if hovered else "#1D1D25"
        on_bg = ACCENT_LIGHT if hovered else ACCENT
        track_hex = blend_hex(off_bg, on_bg, p_quant)
        border_hex = blend_hex("#343442", ACCENT_LIGHT, p_quant)

        bw = max(s, int(round(self._sc.border(1) * s)))
        d.rounded_rectangle(
            (bw, bw, W - bw - 1, H - bw - 1),
            radius=(H - 2 * bw) // 2,
            fill=(*hex_to_rgb(track_hex), 255),
            outline=(*hex_to_rgb(border_hex), 255),
            width=bw,
        )

        pad = int(round(H * 0.16))
        knob_d = H - 2 * pad
        travel = W - 2 * pad - knob_d
        kx = int(round(pad + travel * p_quant))
        ky = pad
        thumb_col = (255, 255, 255, 255) if p_quant > 0.4 else (212, 212, 220, 255)
        d.ellipse((kx, ky, kx + knob_d, ky + knob_d), fill=thumb_col)

        photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS), master=self._master)
        self._cache[key] = photo
        return photo

    def brand_mark(self, size_logical: int = 28) -> ImageTk.PhotoImage:
        size = self._sc.px(size_logical)
        key = ("brand_mark", size)
        if key in self._cache:
            return self._cache[key]

        master = load_master_logo()
        if master is not None:
            sharp = ImageEnhance.Sharpness(master.resize((size, size), Image.Resampling.LANCZOS)).enhance(1.12)
            photo = ImageTk.PhotoImage(sharp, master=self._master)
            self._cache[key] = photo
            return photo

        s = 3
        S = size * s
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        u = S / 28.0

        d.rounded_rectangle(
            (int(u), int(u), S - int(u) - 1, S - int(u) - 1),
            radius=int(7 * u),
            fill=(*hex_to_rgb("#161726"), 255),
            outline=(*hex_to_rgb(ACCENT), 225),
            width=max(2, int(1.2 * u)),
        )
        cx, cy = S // 2, int(S * 0.53)
        lw = max(2, int(1.6 * u))
        d.rounded_rectangle(
            (cx - int(7 * u), cy - int(4 * u), cx + int(7 * u), cy + int(2 * u)),
            radius=int(3 * u),
            outline=(244, 244, 245, 255),
            width=lw,
        )
        d.line(
            [(cx - int(6 * u), cy), (cx - int(8 * u), cy + int(5 * u)), (cx - int(4 * u), cy + int(4 * u))],
            fill=(244, 244, 245, 255),
            width=lw,
        )
        d.line(
            [(cx + int(6 * u), cy), (cx + int(8 * u), cy + int(5 * u)), (cx + int(4 * u), cy + int(4 * u))],
            fill=(244, 244, 245, 255),
            width=lw,
        )
        d.line(
            [(cx - int(4 * u), cy - int(4 * u)), (cx + int(4 * u), cy - int(4 * u))],
            fill=(*hex_to_rgb(ACCENT_LIGHT), 255),
            width=max(2, int(2.0 * u)),
        )
        photo = ImageTk.PhotoImage(img.resize((size, size), Image.Resampling.LANCZOS), master=self._master)
        self._cache[key] = photo
        return photo

    def glyph(
        self,
        kind: str,
        size_logical: int = 20,
        fg: str = TEXT_PRIMARY,
        bg: str | None = BG_ELEVATED,
        border: str | None = BORDER_CARD,
    ) -> ImageTk.PhotoImage:
        """Render pure vector controller / UI icons (strictly zero emojis)."""
        size = self._sc.px(size_logical)
        key = ("glyph", kind, size, fg, bg, border)
        if key in self._cache:
            return self._cache[key]
        s = 3
        S = size * s
        u = S / 20.0
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        if bg is not None:
            bw = max(2, int(1.0 * u))
            d.rounded_rectangle(
                (bw, bw, S - bw - 1, S - bw - 1),
                radius=int(5 * u),
                fill=(*hex_to_rgb(bg), 255),
                outline=(*hex_to_rgb(border), 255) if border else None,
                width=bw if border else 0,
            )

        col = (*hex_to_rgb(fg), 255)
        cx, cy = S // 2, S // 2
        lw = max(2, int(round(1.55 * u)))

        if kind == "cross":
            r = int(4.3 * u)
            d.line((cx - r, cy - r, cx + r, cy + r), fill=col, width=lw)
            d.line((cx - r, cy + r, cx + r, cy - r), fill=col, width=lw)
        elif kind == "circle":
            r = int(4.6 * u)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col, width=lw)
        elif kind == "square":
            r = int(4.3 * u)
            d.rectangle((cx - r, cy - r, cx + r, cy + r), outline=col, width=lw)
        elif kind == "triangle":
            r = int(5.0 * u)
            pts = [(cx, cy - r), (cx + r, cy + int(r * 0.82)), (cx - r, cy + int(r * 0.82))]
            d.polygon(pts, outline=col, width=lw)
        elif kind == "touchpad":
            rw, rh = int(5.6 * u), int(3.8 * u)
            d.rounded_rectangle((cx - rw, cy - rh, cx + rw, cy + rh), radius=int(2 * u), outline=col, width=lw)
            d.line((cx, cy - rh, cx, cy - int(0.5 * u)), fill=col, width=max(2, int(u)))
        elif kind == "ps":
            r = int(4.8 * u)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col, width=lw)
            ir = int(1.8 * u)
            d.ellipse((cx - ir, cy - ir, cx + ir, cy + ir), fill=col)
        elif kind == "create":
            d.line((cx - int(3 * u), cy - int(3 * u), cx - int(4 * u), cy + int(3 * u)), fill=col, width=lw)
            d.line((cx, cy - int(4 * u), cx, cy + int(4 * u)), fill=col, width=lw)
            d.line((cx + int(3 * u), cy - int(3 * u), cx + int(4 * u), cy + int(3 * u)), fill=col, width=lw)
        elif kind in ("l3", "r3", "stick"):
            r = int(5.0 * u)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col, width=lw)
            d.line((cx, cy - int(2 * u), cx, cy + int(2 * u)), fill=col, width=max(2, int(u)))
            d.line((cx - int(2 * u), cy, cx + int(2 * u), cy), fill=col, width=max(2, int(u)))
        elif kind == "dpad":
            arm, w2 = int(5.0 * u), int(1.8 * u)
            d.rectangle((cx - w2, cy - arm, cx + w2, cy + arm), outline=col, width=max(2, int(1.2 * u)))
            d.rectangle((cx - arm, cy - w2, cx + arm, cy + w2), outline=col, width=max(2, int(1.2 * u)))
        elif kind == "r1":
            rw, rh = int(5.8 * u), int(3.4 * u)
            d.rounded_rectangle((cx - rw, cy - rh, cx + rw, cy + rh), radius=int(2 * u), outline=col, width=lw)
            d.line((cx - int(2 * u), cy, cx + int(2 * u), cy), fill=col, width=lw)
        elif kind == "l2":
            pts = [
                (cx - int(5 * u), cy + int(4 * u)),
                (cx - int(4 * u), cy - int(4 * u)),
                (cx + int(4 * u), cy - int(4 * u)),
                (cx + int(5 * u), cy + int(4 * u)),
            ]
            d.polygon(pts, outline=col, width=lw)
        elif kind == "options":
            for dy in (-3.2, 0.0, 3.2):
                yy = cy + int(dy * u)
                d.line((cx - int(4.2 * u), yy, cx + int(4.2 * u), yy), fill=col, width=lw)
        elif kind == "search":
            r = int(3.8 * u)
            ox, oy = cx - int(1.2 * u), cy - int(1.2 * u)
            d.ellipse((ox - r, oy - r, ox + r, oy + r), outline=col, width=lw)
            d.line((ox + int(2.7 * u), oy + int(2.7 * u), cx + int(4.6 * u), cy + int(4.6 * u)), fill=col, width=lw)
        elif kind == "close":
            r = int(3.5 * u)
            d.line((cx - r, cy - r, cx + r, cy + r), fill=col, width=lw)
            d.line((cx - r, cy + r, cx + r, cy - r), fill=col, width=lw)
        elif kind == "chevron":
            d.line((cx - int(3.5 * u), cy - int(1.5 * u), cx, cy + int(2.0 * u)), fill=col, width=lw)
            d.line((cx, cy + int(2.0 * u), cx + int(3.5 * u), cy - int(1.5 * u)), fill=col, width=lw)
        elif kind == "check":
            d.line((cx - int(4 * u), cy, cx - int(1 * u), cy + int(3 * u)), fill=col, width=lw)
            d.line((cx - int(1 * u), cy + int(3 * u), cx + int(4.5 * u), cy - int(3 * u)), fill=col, width=lw)
        elif kind == "refresh":
            r = int(4.4 * u)
            d.arc((cx - r, cy - r, cx + r, cy + r), start=35, end=315, fill=col, width=lw)
            ax, ay = cx + int(3.2 * u), cy - int(2.6 * u)
            d.polygon([(ax, ay - int(2.2 * u)), (ax + int(2.4 * u), ay + int(1.2 * u)), (ax - int(1.8 * u), ay + int(1.2 * u))], fill=col)
        elif kind == "mic":
            mw = int(2.4 * u)
            d.rounded_rectangle((cx - mw, cy - int(5 * u), cx + mw, cy + int(1 * u)), radius=mw, outline=col, width=lw)
            d.arc((cx - int(4.4 * u), cy - int(3.5 * u), cx + int(4.4 * u), cy + int(3.5 * u)), start=0, end=180, fill=col, width=lw)
            d.line((cx, cy + int(3.5 * u), cx, cy + int(5.5 * u)), fill=col, width=lw)
        elif kind == "pause":
            d.rectangle((cx - int(3.4 * u), cy - int(4 * u), cx - int(1.2 * u), cy + int(4 * u)), fill=col)
            d.rectangle((cx + int(1.2 * u), cy - int(4 * u), cx + int(3.4 * u), cy + int(4 * u)), fill=col)
        elif kind == "play":
            pts = [(cx - int(2.8 * u), cy - int(4.2 * u)), (cx - int(2.8 * u), cy + int(4.2 * u)), (cx + int(4.2 * u), cy)]
            d.polygon(pts, fill=col)
        elif kind == "grid":
            for gx in (-3, 1):
                for gy in (-3, 1):
                    d.rectangle(
                        (cx + int(gx * u), cy + int(gy * u), cx + int((gx + 2) * u), cy + int((gy + 2) * u)),
                        fill=col,
                    )

        photo = ImageTk.PhotoImage(img.resize((size, size), Image.Resampling.LANCZOS), master=self._master)
        self._cache[key] = photo
        return photo

    def swatch(self, color_hex: str, selected: bool, size_logical: int = 22) -> ImageTk.PhotoImage:
        size = self._sc.px(size_logical)
        key = ("swatch", color_hex, selected, size)
        if key in self._cache:
            return self._cache[key]
        s = 3
        S = size * s
        u = S / 22.0
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = S // 2, S // 2

        if selected:
            ring_col = (*hex_to_rgb(TEXT_PRIMARY), 255)
            d.ellipse((int(u), int(u), S - int(u) - 1, S - int(u) - 1), outline=ring_col, width=max(2, int(1.6 * u)))

        inner_pad = int(4.5 * u) if selected else int(3.0 * u)
        rgb = hex_to_rgb(color_hex)
        is_off = rgb == (0, 0, 0)
        fill_col = (28, 28, 36, 255) if is_off else (*rgb, 255)
        out_col = (*hex_to_rgb(BORDER_HOVER), 255) if is_off else (*rgb, 200)
        d.ellipse(
            (inner_pad, inner_pad, S - inner_pad - 1, S - inner_pad - 1),
            fill=fill_col,
            outline=out_col,
            width=max(2, int(u)),
        )
        if is_off:
            r = int(3.2 * u)
            d.line((cx - r, cy + r, cx + r, cy - r), fill=(*hex_to_rgb(TEXT_MUTED), 255), width=max(2, int(u)))

        photo = ImageTk.PhotoImage(img.resize((size, size), Image.Resampling.LANCZOS), master=self._master)
        self._cache[key] = photo
        return photo


class ProToggle(tk.Canvas):
    """DPI-aware smooth animated pill toggle rendered via supersampled Pillow frames."""

    def __init__(
        self,
        parent: tk.Widget,
        icons: VectorIconCache,
        scaler: DpiScaler,
        initial: bool = False,
        on_change: Callable[[bool], None] | None = None,
        bg: str = BG_CARD,
    ) -> None:
        w = scaler.px(38)
        h = scaler.px(20)
        super().__init__(
            parent,
            width=w,
            height=h,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._icons = icons
        self._value = bool(initial)
        self._progress = 1.0 if self._value else 0.0
        self._hovered = False
        self._on_change = on_change
        self._anim_after: str | None = None

        self._img_id = self.create_image(w // 2, h // 2, image=self._icons.toggle_frame(self._progress, False))
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    @property
    def value(self) -> bool:
        return self._value

    def set_value(self, val: bool, animate: bool = False, notify: bool = False) -> None:
        val = bool(val)
        self._value = val
        if self._anim_after is not None:
            try:
                self.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None

        target = 1.0 if val else 0.0
        if not animate or not self.winfo_exists():
            self._progress = target
            self._redraw()
        else:
            self._step_anim(target)

        if notify and self._on_change:
            self._on_change(self._value)

    def _step_anim(self, target: float) -> None:
        if not self.winfo_exists():
            return
        diff = target - self._progress
        if abs(diff) <= 0.26:
            self._progress = target
            self._redraw()
            self._anim_after = None
            return
        self._progress += 0.34 if diff > 0 else -0.34
        self._redraw()
        self._anim_after = self.after(15, lambda: self._step_anim(target))

    def _toggle(self, _event: tk.Event | None = None) -> None:
        self.set_value(not self._value, animate=True, notify=True)

    def _on_enter(self, _event: tk.Event) -> None:
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._redraw()

    def _redraw(self) -> None:
        img = self._icons.toggle_frame(self._progress, self._hovered)
        self.itemconfigure(self._img_id, image=img)


class PrecisionSlider(tk.Frame):
    """DPI-aware horizontal engineering slider with clickable/draggable track and Consolas value pill."""

    def __init__(
        self,
        parent: tk.Widget,
        scaler: DpiScaler,
        label: str,
        min_val: float,
        max_val: float,
        step: float,
        initial: float,
        fmt: Callable[[float], str],
        on_change: Callable[[float], None] | None = None,
        bg: str = BG_CARD,
    ) -> None:
        super().__init__(parent, bg=bg)
        self._sc = scaler
        self._min = float(min_val)
        self._max = float(max_val)
        self._step = float(step)
        self._value = self._quantize(initial)
        self._fmt = fmt
        self._on_change = on_change
        self._dragging = False
        self._hovered = False

        self.columnconfigure(1, weight=1)

        self._lbl = tk.Label(
            self,
            text=label,
            font=(FONT_UI, 9),
            fg=TEXT_PRIMARY,
            bg=bg,
            width=24,
            anchor="w",
        )
        self._lbl.grid(row=0, column=0, sticky="w", padx=(0, scaler.px(8)))

        self._canvas_h = scaler.px(24)
        self._pad = scaler.px(9)
        self._canvas = tk.Canvas(
            self,
            height=self._canvas_h,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._canvas.grid(row=0, column=1, sticky="ew", padx=(scaler.px(4), scaler.px(10)))

        self._readout = tk.Label(
            self,
            text=self._fmt(self._value),
            font=(FONT_MONO, 9, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_DOCK,
            width=10,
            anchor="e",
            padx=scaler.px(8),
            pady=scaler.px(2),
            highlightbackground=BORDER_CARD,
            highlightthickness=scaler.border(1),
        )
        self._readout.grid(row=0, column=2, sticky="e")

        self._canvas.bind("<Configure>", lambda _e: self._redraw())
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Enter>", self._on_enter)
        self._canvas.bind("<Leave>", self._on_leave)

    def _quantize(self, v: float) -> float:
        clamped = max(self._min, min(self._max, float(v)))
        steps = round((clamped - self._min) / self._step)
        q = self._min + steps * self._step
        return max(self._min, min(self._max, round(q, 4)))

    @property
    def value(self) -> float:
        return self._value

    def set_value(self, val: float, notify: bool = False) -> None:
        self._value = self._quantize(val)
        self._readout.configure(text=self._fmt(self._value))
        self._redraw()
        if notify and self._on_change:
            self._on_change(self._value)

    def _x_to_val(self, x: int) -> float:
        w = max(self._sc.px(40), self._canvas.winfo_width())
        usable = max(1, w - 2 * self._pad)
        ratio = max(0.0, min(1.0, (x - self._pad) / usable))
        return self._quantize(self._min + ratio * (self._max - self._min))

    def _on_press(self, event: tk.Event) -> None:
        self._dragging = True
        self._readout.configure(highlightbackground=ACCENT, fg=ACCENT_LIGHT)
        self.set_value(self._x_to_val(event.x), notify=True)

    def _on_drag(self, event: tk.Event) -> None:
        if self._dragging:
            self.set_value(self._x_to_val(event.x), notify=True)

    def _on_release(self, _event: tk.Event) -> None:
        self._dragging = False
        self._readout.configure(highlightbackground=BORDER_CARD, fg=TEXT_PRIMARY)
        self._redraw()

    def _on_enter(self, _event: tk.Event) -> None:
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._redraw()

    def _redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        if w < self._sc.px(20):
            w = self._sc.px(220)
        h = self._canvas_h
        cy = h // 2
        pad = self._pad
        usable = max(1, w - 2 * pad)
        ratio = (self._value - self._min) / max(1e-6, self._max - self._min)
        kx = pad + ratio * usable

        rail_w = self._sc.px(4)
        c.create_line(pad, cy, w - pad, cy, fill="#252530", width=rail_w, capstyle="round")
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            tx = pad + frac * usable
            c.create_line(tx, cy + self._sc.px(5), tx, cy + self._sc.px(7), fill="#2A2A36", width=self._sc.border(1))
        if kx > pad + 1:
            c.create_line(
                pad,
                cy,
                kx,
                cy,
                fill=ACCENT_LIGHT if (self._dragging or self._hovered) else ACCENT,
                width=rail_w,
                capstyle="round",
            )
        r = self._sc.px(7 if (self._dragging or self._hovered) else 6)
        c.create_oval(
            kx - r,
            cy - r,
            kx + r,
            cy + r,
            fill=TEXT_PRIMARY,
            outline=ACCENT_LIGHT if self._dragging else ACCENT,
            width=self._sc.px(2),
        )
        ir = self._sc.px(2)
        c.create_oval(kx - ir, cy - ir, kx + ir, cy + ir, fill=ACCENT, outline="")


class SegmentedBar(tk.Frame):
    """Crisp segmented selector bar for discrete engineering scales."""

    def __init__(
        self,
        parent: tk.Widget,
        scaler: DpiScaler,
        options: list[tuple[str, Any]],
        initial: Any,
        on_change: Callable[[Any], None] | None = None,
    ) -> None:
        super().__init__(
            parent,
            bg=BG_DOCK,
            highlightbackground=BORDER_CARD,
            highlightthickness=scaler.border(1),
            padx=scaler.px(2),
            pady=scaler.px(2),
        )
        self._choices = options
        self._value = initial
        self._on_change = on_change
        self._btns: list[tuple[Any, tk.Label]] = []

        for idx, (lbl_text, val) in enumerate(options):
            lbl = tk.Label(
                self,
                text=lbl_text,
                font=(FONT_MONO if any(ch.isdigit() for ch in lbl_text) else FONT_UI, 9, "bold"),
                padx=scaler.px(10),
                pady=scaler.px(4),
                cursor="hand2",
            )
            lbl.pack(side="left", padx=(0 if idx == 0 else scaler.px(2), 0))
            lbl.bind("<Button-1>", lambda _e, v=val: self.set_value(v, notify=True))
            lbl.bind("<Enter>", lambda _e, w=lbl, v=val: self._hover(w, v, True))
            lbl.bind("<Leave>", lambda _e, w=lbl, v=val: self._hover(w, v, False))
            self._btns.append((val, lbl))

        self._refresh_visuals()

    @property
    def value(self) -> Any:
        return self._value

    def set_value(self, val: Any, notify: bool = False) -> None:
        self._value = val
        self._refresh_visuals()
        if notify and self._on_change:
            self._on_change(val)

    def _hover(self, widget: tk.Label, val: Any, entering: bool) -> None:
        if val == self._value:
            return
        widget.configure(bg=BG_HOVER if entering else BG_DOCK, fg=TEXT_PRIMARY if entering else TEXT_SECONDARY)

    def _refresh_visuals(self) -> None:
        for val, lbl in self._btns:
            if val == self._value:
                lbl.configure(bg=ACCENT, fg="#FFFFFF")
            else:
                lbl.configure(bg=BG_DOCK, fg=TEXT_SECONDARY)


class ProSelect(tk.Frame):
    """Self-contained dark popover selector supporting dynamic option list updates."""

    def __init__(
        self,
        parent: tk.Widget,
        icons: VectorIconCache,
        scaler: DpiScaler,
        options: list[tuple[str, str]],
        initial_key: str,
        on_change: Callable[[str], None] | None = None,
        width_logical: int = 250,
        bg_surface: str = BG_DOCK,
    ) -> None:
        super().__init__(
            parent,
            bg=bg_surface,
            highlightbackground=BORDER_CARD,
            highlightthickness=scaler.border(1),
            cursor="hand2",
            width=scaler.px(width_logical),
            height=scaler.px(29),
        )
        self.pack_propagate(False)
        self._icons = icons
        self._sc = scaler
        self._choices: list[tuple[str, str]] = list(options)
        self._value = initial_key
        self._on_change = on_change
        self._bg_surface = bg_surface
        self._popover: tk.Toplevel | None = None

        self._text_lbl = tk.Label(
            self,
            text=self._key_to_label(initial_key),
            font=(FONT_UI, 9),
            fg=TEXT_PRIMARY,
            bg=bg_surface,
            anchor="w",
            padx=scaler.px(8),
            cursor="hand2",
        )
        self._text_lbl.pack(side="left", fill="both", expand=True)

        self._chev_lbl = tk.Label(
            self,
            image=self._icons.glyph("chevron", size_logical=14, fg=TEXT_SECONDARY, bg=None, border=None),
            bg=bg_surface,
            padx=scaler.px(6),
            cursor="hand2",
        )
        self._chev_lbl.pack(side="right")

        for w in (self, self._text_lbl, self._chev_lbl):
            w.bind("<Button-1>", self._toggle_popover)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _key_to_label(self, key: str) -> str:
        for lbl, k in self._choices:
            if k == key:
                return lbl
        return self._choices[0][0] if self._choices else key

    @property
    def value(self) -> str:
        return self._value

    def set_options(self, options: list[tuple[str, str]], selected_key: str | None = None) -> None:
        self._choices = list(options)
        if selected_key is not None:
            self._value = selected_key
        self._text_lbl.configure(text=self._key_to_label(self._value))

    def set_value(self, key: str, notify: bool = False) -> None:
        self._value = key
        self._text_lbl.configure(text=self._key_to_label(key))
        if notify and self._on_change:
            self._on_change(key)

    def _on_enter(self, _e: tk.Event) -> None:
        if self._popover is None:
            self.configure(highlightbackground=BORDER_HOVER)

    def _on_leave(self, _e: tk.Event) -> None:
        if self._popover is None:
            self.configure(highlightbackground=BORDER_CARD)

    def close_popover(self) -> None:
        if self._popover is not None:
            try:
                self._popover.destroy()
            except Exception:
                pass
            self._popover = None
        if self.winfo_exists():
            self.configure(highlightbackground=BORDER_CARD)

    def _toggle_popover(self, _event: tk.Event | None = None) -> str:
        if self._popover is not None:
            self.close_popover()
            return "break"

        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + self._sc.px(2)
        w = max(self.winfo_width(), self._sc.px(230))

        pop = tk.Toplevel(self.winfo_toplevel())
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        pop.configure(bg=BORDER_HOVER)
        self._popover = pop
        self.configure(highlightbackground=ACCENT)

        b_px = self._sc.border(1)
        inner = tk.Frame(pop, bg=BG_CARD, padx=self._sc.px(3), pady=self._sc.px(3))
        inner.pack(fill="both", expand=True, padx=b_px, pady=b_px)

        chk_img = self._icons.glyph("check", size_logical=13, fg=ACCENT_LIGHT, bg=None, border=None)
        blank_img = self._icons.pill(13, 13, fill=BG_CARD, outline=None, radius=2)

        for lbl_text, k in self._choices:
            active = k == self._value
            row_bg = BG_ACTIVE_PILL if active else BG_CARD
            row = tk.Frame(inner, bg=row_bg, cursor="hand2", padx=self._sc.px(6), pady=self._sc.px(4))
            row.pack(fill="x", pady=max(1, self._sc.px(1)))

            ic = tk.Label(row, image=chk_img if active else blank_img, bg=row_bg)
            ic.pack(side="left", padx=(0, self._sc.px(6)))
            tx = tk.Label(
                row,
                text=lbl_text,
                font=(FONT_UI, 9, "bold" if active else "normal"),
                fg=TEXT_PRIMARY if active else TEXT_SECONDARY,
                bg=row_bg,
                anchor="w",
            )
            tx.pack(side="left", fill="x", expand=True)

            def pick(_e: tk.Event, chosen_k: str = k) -> None:
                self.close_popover()
                self.set_value(chosen_k, notify=True)

            def enter(_e: tk.Event, r: tk.Frame = row, i: tk.Label = ic, t: tk.Label = tx, act: bool = active) -> None:
                if not act:
                    r.configure(bg=BG_HOVER)
                    i.configure(bg=BG_HOVER)
                    t.configure(bg=BG_HOVER, fg=TEXT_PRIMARY)

            def leave(_e: tk.Event, r: tk.Frame = row, i: tk.Label = ic, t: tk.Label = tx, act: bool = active) -> None:
                if not act:
                    r.configure(bg=BG_CARD)
                    i.configure(bg=BG_CARD)
                    t.configure(bg=BG_CARD, fg=TEXT_SECONDARY)

            for widget in (row, ic, tx):
                widget.bind("<Button-1>", pick)
                widget.bind("<Enter>", enter)
                widget.bind("<Leave>", leave)

        pop.update_idletasks()
        ph = pop.winfo_reqheight()
        pw = max(w, pop.winfo_reqwidth())
        sh = self.winfo_screenheight()
        sw = self.winfo_screenwidth()
        if y + ph > sh - self._sc.px(24):
            y = max(self._sc.px(12), self.winfo_rooty() - ph - self._sc.px(2))
        if x + pw > sw - self._sc.px(12):
            x = max(self._sc.px(12), sw - pw - self._sc.px(12))
        pop.geometry(f"{pw}x{ph}+{x}+{y}")
        pop.focus_force()
        pop.bind("<FocusOut>", lambda _e: self.after(60, self.close_popover))
        pop.bind("<Escape>", lambda _e: self.close_popover())
        return "break"
