"""Unit tests for the evdev reader's failure handling.

Only the paths that need no readable device are covered here; reading actual
events is exercised by test_integration.py.
"""

import threading

from hidguard.collectors.event_reader import read_evdev_events
from hidguard.models.session import Session


def test_read_evdev_events_reports_unopenable_device_and_returns(capsys):
    """A device that cannot be opened is logged and skipped, not raised.

    This is the normal outcome for anyone not in the 'input' group, and for
    devices unplugged between udev's 'add' and our open(). It runs on a reader
    thread whose exception nobody would see, so it has to fail soft: print the
    reason and return, leaving the rest of the listener running.
    """
    session = Session.start(device_id="dev-1")

    read_evdev_events("/dev/input/event-does-not-exist", threading.Event(), session.id)

    output = capsys.readouterr().out
    assert "Could not open" in output
    assert "/dev/input/event-does-not-exist" in output
