#!/usr/bin/env python3
"""Harmless HID-injection simulator for demonstrating HIDGuard end to end.

This is a standalone tool that knows nothing about HIDGuard. It creates a real
virtual keyboard through /dev/uinput -- the same thing a Rubber Ducky does when
it enumerates as a HID device -- and types a preset payload into whatever window
has focus. The kernel and udev treat it exactly like plugged-in hardware, so
HIDGuard sees it through its normal udev -> session -> detection pipeline rather
than through any test seam.

The effect is deliberately visible and harmless: focus a text editor before the
countdown ends and the payload appears there at machine speed while HIDGuard
flags the session. No Enter is sent, so nothing is ever executed.

Requires write access to /dev/uinput, which is root-only on most systems:

    sudo .venv/bin/python tools/ducky.py --payload superhuman

Aim it at a scratch editor or an empty virtual terminal (Ctrl+Alt+F3), never at
a shell you care about.
"""

from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass

import pyudev
from evdev import UInput
from evdev import ecodes as e

# A subset of US-layout keys, enough for the demo strings below. Each printable
# character maps to a key code and whether Shift has to be held for it; anything
# outside this table is skipped with a warning rather than typed wrong.
_SHIFTED = {
    "!": "KEY_1", "@": "KEY_2", "#": "KEY_3", "$": "KEY_4", "%": "KEY_5",
    "^": "KEY_6", "&": "KEY_7", "*": "KEY_8", "(": "KEY_9", ")": "KEY_0",
    "_": "KEY_MINUS", "+": "KEY_EQUAL", ":": "KEY_SEMICOLON", '"': "KEY_APOSTROPHE",
    "?": "KEY_SLASH", ">": "KEY_DOT", "<": "KEY_COMMA",
}
_UNSHIFTED = {
    " ": "KEY_SPACE", ".": "KEY_DOT", ",": "KEY_COMMA", "-": "KEY_MINUS",
    "=": "KEY_EQUAL", ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE", "/": "KEY_SLASH",
}


def _build_keymap() -> dict[str, tuple[int, bool]]:
    keymap: dict[str, tuple[int, bool]] = {}
    for char in "abcdefghijklmnopqrstuvwxyz":
        code = getattr(e, f"KEY_{char.upper()}")
        keymap[char] = (code, False)
        keymap[char.upper()] = (code, True)
    for digit in "0123456789":
        keymap[digit] = (getattr(e, f"KEY_{digit}"), False)
    for char, name in _UNSHIFTED.items():
        keymap[char] = (getattr(e, name), False)
    for char, name in _SHIFTED.items():
        keymap[char] = (getattr(e, name), True)
    return keymap


KEYMAP = _build_keymap()

# The visible payload. Pure text, no Enter -- it fills a focused editor and does
# nothing else. Long enough (>60 chars) that the fast presets also trip the
# volume-based rules (long_burst, no_corrections) on top of the timing ones.
MESSAGE = "HIDGuard demo: this line was typed by a simulated HID injection device."


@dataclass
class Timing:
    """How a preset spaces its keystrokes, in milliseconds.

    gap is the delay between one key and the next; dwell is how long each key is
    held. Both are drawn per keystroke from a normal distribution, so a std of 0
    means a perfectly rigid cadence -- exactly the machine signature HIDGuard's
    no_jitter and uniform_dwell rules look for.
    """

    gap_mean: float
    gap_std: float
    dwell_mean: float
    dwell_std: float

    def gap_ms(self) -> float:
        return max(1.0, random.gauss(self.gap_mean, self.gap_std))

    def dwell_ms(self) -> float:
        return max(0.5, random.gauss(self.dwell_mean, self.dwell_std))


@dataclass
class Preset:
    description: str
    timing: Timing
    launcher: bool = False  # send Ctrl+Alt+T first, to trip launcher_sequence
    # Seconds to wait before typing. The editor presets need this so the tester
    # can focus a target window; the launcher preset opens and focuses its own
    # terminal, so it stays short on purpose -- a long countdown would push the
    # hotkey past HIDGuard's launcher_sequence window and the rule would miss it.
    countdown: int = 5


