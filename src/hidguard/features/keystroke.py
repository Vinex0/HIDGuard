"""Keystroke-dynamics features derived from a session's raw input events.

Only update_session touches storage; everything below it is pure -- lists of
events in, numbers out -- so the statistics can be tested without a database.
"""

from itertools import pairwise
from statistics import fmean, median, pstdev

from evdev.ecodes import (
    KEY_BACKSPACE,
    KEY_F2,
    KEY_LEFTALT,
    KEY_LEFTCTRL,
    KEY_LEFTMETA,
    KEY_LEFTSHIFT,
    KEY_RIGHTALT,
    KEY_RIGHTCTRL,
    KEY_RIGHTMETA,
    KEY_RIGHTSHIFT,
    KEY_T,
)

from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session
from hidguard.storage.sqlite_repo import SqliteRepo

# evdev names the key codes but not the values an EV_KEY event carries.
KEY_UP, KEY_DOWN, KEY_REPEAT = 0, 1, 2

# Gap below which two presses count as part of the same burst. Sustained human
# typing rarely stays under this; injection tools emit at a fixed 10-30ms.
BURST_MAX_GAP_MS = 50.0

# Width of the window max_keys_per_second slides over the press timestamps.
BURST_WINDOW_S = 1.0

# Which side of the keyboard a modifier came from says nothing about intent, and
# an injector picks a side by whatever its descriptor happens to emit.
MODIFIER_ALIASES = {
    KEY_RIGHTCTRL: KEY_LEFTCTRL,
    KEY_RIGHTALT: KEY_LEFTALT,
    KEY_RIGHTMETA: KEY_LEFTMETA,
    KEY_RIGHTSHIFT: KEY_LEFTSHIFT,
}

# Held rather than typed, so these never complete a combo by themselves.
MODIFIERS = frozenset({KEY_LEFTCTRL, KEY_LEFTALT, KEY_LEFTMETA, KEY_LEFTSHIFT})

# The first move of practically every injection payload: open a terminal or a
# run dialog. Written in normalised (left-hand) codes.
LAUNCHER_COMBOS = frozenset(
    {
        frozenset({KEY_LEFTMETA}),  # GNOME/KDE overview
        frozenset({KEY_LEFTCTRL, KEY_LEFTALT, KEY_T}),  # terminal
        frozenset({KEY_LEFTALT, KEY_F2}),  # run dialog
    }
)


def update_session(repo: SqliteRepo, session: Session) -> Session:
    """Returns the session with its feature columns filled in from stored events.

    The caller saves the result; this is the one seam that reads storage.
    """
    events = repo.get_events_for_session(session.id)
    return session.model_copy(update=extract(events, session.connected_at))


def extract(events: list[InputEvent], connected_at: float) -> dict:
    """Feature values for one session's events, keyed by Session field name.

    Statistics with no data to compute from are left out rather than zeroed,
    so their columns stay NULL and a rule can tell 'no keystrokes' apart from
    'keystrokes that happened to average zero'.
    """
    presses = [event for event in events if event.value == KEY_DOWN]
    delays_ms = [(b.timestamp - a.timestamp) * 1000 for a, b in pairwise(presses)]
    dwells_ms = dwell_times_ms(events)
    launcher_ms = launcher_hotkey_after_ms(events, connected_at)

    # float rather than int|float: the counts widen harmlessly, and declaring the
    # union would make every later statistic an assignment error.
    features: dict[str, float] = {
        "event_count": len(events),
        "keystroke_count": len(presses),
        "backspace_count": sum(1 for event in presses if event.code == KEY_BACKSPACE),
        "max_keys_per_second": max_keys_per_second([press.timestamp for press in presses]),
        "longest_burst_length": longest_burst_length(presses),
    }

    if presses:
        features["time_to_first_keystroke_ms"] = (presses[0].timestamp - connected_at) * 1000

    # Explicitly against None, not truthiness: a combo pressed the instant the
    # device enumerated measures zero, and that is the most damning value there is.
    if launcher_ms is not None:
        features["launcher_hotkey_after_ms"] = launcher_ms

    if delays_ms:
        features |= {
            "avg_interkey_delay_ms": fmean(delays_ms),
            "std_interkey_delay_ms": pstdev(delays_ms),
            "min_interkey_delay_ms": min(delays_ms),
            "max_interkey_delay_ms": max(delays_ms),
            "median_interkey_delay_ms": median(delays_ms),
        }

    if dwells_ms:
        features |= {
            "avg_dwell_time_ms": fmean(dwells_ms),
            "std_dwell_time_ms": pstdev(dwells_ms),
        }

    return features


