"""120 Hz PS5 DualSense Controller & Touchpad Engine for Couch PC + AI Chat Control."""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

# Must set SDL2 hints BEFORE importing pygame so background input & PS5 HIDAPI features work!
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("SDL_JOYSTICK_HIDAPI", "1")
os.environ.setdefault("SDL_JOYSTICK_HIDAPI_PS5", "1")
os.environ.setdefault("SDL_JOYSTICK_HIDAPI_PS5_RUMBLE", "1")

import pygame
import pygame._sdl2.controller as sdl_controller

from config import AppConfig, LIGHTBAR_PRESETS
from win_input import (
    InputSynthesizer,
    SteamPSButtonGuard,
    VK_DOWN,
    VK_LEFT,
    VK_RIGHT,
    VK_UP,
    is_shell_navigation_foreground,
)


def _apply_radial_curve(
    rx: float, ry: float, deadzone: float
) -> tuple[float, float, float]:
    """Apply radial deadzone and gentle precision curve for calm couch cursor aiming."""
    mag = math.hypot(rx, ry)
    if mag <= deadzone or mag < 1e-6:
        return 0.0, 0.0, 0.0

    norm = min(1.0, (mag - deadzone) / max(0.05, 1.0 - deadzone))
    curved = 0.12 * norm + 0.88 * (norm ** 2.6)

    ux = rx / mag
    uy = ry / mag
    return ux * curved, uy * curved, norm


def _decode_transport(guid: str, name: str) -> tuple[str, bool]:
    g = (guid or "").lower()
    low_name = (name or "").lower()
    is_ps5 = ("4c05" in g and ("e60c" in g or "df0c" in g)) or (
        "dualsense" in low_name or "ps5" in low_name
    )
    if g.startswith("0500"):
        return "Bluetooth", is_ps5
    if g.startswith("0300"):
        return "DualSense", is_ps5
    return "Connected", is_ps5


@dataclass
class ControllerTelemetry:
    connected: bool = False
    name: str = "Searching for PS5 Controller..."
    transport: str = "Disconnected"
    is_dualsense: bool = False
    power_level: str = "unknown"
    paused_game_mode: bool = False
    precision_active: bool = False
    turbo_active: bool = False
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    l2: float = 0.0
    r2: float = 0.0
    active_buttons: list[str] = field(default_factory=list)
    last_action: str = "Ready"


