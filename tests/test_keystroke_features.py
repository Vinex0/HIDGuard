"""Unit tests for the keystroke statistics.

Everything here except the last test is a pure function over a hand-built
event list, so none of it needs a repo, a session row, or a device.
"""

from uuid import uuid4

import pytest
from evdev.ecodes import (
    EV_KEY,
    KEY_A,
    KEY_B,
    KEY_BACKSPACE,
    KEY_F2,
    KEY_LEFTALT,
    KEY_LEFTCTRL,
    KEY_LEFTMETA,
    KEY_RIGHTALT,
    KEY_RIGHTCTRL,
    KEY_T,
)

from hidguard.features import keystroke
from hidguard.features.keystroke import KEY_DOWN, KEY_REPEAT, KEY_UP
from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session

SESSION_ID = uuid4()


def event(code: int, value: int, timestamp: float) -> InputEvent:
    return InputEvent(
        session_id=SESSION_ID, type=EV_KEY, code=code, value=value, timestamp=timestamp
    )


def presses_at(*timestamps: float) -> list[InputEvent]:
    return [event(KEY_A, KEY_DOWN, timestamp) for timestamp in timestamps]


def test_dwell_pairs_overlapping_keys_by_code():
    """Keys held at the same time are paired by keycode, not by adjacency.

    Fast typing rolls one key over the next -- 'ab' arrives as a-down, b-down,
    a-up, b-up -- so pairing consecutive events would time a-down against b-down
    and report nonsense for both keys.
    """
    events = [
        event(KEY_A, KEY_DOWN, 1.00),
        event(KEY_B, KEY_DOWN, 1.02),
        event(KEY_A, KEY_UP, 1.08),  # 'a' held 80ms
        event(KEY_B, KEY_UP, 1.14),  # 'b' held 120ms
    ]

    assert keystroke.dwell_times_ms(events) == pytest.approx([80, 120])


def test_dwell_drops_release_without_a_press():
    """A release with no matching press contributes nothing.

    Routine rather than malformed: the reader attaches to an already-connected
    device, so the first thing it sees can be the release of a key that went
    down before the session existed.
    """
    events = [
        event(KEY_A, KEY_UP, 1.00),  # pressed before the session started
        event(KEY_B, KEY_DOWN, 1.10),
        event(KEY_B, KEY_UP, 1.15),
    ]

    assert keystroke.dwell_times_ms(events) == pytest.approx([50])


def test_dwell_drops_press_still_held_at_disconnect():
    """A press never released is dropped rather than timed against the end."""
    events = [
        event(KEY_A, KEY_DOWN, 1.00),
        event(KEY_A, KEY_UP, 1.05),
        event(KEY_B, KEY_DOWN, 1.10),  # still down when the device was unplugged
    ]

    assert keystroke.dwell_times_ms(events) == pytest.approx([50])


def test_dwell_excludes_autorepeating_keys():
    """A key held long enough to autorepeat is left out of the dwell stats.

    Its dwell measures how long someone leaned on the key, not how they type,
    and at a second-plus it would swamp the mean of ordinary 50-100ms holds.
    """
    events = [
        event(KEY_A, KEY_DOWN, 1.00),
        event(KEY_A, KEY_UP, 1.06),
        event(KEY_B, KEY_DOWN, 2.00),
        event(KEY_B, KEY_REPEAT, 2.50),
        event(KEY_B, KEY_REPEAT, 2.53),
        event(KEY_B, KEY_UP, 3.00),  # 1000ms hold, excluded
    ]

    assert keystroke.dwell_times_ms(events) == pytest.approx([60])


def test_dwell_counts_a_key_pressed_again_after_repeating():
    """The repeat exclusion applies per press, not for the rest of the session."""
    events = [
        event(KEY_A, KEY_DOWN, 1.00),
        event(KEY_A, KEY_REPEAT, 1.50),
        event(KEY_A, KEY_UP, 2.00),  # excluded
        event(KEY_A, KEY_DOWN, 3.00),
        event(KEY_A, KEY_UP, 3.07),  # ordinary press of the same key, kept
    ]

    assert keystroke.dwell_times_ms(events) == pytest.approx([70])


def test_max_keys_per_second_slides_across_a_second_boundary():
    """The busiest window is found wherever it falls, not per whole second.

    These six presses straddle the 1.0s mark, so fixed one-second buckets would
    split them into two unremarkable halves and report 3 instead of 6.
    """
    press_times = [0.85, 0.88, 0.91, 1.02, 1.05, 1.08]

    assert keystroke.max_keys_per_second(press_times) == 6


def test_max_keys_per_second_excludes_the_window_edge():
    """Presses exactly a second apart fall in different windows."""
    assert keystroke.max_keys_per_second([0.0, 1.0, 2.0]) == 1