PRESETS = {
    # Human cadence: ~150ms between keys with real variability, ordinary hold
    # times. HIDGuard should read this as benign.
    "benign": Preset(
        "Human-speed typing with natural jitter -- expected verdict: benign.",
        Timing(gap_mean=150, gap_std=95, dwell_mean=90, dwell_std=30),
    ),
    # Fixed 12ms cadence, near-zero dwell variation: superhuman speed with no
    # jitter, sustained in one burst. Expected verdict: malicious.
    "superhuman": Preset(
        "Fixed 12ms cadence, no jitter -- expected verdict: malicious.",
        Timing(gap_mean=12, gap_std=0, dwell_mean=1, dwell_std=0),
    ),
    # Same machine cadence, preceded by a launcher hotkey the instant the device
    # appears -- the opening move of a real payload. Expected verdict: malicious.
    "launcher": Preset(
        "Opens a terminal via Ctrl+Alt+T, then types fast -- expected verdict: malicious.",
        Timing(gap_mean=12, gap_std=0, dwell_mean=1, dwell_std=0),
        launcher=True,
        countdown=1,
    ),
}


def _find_real_keyboard_node() -> str:
    """A device node udev already tags as a keyboard, to clone capabilities from.

    Hand-declaring key codes doesn't reliably reproduce udev's ID_INPUT_KEYBOARD
    tag -- its classifier also weighs EV_MSC/EV_REP support that UInput won't
    enable unless the source's capabilities ask for it. Cloning a real keyboard
    sidesteps reverse-engineering that, which is why HIDGuard then sees the
    virtual device as a keyboard at all.
    """
    context = pyudev.Context()
    for device in context.list_devices(subsystem="input", ID_INPUT_KEYBOARD="1"):
        if device.device_node:
            return device.device_node
    raise SystemExit("No real keyboard found to clone; is one attached?")


def _tap(ui: UInput, code: int, dwell_ms: float, shift: bool = False) -> None:
    if shift:
        ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
    ui.write(e.EV_KEY, code, 1)
    ui.syn()
    time.sleep(dwell_ms / 1000)
    ui.write(e.EV_KEY, code, 0)
    if shift:
        ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
    ui.syn()


def _send_launcher(ui: UInput) -> None:
    """Ctrl+Alt+T: on most desktops this opens a terminal (the visible effect)."""
    for code in (e.KEY_LEFTCTRL, e.KEY_LEFTALT, e.KEY_T):
        ui.write(e.EV_KEY, code, 1)
    ui.syn()
    time.sleep(0.02)
    for code in (e.KEY_T, e.KEY_LEFTALT, e.KEY_LEFTCTRL):
        ui.write(e.EV_KEY, code, 0)
    ui.syn()


def _type_message(ui: UInput, message: str, timing: Timing) -> None:
    for char in message:
        mapped = KEYMAP.get(char)
        if mapped is None:
            print(f"  (skipping unmapped character {char!r})")
            continue
        code, shift = mapped
        _tap(ui, code, timing.dwell_ms(), shift)
        time.sleep(timing.gap_ms() / 1000)


def run(preset: Preset, countdown: int | None) -> None:
    if countdown is None:
        countdown = preset.countdown
    node = _find_real_keyboard_node()
    print(f"Cloning capabilities from {node} ...")
    with UInput.from_device(node, name="hidguard-ducky") as ui:
        # from_device copies the source's key set; Shift and the launcher combo
        # are part of any real keyboard's capabilities, so nothing extra needed.
        time.sleep(1)  # let udev register the device and HIDGuard open a session

        for remaining in range(countdown, 0, -1):
            print(f"  focus your target window... typing in {remaining}s", end="\r", flush=True)
            time.sleep(1)
        print("\nTyping now.")

        if preset.launcher:
            _send_launcher(ui)
            time.sleep(0.5)  # let the terminal take focus before the payload
        _type_message(ui, MESSAGE, preset.timing)

        time.sleep(0.5)  # let HIDGuard's reader drain the last events
    print("Done. The virtual keyboard is gone; check HIDGuard's verdict.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--payload", choices=PRESETS, default="superhuman",
        help="which attack profile to replay (default: superhuman)",
    )
    parser.add_argument(
        "--countdown", type=int, default=None,
        help="seconds to focus the target window before typing (default: per preset)",
    )
    parser.add_argument("--list", action="store_true", help="describe the presets and exit")
    args = parser.parse_args()

    if args.list:
        for name, preset in PRESETS.items():
            print(f"{name:12} {preset.description}")
        return

    preset = PRESETS[args.payload]
    print(f"Payload: {args.payload} -- {preset.description}\n")
    run(preset, args.countdown)


if __name__ == "__main__":
    main()
