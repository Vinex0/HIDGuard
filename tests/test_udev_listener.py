"""Unit tests for the udev add/remove handlers.

The event reader is stubbed out, so these drive handle_add/handle_remove
without opening a real device -- no privileges needed and no timing waits.
test_integration.py covers the same code through a real /dev/uinput device.
"""

import threading

import pytest
from evdev.ecodes import EV_KEY, KEY_A, KEY_B, KEY_BACKSPACE, KEY_C

from hidguard.collectors import udev_listener
from hidguard.collectors.session_manager import SessionManager
from hidguard.models.input_event import InputEvent


class FakeUdevDevice:
    """Minimal stand-in for pyudev.Device, as the handlers use it."""

    def __init__(self, device_node, properties=None, sys_path="/sys/fake/path"):
        self.device_node = device_node
        self.properties = properties or {}
        self.sys_path = sys_path


@pytest.fixture
def stub_reader(monkeypatch):
    """Swaps read_evdev_events for a recorder, so no device is ever opened.

    Returns (calls, started): the args each call received, and an Event set
    once the reader thread has actually run, to wait on instead of sleeping.
    """
    calls = []
    started = threading.Event()

    def fake_read(device_node, stop_event, session_id, repo):
        calls.append((device_node, stop_event, session_id))
        started.set()

    monkeypatch.setattr(udev_listener, "read_evdev_events", fake_read)
    return calls, started


def test_handle_add_registers_session_and_starts_reader(stub_reader, repo):
    """An 'add' for an event node opens a session and hands it to a reader.

    The session id the reader receives must be the one registered for that
    node, since that is what tags every event it goes on to read.
    """
    calls, started = stub_reader
    manager = SessionManager()
    udev_device = FakeUdevDevice(
        "/dev/input/event5", {"ID_VENDOR_ID": "046d", "ID_INPUT_KEYBOARD": "1"}
    )

    udev_listener.handle_add(udev_device, manager, repo)

    assert started.wait(timeout=2), "reader thread did not run"
    node, _stop_event, session_id = calls[0]
    assert node == "/dev/input/event5"
    assert session_id == manager.session_id_for("/dev/input/event5")


@pytest.mark.parametrize(
    "node",
    [None, "/dev/input/js0"],
    ids=["no-node", "joystick-node"],
)
def test_handle_add_ignores_non_event_nodes(stub_reader, repo, node):
    """Devices without an event node are skipped entirely.

    udev announces several nodes per physical device (js0 for joysticks, and
    parent devices with no node at all); only the evdev ones are readable, so
    the others must not open a session or spawn a thread.
    """
    calls, started = stub_reader
    manager = SessionManager()

    udev_listener.handle_add(FakeUdevDevice(node), manager, repo)

    assert calls == []
    assert not started.is_set()
    assert manager.session_id_for(node) is None


def test_handle_add_ignores_non_keyboard_devices(stub_reader, repo):
    """Mice, touchpads, and a keyboard's own non-keyboard event nodes are skipped.

    A single physical keyboard announces several /dev/input/eventN nodes, only
    one of which is tagged ID_INPUT_KEYBOARD; without this filter every one of
    them (plus every mouse) opens its own empty session.
    """
    calls, started = stub_reader
    manager = SessionManager()
    udev_device = FakeUdevDevice("/dev/input/event6", {"ID_INPUT_MOUSE": "1"})

    udev_listener.handle_add(udev_device, manager, repo)

    assert calls == []
    assert not started.is_set()
    assert manager.session_id_for("/dev/input/event6") is None


def test_handle_remove_untracked_node_is_silent(capsys, repo):
    """A 'remove' for a node we never registered reports nothing.

    handle_add filters most nodes out, so udev delivers removes for devices
    that were never tracked; those must not print a session summary.
    """
    manager = SessionManager()

    udev_listener.handle_remove(FakeUdevDevice("/dev/input/js0"), manager, repo)

    assert "Session ended" not in capsys.readouterr().out


def test_handle_remove_persists_features(stub_reader, repo):
    """Ending a session writes the extracted features back to its row.

    The reader stores events as they arrive but never touches the session row,
    so the aggregates only exist once handle_remove runs the extraction; a
    session that disconnects without this stays permanently unscored.
    """
    manager = SessionManager()
    udev_listener.handle_add(
        FakeUdevDevice("/dev/input/event5", {"ID_INPUT_KEYBOARD": "1"}), manager, repo
    )
    session_id = manager.session_id_for("/dev/input/event5")
    assert session_id is not None, "handle_add did not register a session"
    connected_at = repo.get_session(session_id).connected_at

    # four key-downs 100ms apart, each held 40ms: spaced far enough apart to
    # give the interkey stats something to work with and to stay out of a burst
    for offset, code in enumerate((KEY_A, KEY_B, KEY_C, KEY_BACKSPACE)):
        pressed_at = connected_at + 0.5 + offset * 0.1
        for value, timestamp in ((1, pressed_at), (0, pressed_at + 0.04)):
            repo.save_event(
                InputEvent(
                    session_id=session_id,
                    type=EV_KEY,
                    code=code,
                    value=value,
                    timestamp=timestamp,
                )
            )

    udev_listener.handle_remove(FakeUdevDevice("/dev/input/event5"), manager, repo)

    stored = repo.get_session(session_id)
    assert stored.event_count == 8
    assert stored.backspace_count == 1
    assert stored.avg_interkey_delay_ms == pytest.approx(100, abs=1)
    assert stored.time_to_first_keystroke_ms == pytest.approx(500, abs=1)
    assert stored.avg_dwell_time_ms == pytest.approx(40, abs=1)
    assert stored.std_dwell_time_ms == pytest.approx(0, abs=1)
    assert stored.max_keys_per_second == 4  # all four presses fall in one second
    assert stored.longest_burst_length == 1  # 100ms gaps are too slow to chain