def dwell_times_ms(events: list[InputEvent]) -> list[float]:
    """How long each key was held, pairing every press with its own release.

    Adjacent events can't be paired directly, because fast typing overlaps
    keys: 'he' commonly arrives as h-down, e-down, h-up, e-up. Presses are
    tracked per keycode instead, and anything left unmatched is dropped rather
    than guessed at -- a release with no press is routine, since the reader
    attaches mid-stream and sees the tail of whatever was already held down.

    Keys that autorepeat are excluded. Their dwell measures how long someone
    leaned on a key rather than how they type, and one of them is long enough
    to move the mean by an order of magnitude.
    """
    pressed_at: dict[int, float] = {}
    repeating: set[int] = set()
    dwells: list[float] = []

    for event in events:
        if event.value == KEY_DOWN:
            pressed_at[event.code] = event.timestamp
            repeating.discard(event.code)
        elif event.value == KEY_REPEAT:
            repeating.add(event.code)
        elif event.value == KEY_UP:
            press_time = pressed_at.pop(event.code, None)
            if press_time is not None and event.code not in repeating:
                dwells.append((event.timestamp - press_time) * 1000)
            repeating.discard(event.code)

    return dwells


def max_keys_per_second(press_times: list[float]) -> int:
    """Most presses falling within any one-second window.

    Slides the window rather than bucketing into fixed seconds: a flurry of
    twenty keystrokes straddling a bucket boundary would otherwise read as two
    unremarkable halves.
    """
    busiest = 0
    window_start = 0

    for index, timestamp in enumerate(press_times):
        while timestamp - press_times[window_start] >= BURST_WINDOW_S:
            window_start += 1
        busiest = max(busiest, index - window_start + 1)

    return busiest


def longest_burst_length(presses: list[InputEvent]) -> int:
    """Longest unbroken run of presses typed faster than BURST_MAX_GAP_MS.

    Counted in keystrokes rather than gaps, so a run of n fast gaps is n+1
    presses and a lone keystroke is a burst of one.
    """
    longest = current = 0
    previous_timestamp = None

    for press in presses:
        gap_ms = (
            None if previous_timestamp is None else (press.timestamp - previous_timestamp) * 1000
        )
        current= current + 1 if gap_ms is not None and gap_ms <= BURST_MAX_GAP_MS else 1
        previous_timestamp = press.timestamp
        longest = max(longest, current)

    return longest


def launcher_hotkey_after_ms(events: list[InputEvent], connected_at: float) -> float | None:
    """Time from enumeration to the first launcher hotkey, or None if none was typed.

    A combo is the set of modifiers held when a normal key goes down, which is
    why the modifiers themselves are tracked rather than the event order: an
    injector releases Ctrl and Alt in whatever order its report layout implies.

    Modifiers pressed alone are the awkward case, since nothing follows them to
    complete a combo. They are recognised on release instead, and only while
    nothing else was pressed in between -- Meta alone opens the overview, but
    the Meta of Meta+A is a modifier and must not count. The press timestamp is
    reported for those, since that is when the keyboard acted.

    Only the first hit is reported; what a payload does after opening its
    terminal is a different question than how fast it got there.
    """
    held: set[int] = set()
    solo: tuple[int, float] | None = None  # a modifier held with nothing else down

    for event in events:
        code = MODIFIER_ALIASES.get(event.code, event.code)
        is_modifier = code in MODIFIERS

        if event.value == KEY_DOWN:
            solo = (code, event.timestamp) if is_modifier and not held else None
            if is_modifier:
                held.add(code)
            elif frozenset(held | {code}) in LAUNCHER_COMBOS:
                return (event.timestamp - connected_at) * 1000

        elif event.value == KEY_UP and is_modifier:
            held.discard(code)
            if solo is not None and solo[0] == code:
                if frozenset({code}) in LAUNCHER_COMBOS:
                    return (solo[1] - connected_at) * 1000
                solo = None

    return None