def test_max_keys_per_second_of_no_presses_is_zero():
    assert keystroke.max_keys_per_second([]) == 0


def test_longest_burst_counts_keystrokes_not_gaps():
    """A run of n fast gaps is reported as n+1 keystrokes.

    Four presses 20ms apart are three sub-threshold gaps; the burst is the four
    keystrokes, which is what a rule comparing against a length threshold means.
    """
    presses = presses_at(1.00, 1.02, 1.04, 1.06)

    assert keystroke.longest_burst_length(presses) == 4


def test_longest_burst_resets_on_a_slow_gap():
    """A human-speed pause ends the burst and starts counting again."""
    presses = presses_at(
        1.00, 1.02, 1.04,  # burst of 3
        2.00,              # 960ms pause resets
        2.01, 2.02, 2.03, 2.04,  # burst of 5
    )

    assert keystroke.longest_burst_length(presses) == 5


def test_longest_burst_of_one_slow_typist_is_one():
    """Presses that are never close together still count as bursts of one."""
    assert keystroke.longest_burst_length(presses_at(1.0, 2.0, 3.0)) == 1


def test_longest_burst_of_no_presses_is_zero():
    assert keystroke.longest_burst_length([]) == 0


def test_launcher_detects_the_terminal_combo():
    """Ctrl+Alt+T is timed from the press that completes it.

    The modifiers only qualify the keystroke; what the payload actually did is
    press T, and that is the moment worth comparing against enumeration.
    """
    events = [
        event(KEY_LEFTCTRL, KEY_DOWN, 1.00),
        event(KEY_LEFTALT, KEY_DOWN, 1.01),
        event(KEY_T, KEY_DOWN, 1.50),
        event(KEY_T, KEY_UP, 1.55),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) == pytest.approx(1000, abs=1)


def test_launcher_normalises_right_hand_modifiers():
    """The same combo counts whichever Ctrl and Alt the device reports.

    Which side a modifier comes from is a property of the descriptor an injector
    happens to emit, not of what was typed, so both map onto the left-hand codes.
    """
    events = [
        event(KEY_RIGHTCTRL, KEY_DOWN, 1.00),
        event(KEY_RIGHTALT, KEY_DOWN, 1.01),
        event(KEY_T, KEY_DOWN, 1.50),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) == pytest.approx(1000, abs=1)


def test_launcher_detects_meta_pressed_alone():
    """Meta on its own opens the overview and is recognised on release.

    Nothing follows a bare modifier to complete a combo, so the hit can only be
    called once the key comes back up with nothing pressed in between. The press
    timestamp is what gets reported -- that is when the keyboard acted.
    """
    events = [
        event(KEY_LEFTMETA, KEY_DOWN, 1.00),
        event(KEY_LEFTMETA, KEY_UP, 1.20),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) == pytest.approx(500, abs=1)


def test_launcher_ignores_meta_held_as_a_modifier():
    """Meta+A is not a bare Meta, even though Meta goes down and later up.

    Window managers bind dozens of Meta combos, so counting every Meta release
    would make the feature fire on ordinary desktop use.
    """
    events = [
        event(KEY_LEFTMETA, KEY_DOWN, 1.00),
        event(KEY_A, KEY_DOWN, 1.10),
        event(KEY_A, KEY_UP, 1.15),
        event(KEY_LEFTMETA, KEY_UP, 1.20),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) is None


def test_launcher_ignores_combos_outside_the_table():
    """Ctrl+T is a browser tab, not a launcher, and Ctrl alone is nothing."""
    events = [
        event(KEY_LEFTCTRL, KEY_DOWN, 1.00),
        event(KEY_T, KEY_DOWN, 1.05),
        event(KEY_T, KEY_UP, 1.10),
        event(KEY_LEFTCTRL, KEY_UP, 1.15),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) is None


def test_launcher_reports_the_first_hit():
    """Only the earliest launcher counts.

    The feature answers how quickly the device reached for a launcher; what a
    payload opens afterwards is a different question.
    """
    events = [
        event(KEY_LEFTALT, KEY_DOWN, 1.00),
        event(KEY_F2, KEY_DOWN, 1.10),
        event(KEY_F2, KEY_UP, 1.15),
        event(KEY_LEFTALT, KEY_UP, 1.20),
        event(KEY_LEFTMETA, KEY_DOWN, 3.00),
        event(KEY_LEFTMETA, KEY_UP, 3.10),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) == pytest.approx(600, abs=1)


def test_launcher_survives_a_release_without_a_press():
    """A modifier released before the reader attached is not a bare press.

    Same mid-stream attach the dwell pairing has to tolerate: the first event of
    a session can be the release of a key that went down earlier.
    """
    events = [
        event(KEY_LEFTMETA, KEY_UP, 1.00),
        event(KEY_A, KEY_DOWN, 1.50),
    ]

    assert keystroke.launcher_hotkey_after_ms(events, 0.50) is None


