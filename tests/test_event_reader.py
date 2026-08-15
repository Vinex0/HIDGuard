"""Unit tests for the evdev reader's failure handling.

Only the paths that need no readable device are covered here; reading actual
events is exercised by test_integration.py.
"""

import threading

from hidguard.collectors import event_reader
from hidguard.collectors.event_reader import read_evdev_events
from hidguard.models.device_model import Device
from hidguard.models.session import Session


class FakeEvdevEvent:
    """Minimal stand-in for evdev.InputEvent."""
    def __init__(self, type_, code, value, ts=1234.5):
        self.type = type_
        self.code = code
        self.value = value
        self._ts = ts

    def timestamp(self):
        return self._ts


class FakeInputDevice:
    """Minimal stand-in for evdev.InputDevice, replaying a fixed event list."""
    def __init__(self, events):
        self.name = "fake-keyboard"
        self._events = events

    def read_loop(self):
        yield from self._events

    def close(self):
        pass


def test_read_evdev_events_filters_to_ev_key(monkeypatch, repo):
    """Only EV_KEY events are persisted.

    EV_SYN and EV_MSC events share the exact timestamp of the keypress they
    accompany; storing them would corrupt every delay stat feature extraction
    computes from consecutive event gaps, for no benefit since nothing ever
    reads them back.
    """
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)  # input_events.session_id is a foreign key
    events = [
        FakeEvdevEvent(type_=4, code=4, value=30),  # EV_MSC scancode
        FakeEvdevEvent(type_=1, code=30, value=1),  # EV_KEY press
        FakeEvdevEvent(type_=0, code=0, value=0),  # EV_SYN
    ]
    monkeypatch.setattr(event_reader, "InputDevice", lambda node: FakeInputDevice(events))

    read_evdev_events("/dev/input/event5", threading.Event(), session.id, repo)

    rows = repo._conn.execute(
        "SELECT type FROM input_events WHERE session_id = ?", (str(session.id),)
    ).fetchall()
    assert [row[0] for row in rows] == [1]


def test_read_evdev_events_reports_unopenable_device_and_returns(capsys, repo):
    """A device that cannot be opened is logged and skipped, not raised.

    This is the normal outcome for anyone not in the 'input' group, and for
    devices unplugged between udev's 'add' and our open(). It runs on a reader
    thread whose exception nobody would see, so it has to fail soft: print the
    reason and return, leaving the rest of the listener running.
    """
    session = Session.start(device_id="dev-1")

    read_evdev_events(
        "/dev/input/event-does-not-exist", threading.Event(), session.id, repo
    )

    output = capsys.readouterr().out
    assert "Could not open" in output
    assert "/dev/input/event-does-not-exist" in output
