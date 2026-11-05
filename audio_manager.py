"""Windows Core Audio microphone detector, auto-switcher, and live voice meter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import comtypes
from pycaw.pycaw import (
    AudioUtilities,
    DEVICE_STATE,
    EDataFlow,
    ERole,
    IAudioEndpointVolume,
    IAudioMeterInformation,
)


DUALSENSE_MIC_KEYWORDS = (
    "wireless controller",
    "dualsense",
)


def is_dualsense_mic_name(name: str) -> bool:
    low = name.lower()
    return any(kw in low for kw in DUALSENSE_MIC_KEYWORDS)


@dataclass
class MicInfo:
    id: str
    name: str
    is_default: bool = False
    is_dualsense: bool = False


class AudioManager:
    """Monitors active Windows microphones, auto-selects DualSense USB mic, and reads peak audio level."""

    def __init__(
        self,
        on_toast: Callable[[str], None] | None = None,
    ) -> None:
        self._on_toast = on_toast
        self._last_dualsense_present: bool = False
        self._cached_meter_id: str | None = None
        self._cached_meter = None
        self._mics: list[MicInfo] = []
        self._default_mic: MicInfo | None = None

    @property
    def mics(self) -> list[MicInfo]:
        return list(self._mics)

    @property
    def default_mic(self) -> MicInfo | None:
        return self._default_mic

    @property
    def dualsense_usb_mic_available(self) -> bool:
        return any(m.is_dualsense for m in self._mics)

    def refresh_devices(self, auto_switch_usb: bool = True) -> list[MicInfo]:
        """Scan active Windows capture devices and optionally auto-activate DualSense USB mic on plug-in."""
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        default_id: str | None = None
        default_imm = None
        try:
            default_imm = AudioUtilities.GetMicrophone()
            if default_imm is not None:
                dev_obj = AudioUtilities.CreateDevice(default_imm)
                if dev_obj is not None:
                    default_id = dev_obj.id
        except Exception:
            default_imm = None

        found: list[MicInfo] = []
        try:
            raw_devs = AudioUtilities.GetAllDevices(
                data_flow=EDataFlow.eCapture.value,
                device_state=DEVICE_STATE.ACTIVE.value,
            )
            for d in raw_devs:
                fname = getattr(d, "FriendlyName", None) or "Microphone"
                did = getattr(d, "id", "")
                if not did:
                    continue
                found.append(
                    MicInfo(
                        id=did,
                        name=fname,
                        is_default=(did == default_id),
                        is_dualsense=is_dualsense_mic_name(fname),
                    )
                )
        except Exception:
            pass

        dualsense_mic = next((m for m in found if m.is_dualsense), None)
        dualsense_now = dualsense_mic is not None

        # Rising edge: DualSense USB mic was just plugged in!
        if dualsense_now and not self._last_dualsense_present and auto_switch_usb:
            if dualsense_mic and not dualsense_mic.is_default:
                if self.set_default_microphone(dualsense_mic.id, notify=False):
                    default_id = dualsense_mic.id
                    for m in found:
                        m.is_default = (m.id == default_id)
                    if self._on_toast:
                        self._on_toast(
                            "🎙️ DualSense USB Mic Active! (Ensure orange mute LED is OFF)"
                        )
        elif not dualsense_now and self._last_dualsense_present:
            current_def = next((m for m in found if m.is_default), None)
            if self._on_toast:
                fallback = current_def.name if current_def else "No Microphone"
                self._on_toast(f"📡 Unplugged USB — Active Mic: {fallback}")

        self._last_dualsense_present = dualsense_now
        self._mics = found
        self._default_mic = next((m for m in found if m.is_default), found[0] if found else None)

        # Keep meter bound to current default capture endpoint
        if default_id != self._cached_meter_id:
            self._bind_meter(default_imm, default_id)

        return found

    def _bind_meter(self, imm_device, dev_id: str | None) -> None:
        self._cached_meter = None
        self._cached_meter_id = dev_id
        if imm_device is None:
            return
        try:
            iface = imm_device.Activate(IAudioMeterInformation._iid_, 0, None)
            self._cached_meter = iface.QueryInterface(IAudioMeterInformation)
        except Exception:
            self._cached_meter = None

    def get_peak_level(self) -> float:
        """Return live peak input level [0.0, 1.0] for the active default microphone."""
        if self._cached_meter is None:
            return 0.0
        try:
            val = float(self._cached_meter.GetPeakValue())
            return max(0.0, min(1.0, val))
        except Exception:
            self._cached_meter = None
            self._cached_meter_id = None
            return 0.0

    def set_default_microphone(self, device_id: str, notify: bool = True) -> bool:
        """Set the Windows Default Recording & Communications Microphone."""
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            AudioUtilities.SetDefaultDevice(
                device_id,
                roles=[ERole.eConsole, ERole.eMultimedia, ERole.eCommunications],
            )
            # Also ensure Windows software mute is unmuted on the selected mic
            try:
                default_imm = AudioUtilities.GetMicrophone()
                if default_imm is not None:
                    vol_iface = default_imm.Activate(IAudioEndpointVolume._iid_, 0, None)
                    vol = vol_iface.QueryInterface(IAudioEndpointVolume)
                    if vol.GetMute():
                        vol.SetMute(0, None)
            except Exception:
                pass

            self._cached_meter_id = None  # Force rebind on next refresh
            for m in self._mics:
                m.is_default = (m.id == device_id)
                if m.is_default:
                    self._default_mic = m
            if notify and self._on_toast and self._default_mic:
                self._on_toast(f"🎙️ Active Mic: {self._default_mic.name}")
            return True
        except Exception:
            return False

    def cycle_microphone(self) -> MicInfo | None:
        """Cycle through active capture microphones (bound to R3 on the couch)."""
        mics = self.refresh_devices(auto_switch_usb=False)
        if not mics:
            if self._on_toast:
                self._on_toast("⚠️ No active microphones detected on Windows")
            return None
        if len(mics) == 1:
            only = mics[0]
            self.set_default_microphone(only.id, notify=False)
            if self._on_toast:
                extra = " (Plug in USB-C to use DualSense mic)" if not only.is_dualsense else ""
                self._on_toast(f"🎙️ Mic: {only.name}{extra}")
            return only

        cur_idx = next((i for i, m in enumerate(mics) if m.is_default), 0)
        nxt = mics[(cur_idx + 1) % len(mics)]
        self.set_default_microphone(nxt.id, notify=True)
        return nxt