def test_extract_counts_keystrokes_not_events():
    """keystroke_count counts presses; event_count counts everything.

    A rule threshold phrased in keystrokes would otherwise be halved by the
    releases, since every press brings its own release along.
    """
    events = [
        event(KEY_A, KEY_DOWN, 1.00),
        event(KEY_A, KEY_UP, 1.05),
        event(KEY_B, KEY_DOWN, 1.10),
        event(KEY_B, KEY_REPEAT, 1.60),
        event(KEY_B, KEY_UP, 2.00),
    ]

    features = keystroke.extract(events, connected_at=0.5)

    assert features["event_count"] == 5
    assert features["keystroke_count"] == 2


def test_extract_leaves_the_launcher_field_out_when_none_was_typed():
    """No launcher means an absent field, not a zero.

    Zero is a real measurement here -- a combo pressed the instant the device
    enumerated -- so it cannot double as 'nothing found'.
    """
    features = keystroke.extract(presses_at(1.0, 1.1), connected_at=0.5)

    assert "launcher_hotkey_after_ms" not in features


def test_extract_reports_the_launcher_delay():
    events = [
        event(KEY_LEFTCTRL, KEY_DOWN, 1.00),
        event(KEY_LEFTALT, KEY_DOWN, 1.01),
        event(KEY_T, KEY_DOWN, 1.50),
    ]

    features = keystroke.extract(events, connected_at=0.50)

    assert features["launcher_hotkey_after_ms"] == pytest.approx(1000, abs=1)


def test_extract_leaves_undefined_statistics_out():
    """A session with one press reports counts but no derived statistics.

    There is no gap to measure and no release to time, so those columns must
    stay absent -- and therefore NULL -- rather than being filled with zeros a
    rule would read as real measurements.
    """
    features = keystroke.extract(presses_at(5.0), connected_at=4.0)

    assert features["event_count"] == 1
    assert features["longest_burst_length"] == 1
    assert features["time_to_first_keystroke_ms"] == pytest.approx(1000)
    assert "avg_interkey_delay_ms" not in features
    assert "avg_dwell_time_ms" not in features


def test_extract_of_no_events_reports_only_counts():
    features = keystroke.extract([], connected_at=4.0)

    assert features["event_count"] == 0
    assert features["backspace_count"] == 0
    assert features["max_keys_per_second"] == 0
    assert "time_to_first_keystroke_ms" not in features


def test_extract_computes_every_statistic():
    """Three evenly spaced presses fill in the interkey, dwell and burst fields."""
    events = [
        event(KEY_A, KEY_DOWN, 1.00),
        event(KEY_A, KEY_UP, 1.04),
        event(KEY_B, KEY_DOWN, 1.10),
        event(KEY_B, KEY_UP, 1.16),
        event(KEY_BACKSPACE, KEY_DOWN, 1.20),
        event(KEY_BACKSPACE, KEY_UP, 1.25),
    ]

    features = keystroke.extract(events, connected_at=0.5)

    assert features["event_count"] == 6
    assert features["backspace_count"] == 1
    assert features["avg_interkey_delay_ms"] == pytest.approx(100, abs=1)
    assert features["min_interkey_delay_ms"] == pytest.approx(100, abs=1)
    assert features["median_interkey_delay_ms"] == pytest.approx(100, abs=1)
    assert features["avg_dwell_time_ms"] == pytest.approx(50, abs=1)
    assert features["max_keys_per_second"] == 3
    assert features["time_to_first_keystroke_ms"] == pytest.approx(500, abs=1)


def test_update_session_reads_events_and_keeps_session_fields(repo):
    """The stored events fill the feature fields without disturbing the rest.

    update_session works from the in-memory Session rather than re-reading the
    row, so disconnected_at -- set on unregister and not yet persisted -- has to
    survive into the returned copy or it is silently lost on save.
    """
    repo.save_device(Device(id="fake-device"))  # sessions.device_id is a foreign key
    session = Session.start(device_id="fake-device")
    repo.save_session(session)
    session.end()

    for offset, code in enumerate((KEY_A, KEY_B, KEY_BACKSPACE)):
        repo.save_event(
            event(code, KEY_DOWN, session.connected_at + 0.5 + offset * 0.02)
            .model_copy(update={"session_id": session.id})
        )

    updated = keystroke.update_session(repo, session)

    assert updated.id == session.id
    assert updated.disconnected_at == session.disconnected_at
    assert updated.event_count == 3
    assert updated.backspace_count == 1
    assert updated.longest_burst_length == 3
