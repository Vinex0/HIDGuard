"""Unit tests for the udev add/remove handlers.

The event reader is stubbed out, so these drive handle_add/handle_remove
without opening a real device -- no privileges needed and no timing waits.
test_integration.py covers the same code through a real /dev/uinput device.
"""

import threading

import pytest

from hidguard.collectors import udev_listener
from hidguard.collectors.session_manager import SessionManager


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
    udev_device = FakeUdevDevice("/dev/input/event5", {"ID_VENDOR_ID": "046d"})

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


def test_handle_remove_untracked_node_is_silent(capsys, repo):
    """A 'remove' for a node we never registered reports nothing.

    handle_add filters most nodes out, so udev delivers removes for devices
    that were never tracked; those must not print a session summary.
    """
    manager = SessionManager()

    udev_listener.handle_remove(FakeUdevDevice("/dev/input/js0"), manager, repo)

    assert "Session ended" not in capsys.readouterr().out