class ControllerEngine:
    """Polls PS5 DualSense at 120 Hz and translates inputs into desktop & AI chat actions."""

    def __init__(
        self,
        config: AppConfig,
        input_synth: InputSynthesizer,
        on_toast: Callable[[str], None] | None = None,
        on_toggle_hud: Callable[[], None] | None = None,
        on_toggle_panel: Callable[[], None] | None = None,
        on_cycle_mic: Callable[[], None] | None = None,
        on_cycle_preset: Callable[[], None] | None = None,
        on_pause_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self.config = config
        self.synth = input_synth
        self.steam_guard = SteamPSButtonGuard()
        self._on_toast = on_toast
        self._on_toggle_hud = on_toggle_hud
        self._on_toggle_panel = on_toggle_panel
        self._on_cycle_mic = on_cycle_mic
        self._on_cycle_preset = on_cycle_preset
        self._on_pause_changed = on_pause_changed

        self.telemetry = ControllerTelemetry()
        self._running = False
        self._thread: threading.Thread | None = None

        self._ctrl: sdl_controller.Controller | None = None
        self._joy: pygame.joystick.JoystickType | None = None
        self._active_instance_id: int | None = None

        self._prev_btns: dict[int, bool] = {}
        self._press_time: dict[int, float] = {}
        self._hold_fired: dict[int, bool] = {}
        self._repeat_next: dict[int, float] = {}
        self._combo_consumed_l2: bool = False
        self._nav_highlight_active: bool = False

        self._touch_fingers: dict[int, tuple[float, float]] = {}
        self._touch0_start_time: float = 0.0
        self._touch0_travel: float = 0.0
        self._touch_was_physical_click: bool = False

        self._last_led_rgb: tuple[int, int, int] | None = None

    @property
    def paused(self) -> bool:
        return self.telemetry.paused_game_mode

    def _base_led_rgb(self) -> tuple[int, int, int]:
        return LIGHTBAR_PRESETS.get(self.config.lightbar_preset, (45, 108, 223))

    def refresh_led_now(self) -> None:
        self._last_led_rgb = None
        if self.telemetry.paused_game_mode:
            self._set_led(220, 120, 20)
        else:
            r, g, b = self._base_led_rgb()
            self._set_led(r, g, b)

    def set_paused(self, paused: bool, notify: bool = True) -> None:
        self.telemetry.paused_game_mode = paused
        self.synth.release_all_buttons()
        if self._on_pause_changed:
            try:
                self._on_pause_changed(paused)
            except Exception:
                pass
        if paused:
            self._set_led(220, 120, 20)
            self._pulse_rumble(0.35, 0.35, 110)
            self.telemetry.last_action = "Paused (Game Mode)"
            if notify and self._on_toast:
                self._on_toast("🎮 Game Mode PAUSED — Press L2 + Options to Resume")
        else:
            r, g, b = self._base_led_rgb()
            self._set_led(r, g, b)
            self._pulse_rumble(0.20, 0.50, 75)
            self.telemetry.last_action = "Desktop Control Active"
            if notify and self._on_toast:
                self._on_toast("🛋️ Couch Control ACTIVE")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="DualSenseLoop", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self.synth.release_all_buttons()
        self.steam_guard.restore()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _emit_toast(self, msg: str) -> None:
        self.telemetry.last_action = msg
        if self._on_toast:
            self._on_toast(msg)

    def _pulse_rumble(self, low: float, high: float, ms: int) -> None:
        if not self.config.haptics_enabled or self._joy is None:
            return
        try:
            self._joy.rumble(low, high, ms)
        except Exception:
            pass

    def _set_led(self, r: int, g: int, b: int) -> None:
        if self._joy is None:
            return
        if self.config.lightbar_preset == "Off (Save Battery)":
            r, g, b = 0, 0, 0
        if self._last_led_rgb == (r, g, b):
            return
        try:
            self._joy.set_led(r, g, b)
            self._last_led_rgb = (r, g, b)
        except Exception:
            pass

    def _run_named_action(self, action_key: str) -> None:
        """Execute a user-configurable action string."""
        if action_key == "none":
            return
        elif action_key == "task_view":
            self._nav_highlight_active = True
            self.synth.open_task_view()
            self._pulse_rumble(0.18, 0.40, 55)
            self._emit_toast("🪟 All Open Programs (Win+Tab) — Arrows or Stick + ✕")
        elif action_key == "taskbar":
            self._nav_highlight_active = True
            self.synth.focus_taskbar()
            self._pulse_rumble(0.14, 0.32, 45)
            self._emit_toast("📌 Taskbar Active (Win+T) — Use ← / → + ✕ to Switch Apps")
        elif action_key == "desktop":
            self._nav_highlight_active = True
            self.synth.show_desktop()
            self._pulse_rumble(0.15, 0.35, 50)
            self._emit_toast("🖥️ Desktop (Win+D) — Use Arrows + ✕ to Open Apps")
        elif action_key == "screenshot":
            self.synth.take_screenshot()
            self._emit_toast("📸 Screenshot Tool (Win+Shift+S)")
        elif action_key == "left_click":
            self._nav_highlight_active = False
            self.synth.click_left()
        elif action_key == "voice_typing":
            self.synth.toggle_voice_typing()
            self._set_led(0, 220, 175)
            self._pulse_rumble(0.20, 0.55, 65)
            self._emit_toast("🎙️ Voice Typing (Win+H) — Speak now! Press □ to Send")
        elif action_key == "cycle_mic":
            if self._on_cycle_mic:
                self._on_cycle_mic()
        elif action_key == "copy":
            self.synth.send_copy()
            self._emit_toast("📋 Copied (Ctrl+C)")
        elif action_key == "paste":
            self.synth.send_paste()
            self._emit_toast("📋 Pasted (Ctrl+V)")
        elif action_key == "zoom_in":
            use_wheel = (self.config.zoom_mode == "ctrl_wheel")
            self.synth.zoom_in(use_wheel=use_wheel)
            self._pulse_rumble(0.10, 0.28, 35)
            self._emit_toast("🔍+ Zoom In (Ctrl +)")
        elif action_key == "zoom_out":
            use_wheel = (self.config.zoom_mode == "ctrl_wheel")
            self.synth.zoom_out(use_wheel=use_wheel)
            self._pulse_rumble(0.10, 0.28, 35)
            self._emit_toast("🔍− Zoom Out (Ctrl -)")
        elif action_key == "zoom_reset":
            self.synth.zoom_reset()
            self._pulse_rumble(0.12, 0.30, 40)
            self._emit_toast("🔍 100% Reset Zoom (Ctrl + 0)")
        elif action_key == "osk":
            self.synth.toggle_onscreen_keyboard()
            self._emit_toast("⌨️ Toggled On-Screen Keyboard")
        elif action_key == "toggle_hud":
            if self._on_toggle_hud:
                self._on_toggle_hud()
        elif action_key == "toggle_panel":
            if self._on_toggle_panel:
                self._on_toggle_panel()
        elif action_key == "game_mode":
            self.set_paused(not self.telemetry.paused_game_mode, notify=True)
        elif action_key == "play_pause":
            self.synth.media_play_pause()
            self._pulse_rumble(0.12, 0.30, 40)
            self._emit_toast("⏯️ Media Play / Pause")
        elif action_key == "volume_up":
            self.synth.volume_up()
            self._pulse_rumble(0.08, 0.22, 25)
            self._emit_toast("🔊 Volume Up")
        elif action_key == "volume_down":
            self.synth.volume_down()
            self._pulse_rumble(0.08, 0.22, 25)
            self._emit_toast("🔉 Volume Down")
        elif action_key == "volume_mute":
            self.synth.volume_mute()
            self._pulse_rumble(0.14, 0.32, 40)
            self._emit_toast("🔇 Audio Mute Toggled")
        elif action_key == "fullscreen":
            self.synth.toggle_fullscreen()
            self._pulse_rumble(0.12, 0.28, 35)
            self._emit_toast("⛶ Fullscreen Toggled (F11)")
        elif action_key == "middle_click":
            self._nav_highlight_active = False
            self.synth.click_middle()
            self._pulse_rumble(0.10, 0.25, 30)
            self._emit_toast("🖱️ Middle Mouse Click")
        elif action_key == "cycle_preset":
            self._pulse_rumble(0.16, 0.42, 55)
            if self._on_cycle_preset:
                self._on_cycle_preset()

    def _select_best_controller(self) -> None:
        count = pygame.joystick.get_count()
        if count <= 0:
            if self.telemetry.connected:
                self._disconnect_current(notify=True)
            return

        best_idx: int | None = None
        best_score = -1

        for idx in range(count):
            try:
                j = pygame.joystick.Joystick(idx)
                guid = j.get_guid()
                name = j.get_name()
                transport, is_ps5 = _decode_transport(guid, name)
                score = 0
                if is_ps5:
                    score += 10
                if sdl_controller.is_controller(idx):
                    score += 2
                if score > best_score:
                    best_score = score
                    best_idx = idx
            except Exception:
                continue

        if best_idx is None:
            return

        try:
            j = pygame.joystick.Joystick(best_idx)
            inst_id = j.get_instance_id()
            if self._joy is not None and self._active_instance_id == inst_id:
                try:
                    self.telemetry.power_level = j.get_power_level()
                except Exception:
                    pass
                return

            ctrl = sdl_controller.Controller(best_idx) if sdl_controller.is_controller(best_idx) else None
            guid = j.get_guid()
            raw_name = j.get_name()
            transport, is_ps5 = _decode_transport(guid, raw_name)
            friendly = "PS5 DualSense Controller" if is_ps5 else raw_name

            self._joy = j
            self._ctrl = ctrl
            self._active_instance_id = inst_id
            self._last_led_rgb = None
            self._prev_btns.clear()

            self.telemetry.connected = True
            self.telemetry.name = friendly
            self.telemetry.transport = transport
            self.telemetry.is_dualsense = is_ps5
            try:
                self.telemetry.power_level = j.get_power_level()
            except Exception:
                self.telemetry.power_level = "unknown"

            if not self.telemetry.paused_game_mode:
                r, g, b = self._base_led_rgb()
                self._set_led(r, g, b)
            self._pulse_rumble(0.18, 0.42, 70)

            try:
                print(
                    f"[DualSense] Connected: raw={raw_name!r} guid={guid} "
                    f"buttons={j.get_numbuttons()} hats={j.get_numhats()}",
                    flush=True,
                )
            except Exception:
                pass

            if self.config.show_hud_on_connect:
                self._emit_toast(f"🎮 {friendly} Connected")
        except Exception:
            pass

    def _disconnect_current(self, notify: bool = True) -> None:
        self.synth.release_all_buttons()
        self._ctrl = None
        self._joy = None
        self._active_instance_id = None
        self._last_led_rgb = None
        self.telemetry.connected = False
        self.telemetry.name = "Searching for PS5 Controller..."
        self.telemetry.transport = "Disconnected"
        self.telemetry.active_buttons = []
        self.telemetry.lx = self.telemetry.ly = 0.0
        self.telemetry.rx = self.telemetry.ry = 0.0
        self.telemetry.l2 = self.telemetry.r2 = 0.0
        if notify:
            self._emit_toast("⚠️ PS5 Controller Disconnected")

    def _read_axes(self) -> tuple[float, float, float, float, float, float]:
        try:
            if self._ctrl is not None and self._ctrl.get_init():
                lx = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_LEFTX) / 32767.0
                ly = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_LEFTY) / 32767.0
                rx = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_RIGHTX) / 32767.0
                ry = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_RIGHTY) / 32767.0
                l2 = max(0.0, self._ctrl.get_axis(pygame.CONTROLLER_AXIS_TRIGGERLEFT) / 32767.0)
                r2 = max(0.0, self._ctrl.get_axis(pygame.CONTROLLER_AXIS_TRIGGERRIGHT) / 32767.0)
                return (
                    max(-1.0, min(1.0, lx)),
                    max(-1.0, min(1.0, ly)),
                    max(-1.0, min(1.0, rx)),
                    max(-1.0, min(1.0, ry)),
                    min(1.0, l2),
                    min(1.0, r2),
                )
            if self._joy is not None and self._joy.get_init() and self._joy.get_numaxes() >= 4:
                lx = self._joy.get_axis(0)
                ly = self._joy.get_axis(1)
                rx = self._joy.get_axis(2)
                ry = self._joy.get_axis(3)
                l2 = (self._joy.get_axis(4) + 1.0) * 0.5 if self._joy.get_numaxes() > 4 else 0.0
                r2 = (self._joy.get_axis(5) + 1.0) * 0.5 if self._joy.get_numaxes() > 5 else 0.0
                return lx, ly, rx, ry, max(0.0, l2), max(0.0, r2)
        except Exception:
            pass
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    def _read_btn(self, sdl_btn: int) -> bool:
        if self._ctrl is not None:
            try:
                return bool(self._ctrl.get_button(sdl_btn))
            except Exception:
                return False
        return False

    def _handle_touchpad_event(self, ev: pygame.event.Event) -> None:
        if not self.config.touchpad_enabled or self.telemetry.paused_game_mode:
            return

        tp_down = getattr(pygame, "JOYTOUCHPADDOWN", None)
        tp_motion = getattr(pygame, "JOYTOUCHPADMOTION", None)
        tp_up = getattr(pygame, "JOYTOUCHPADUP", None)

        finger = getattr(ev, "finger", 0)
        x = float(getattr(ev, "x", 0.0))
        y = float(getattr(ev, "y", 0.0))

        if ev.type == tp_down:
            self._touch_fingers[finger] = (x, y)
            if finger == 0:
                self._touch0_start_time = time.perf_counter()
                self._touch0_travel = 0.0
                self._touch_was_physical_click = False
        elif ev.type == tp_motion:
            prev = self._touch_fingers.get(finger)
            self._touch_fingers[finger] = (x, y)
            if prev is not None:
                dx = x - prev[0]
                dy = y - prev[1]
                if finger == 0:
                    self._touch0_travel += math.hypot(dx, dy)
                    sens = self.config.touchpad_sensitivity
                    if 1 in self._touch_fingers:
                        v_sign = 1.0 if self.config.invert_scroll else -1.0
                        self.synth.scroll(
                            vertical=dy * 1500.0 * v_sign,
                            horizontal=dx * 1200.0,
                        )
                    else:
                        if abs(dx) > 0.0008 or abs(dy) > 0.0008:
                            self._nav_highlight_active = False
                        self.synth.move_relative(dx * 1350.0 * sens, dy * 850.0 * sens)
        elif ev.type == tp_up:
            self._touch_fingers.pop(finger, None)
            if (
                finger == 0
                and self.config.touchpad_tap_click
                and not self._touch_was_physical_click
            ):
                elapsed = time.perf_counter() - self._touch0_start_time
                if elapsed < 0.22 and self._touch0_travel < 0.015:
                    self._nav_highlight_active = False
                    self.synth.click_left()

    def _loop(self) -> None:
        pygame.init()
        pygame.joystick.init()
        sdl_controller.init()

        self._select_best_controller()

        target_dt = 1.0 / 120.0
        last_t = time.perf_counter()
        last_rescan_t = last_t
        pending_ps_action_at: float | None = None

        btn_names = {
            pygame.CONTROLLER_BUTTON_A: "✕ Cross",
            pygame.CONTROLLER_BUTTON_B: "○ Circle",
            pygame.CONTROLLER_BUTTON_X: "□ Square",
            pygame.CONTROLLER_BUTTON_Y: "△ Triangle",
            pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "L1",
            pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "R1",
            pygame.CONTROLLER_BUTTON_BACK: "Create",
            pygame.CONTROLLER_BUTTON_START: "Options",
            pygame.CONTROLLER_BUTTON_LEFTSTICK: "L3",
            pygame.CONTROLLER_BUTTON_RIGHTSTICK: "R3",
            pygame.CONTROLLER_BUTTON_DPAD_UP: "D-Up",
            pygame.CONTROLLER_BUTTON_DPAD_DOWN: "D-Down",
            pygame.CONTROLLER_BUTTON_DPAD_LEFT: "D-Left",
            pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "D-Right",
            pygame.CONTROLLER_BUTTON_GUIDE: "PS",
        }
        misc1_btn = getattr(pygame, "CONTROLLER_BUTTON_MISC1", 15)
        touchpad_click_btn = getattr(pygame, "CONTROLLER_BUTTON_TOUCHPAD", 20)
        last_rstick_zoom_t: float = 0.0
        rstick_zoom_neutral: bool = True

        while self._running:
            now = time.perf_counter()
            dt = min(0.05, max(0.001, now - last_t))
            last_t = now
            dt_scale = dt * 120.0

            # Intercept Steam if it tries to pop up after PS button press
            guard_active = (
                self.config.block_steam_ps_button and not self.telemetry.paused_game_mode
            )
            self.steam_guard.tick(now, enabled=guard_active)

            # Fire delayed PS button action slightly after Steam guard arms so Steam never steals it
            if pending_ps_action_at is not None and now >= pending_ps_action_at:
                pending_ps_action_at = None
                self._run_named_action(self.config.ps_button_action)

            for ev in pygame.event.get():
                if ev.type in (
                    pygame.JOYDEVICEADDED,
                    pygame.JOYDEVICEREMOVED,
                    getattr(pygame, "CONTROLLERDEVICEADDED", -1),
                    getattr(pygame, "CONTROLLERDEVICEREMOVED", -1),
                ):
                    self._select_best_controller()
                elif ev.type in (
                    getattr(pygame, "JOYTOUCHPADDOWN", -1),
                    getattr(pygame, "JOYTOUCHPADMOTION", -1),
                    getattr(pygame, "JOYTOUCHPADUP", -1),
                ):
                    self._handle_touchpad_event(ev)

            if now - last_rescan_t > 2.0:
                last_rescan_t = now
                self._select_best_controller()

            if not self.telemetry.connected or self._joy is None:
                time.sleep(0.05)
                continue

            lx, ly, rx, ry, l2, r2 = self._read_axes()
            self.telemetry.lx = lx
            self.telemetry.ly = ly
            self.telemetry.rx = rx
            self.telemetry.ry = ry
            self.telemetry.l2 = l2
            self.telemetry.r2 = r2

            l2_held = l2 > 0.30
            r2_held = r2 > 0.30
            self.telemetry.precision_active = l2_held and not self.telemetry.paused_game_mode
            self.telemetry.turbo_active = r2_held and not l2_held and not self.telemetry.paused_game_mode

            if not l2_held:
                self._combo_consumed_l2 = False

            cur_btns: dict[int, bool] = {}
            pressed_labels: list[str] = []
            for b_id in btn_names:
                cur_btns[b_id] = self._read_btn(b_id)

            try:
                if self._joy is not None and self._joy.get_init() and self._joy.get_numhats() > 0:
                    hx, hy = self._joy.get_hat(0)
                    if hy > 0:
                        cur_btns[pygame.CONTROLLER_BUTTON_DPAD_UP] = True
                    elif hy < 0:
                        cur_btns[pygame.CONTROLLER_BUTTON_DPAD_DOWN] = True
                    if hx < 0:
                        cur_btns[pygame.CONTROLLER_BUTTON_DPAD_LEFT] = True
                    elif hx > 0:
                        cur_btns[pygame.CONTROLLER_BUTTON_DPAD_RIGHT] = True
            except Exception:
                pass

            for b_id, label in btn_names.items():
                if cur_btns.get(b_id, False):
                    pressed_labels.append(label)

            cur_btns[misc1_btn] = self._read_btn(misc1_btn)
            cur_btns[touchpad_click_btn] = self._read_btn(touchpad_click_btn)
            if cur_btns[misc1_btn]:
                pressed_labels.append("Mic Btn")
            if cur_btns[touchpad_click_btn]:
                self._touch_was_physical_click = True
                pressed_labels.append("Touchpad")
            if l2_held:
                pressed_labels.append("L2")
            if r2_held:
                pressed_labels.append("R2")

            self.telemetry.active_buttons = pressed_labels

            def just_pressed(b: int) -> bool:
                return cur_btns.get(b, False) and not self._prev_btns.get(b, False)

            def just_released(b: int) -> bool:
                return not cur_btns.get(b, False) and self._prev_btns.get(b, False)

            for b, is_down in cur_btns.items():
                if is_down and not self._prev_btns.get(b, False):
                    self._press_time[b] = now
                    self._hold_fired[b] = False
                    self._repeat_next[b] = now + 0.36

            # L2 + Options ALWAYS works (even in Game Mode!)
            if just_pressed(pygame.CONTROLLER_BUTTON_START) and l2_held:
                self._combo_consumed_l2 = True
                self._hold_fired[pygame.CONTROLLER_BUTTON_START] = True
                self.set_paused(not self.telemetry.paused_game_mode, notify=True)
                self._prev_btns = cur_btns
                time.sleep(target_dt)
                continue

            if self.telemetry.paused_game_mode:
                self._prev_btns = cur_btns
                time.sleep(target_dt)
                continue

            # Update DualSense Lightbar color by active mode
            if l2_held:
                self._set_led(168, 85, 247)
            else:
                r, g, b = self._base_led_rgb()
                self._set_led(r, g, b)

            # 1. Cursor Movement (Left Stick)
            speed_mult = 1.0
            if l2_held:
                speed_mult = self.config.precision_multiplier
            elif r2_held:
                speed_mult = self.config.turbo_multiplier

            cx, cy, _ = _apply_radial_curve(lx, ly, self.config.deadzone)
            if cx != 0.0 or cy != 0.0:
                self._nav_highlight_active = False
                px_scale = self.config.cursor_speed * speed_mult * dt_scale
                self.synth.move_relative(cx * px_scale, cy * px_scale)

            # 2. Right Stick -> Smooth Chat Scrolling OR Hold L2 + Right Stick Up/Down = Text Zoom (Ctrl + / -)!
            if l2_held and self.config.l2_rstick_zoom:
                if abs(ry) < 0.25:
                    rstick_zoom_neutral = True
                elif ry < -0.52 and (rstick_zoom_neutral or now - last_rstick_zoom_t >= 0.26):
                    rstick_zoom_neutral = False
                    last_rstick_zoom_t = now
                    self._combo_consumed_l2 = True
                    self._run_named_action("zoom_in")
                elif ry > 0.52 and (rstick_zoom_neutral or now - last_rstick_zoom_t >= 0.26):
                    rstick_zoom_neutral = False
                    last_rstick_zoom_t = now
                    self._combo_consumed_l2 = True
                    self._run_named_action("zoom_out")
            else:
                rstick_zoom_neutral = True
                sx, sy, _ = _apply_radial_curve(rx, ry, self.config.deadzone)
                if sx != 0.0 or sy != 0.0:
                    scroll_mult = self.config.precision_multiplier if l2_held else (
                        self.config.turbo_multiplier if r2_held else 1.0
                    )
                    v_dir = 1.0 if self.config.invert_scroll else -1.0
                    v_delta = (sy * v_dir) * self.config.scroll_speed * 2.2 * scroll_mult * dt_scale
                    h_delta = sx * self.config.scroll_speed * 1.8 * scroll_mult * dt_scale
                    self.synth.scroll(vertical=v_delta, horizontal=h_delta)

            # 3. Touchpad Physical Button Click -> User-chosen action (Default: All Open Programs Win+Tab)
            if just_pressed(touchpad_click_btn):
                self._touch_was_physical_click = True
                self._run_named_action(self.config.touchpad_press_action)

            # 4. PS Guide Button -> L2 + PS = Cycle Activity Preset | Tap = Arm Steam Blocker + Run PS Button Action!
            if just_pressed(pygame.CONTROLLER_BUTTON_GUIDE):
                if self.config.block_steam_ps_button:
                    self.steam_guard.notify_ps_button_pressed()
                if l2_held:
                    self._combo_consumed_l2 = True
                    self._run_named_action("cycle_preset")
                else:
                    pending_ps_action_at = now + 0.09

            # 5. Cross (✕) -> Smart Activate (Enter when keyboard-highlighting apps/boxes) OR Left Click & Drag!
            b_cross = pygame.CONTROLLER_BUTTON_A
            if self._nav_highlight_active:
                if just_pressed(b_cross):
                    self._nav_highlight_active = False
                    self.synth.tap_key(0x0D)
                    self._pulse_rumble(0.10, 0.30, 35)
                self.synth.set_left_button(False)
            else:
                self.synth.set_left_button(cur_btns.get(b_cross, False))

            # 6. Circle (○) -> Tap = Right Click (or Esc in nav) | Hold (0.45s) = Escape
            b_circle = pygame.CONTROLLER_BUTTON_B
            if cur_btns.get(b_circle, False):
                if not self._hold_fired.get(b_circle, False) and (now - self._press_time.get(b_circle, now)) >= 0.45:
                    self._hold_fired[b_circle] = True
                    self._nav_highlight_active = False
                    self.synth.send_escape()
                    self._pulse_rumble(0.15, 0.30, 45)
                    self._emit_toast("⎋ Escape")
            elif just_released(b_circle) and not self._hold_fired.get(b_circle, False):
                if self._nav_highlight_active:
                    self._nav_highlight_active = False
                    self.synth.send_escape()
                else:
                    self.synth.click_right()

            # 7. Triangle (△) -> Configurable Action (Default: Voice Typing Win+H) | L2+Triangle = Cycle Mic
            if just_pressed(pygame.CONTROLLER_BUTTON_Y):
                if l2_held:
                    self._combo_consumed_l2 = True
                    if self._on_cycle_mic:
                        self._on_cycle_mic()
                else:
                    self._run_named_action(self.config.triangle_button_action)

            # 8. Square (□) -> Tap = Enter | Hold (0.42s) or L2+Square = Shift+Enter
            b_sq = pygame.CONTROLLER_BUTTON_X
            if cur_btns.get(b_sq, False):
                if l2_held and just_pressed(b_sq):
                    self._combo_consumed_l2 = True
                    self._hold_fired[b_sq] = True
                    self.synth.send_enter(newline_only=True)
                    self._emit_toast("↵ New Line (Shift+Enter)")
                elif not self._hold_fired.get(b_sq, False) and (now - self._press_time.get(b_sq, now)) >= 0.42:
                    self._hold_fired[b_sq] = True
                    self.synth.send_enter(newline_only=True)
                    self._pulse_rumble(0.12, 0.25, 40)
                    self._emit_toast("↵ New Line (Shift+Enter)")
            elif just_released(b_sq) and not self._hold_fired.get(b_sq, False):
                self._nav_highlight_active = False
                self.synth.send_enter(newline_only=False)
                self._pulse_rumble(0.10, 0.35, 35)
                self._emit_toast("⏎ Enter")

            # 9. L1 -> Backspace (with hold repeat) | L2 + L1 -> Undo (Ctrl+Z)
            b_l1 = pygame.CONTROLLER_BUTTON_LEFTSHOULDER
            if just_pressed(b_l1):
                if l2_held:
                    self._combo_consumed_l2 = True
                    self._hold_fired[b_l1] = True
                    self.synth.send_undo()
                    self._emit_toast("↩️ Undo (Ctrl+Z)")
                else:
                    self.synth.send_backspace()
            elif cur_btns.get(b_l1, False) and not self._hold_fired.get(b_l1, False):
                if now >= self._repeat_next.get(b_l1, now + 1.0):
                    self._repeat_next[b_l1] = now + 0.055
                    self.synth.send_backspace()

            # 10. R1 -> Jump Between Content Boxes in Any Window (Tab / L2+R1 = Shift+Tab)
            b_r1 = pygame.CONTROLLER_BUTTON_RIGHTSHOULDER
            if just_pressed(b_r1):
                self._nav_highlight_active = True
                if l2_held:
                    self._combo_consumed_l2 = True
                    self.synth.focus_prev_box()
                else:
                    self.synth.focus_next_box()
            elif cur_btns.get(b_r1, False):
                if now >= self._repeat_next.get(b_r1, now + 1.0):
                    self._repeat_next[b_r1] = now + 0.11
                    self._nav_highlight_active = True
                    if l2_held:
                        self.synth.focus_prev_box()
                    else:
                        self.synth.focus_next_box()

            # 11. D-Pad Arrows -> Navigate Desktop Apps, Taskbar, Win+Tab, Lists & Text
            dpad_map = [
                (pygame.CONTROLLER_BUTTON_DPAD_UP, VK_UP, "zoom_in"),
                (pygame.CONTROLLER_BUTTON_DPAD_DOWN, VK_DOWN, "zoom_out"),
                (pygame.CONTROLLER_BUTTON_DPAD_LEFT, VK_LEFT, "copy"),
                (pygame.CONTROLLER_BUTTON_DPAD_RIGHT, VK_RIGHT, "paste"),
            ]
            for b_dp, vk_arrow, fn_action in dpad_map:
                if just_pressed(b_dp):
                    if l2_held:
                        self._combo_consumed_l2 = True
                        self._hold_fired[b_dp] = True
                        if fn_action in ("zoom_in", "zoom_out"):
                            self._repeat_next[b_dp] = now + 0.30
                            self._run_named_action(fn_action)
                        elif fn_action == "copy":
                            self.synth.send_copy()
                            self._pulse_rumble(0.12, 0.30, 40)
                            self._emit_toast("📋 Copied (Ctrl+C)")
                        elif fn_action == "paste":
                            self.synth.send_paste()
                            self._pulse_rumble(0.12, 0.30, 40)
                            self._emit_toast("📋 Pasted (Ctrl+V)")
                    else:
                        if is_shell_navigation_foreground():
                            self._nav_highlight_active = True
                        self.synth.tap_key(vk_arrow)
                elif cur_btns.get(b_dp, False):
                    if l2_held and fn_action in ("zoom_in", "zoom_out"):
                        if now >= self._repeat_next.get(b_dp, now + 1.0):
                            self._repeat_next[b_dp] = now + 0.22
                            self._run_named_action(fn_action)
                    elif not self._hold_fired.get(b_dp, False):
                        if now >= self._repeat_next.get(b_dp, now + 1.0):
                            self._repeat_next[b_dp] = now + 0.08
                            if is_shell_navigation_foreground():
                                self._nav_highlight_active = True
                            self.synth.tap_key(vk_arrow)

            # 12. Create / Share -> Tap = Configured Action (Default: Taskbar Win+T) | Hold = Screenshot | L2+Create = Desktop
            b_create = pygame.CONTROLLER_BUTTON_BACK
            if cur_btns.get(b_create, False):
                if l2_held and just_pressed(b_create):
                    self._combo_consumed_l2 = True
                    self._hold_fired[b_create] = True
                    self._run_named_action("desktop")
                elif not self._hold_fired.get(b_create, False) and (now - self._press_time.get(b_create, now)) >= 0.42:
                    self._hold_fired[b_create] = True
                    self._pulse_rumble(0.16, 0.38, 50)
                    self._run_named_action("screenshot")
            elif just_released(b_create) and not self._hold_fired.get(b_create, False):
                self._run_named_action(self.config.create_button_action)

            # 13. Options -> Toggle Couch Cheat-Sheet HUD
            if just_released(pygame.CONTROLLER_BUTTON_START) and not self._hold_fired.get(pygame.CONTROLLER_BUTTON_START, False):
                if self._on_toggle_hud:
                    self._on_toggle_hud()

            # 14. L3 -> Configurable Action (Default: On-Screen Keyboard) | L2 + L3 = Previous Browser Tab
            if just_pressed(pygame.CONTROLLER_BUTTON_LEFTSTICK):
                if l2_held:
                    self._combo_consumed_l2 = True
                    self.synth.prev_tab()
                    self._emit_toast("⏮️ Previous Browser Tab")
                else:
                    self._run_named_action(self.config.l3_button_action)

            # 15. R3 -> Configurable Action (Default: Switch Mic) | L2 + R3 = Next Browser Tab
            if just_pressed(pygame.CONTROLLER_BUTTON_RIGHTSTICK):
                if l2_held:
                    self._combo_consumed_l2 = True
                    self.synth.next_tab()
                    self._emit_toast("⏭️ Next Browser Tab")
                else:
                    self._run_named_action(self.config.r3_button_action)

            # 16. Physical DualSense Mic Mute Button -> L2 + Mic Btn = Mute TV Audio | Tap = Mic LED reminder
            if just_pressed(misc1_btn):
                if l2_held:
                    self._combo_consumed_l2 = True
                    self._run_named_action("volume_mute")
                else:
                    self._emit_toast(
                        "🎙️ Controller Mute Button: Orange LED OFF = Mic Live | ON = Muted"
                    )

            self._prev_btns = cur_btns

            elapsed = time.perf_counter() - now
            sleep_for = target_dt - elapsed
            if sleep_for > 0.0005:
                time.sleep(sleep_for)
