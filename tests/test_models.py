"""Unit tests for the pydantic models and their constructors.

These use hand-rolled fakes instead of real pyudev/evdev objects, so they
need no device access and run anywhere.
"""

from uuid import UUID

import pytest
from pydantic import ValidationError

from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session


class FakeUdevDevice:
    """Minimal stand-in for pyudev.Device."""
    def __init__(self, properties: dict, sys_path: str = "/sys/fake/path"):
        self.properties = properties
        self.sys_path = sys_path


class FakeEvdevEvent:
    """Minimal stand-in for evdev.InputEvent."""
    def __init__(self, type_, code, value, ts=1234.5):
        self.type = type_
        self.code = code
        self.value = value
        self._ts = ts

    def timestamp(self):
        return self._ts


def test_device_from_udev_builds_composite_id():
    """A fully-populated udev device yields the id 'vendor:model:serial'.

    Also checks that the human-readable ID_VENDOR property is carried over
    into vendor_name, separately from the vendor_id used to build the id.
    """
    udev_device = FakeUdevDevice({
        "ID_VENDOR_ID": "046d",
        "ID_MODEL_ID": "c31c",
        "ID_VENDOR": "Logitech",
        "ID_MODEL": "Keyboard",
        "ID_SERIAL": "abc123",
    })

    device = Device.from_udev(udev_device)

    assert device.id == "046d:c31c:abc123"
    assert device.vendor_name == "Logitech"


def test_device_from_udev_falls_back_to_sys_path_without_serial():
    """Devices reporting no serial fall back to sys_path for the id.

    Missing properties are dropped rather than left as empty segments, so a
    device with only a vendor id produces 'vendor:sys_path' and not
    'vendor::sys_path'. This keeps the id stable and non-colliding for the
    many input devices that expose no ID_SERIAL.
    """
    udev_device = FakeUdevDevice({"ID_VENDOR_ID": "046d"}, sys_path="/sys/fake/path")

    device = Device.from_udev(udev_device)

    assert device.id == "046d:/sys/fake/path"


def test_session_start_sets_connected_at_and_no_disconnected_at():
    """Session.start() produces an open session: stamped, with a fresh UUID.

    disconnected_at must be None so an in-progress session is distinguishable
    from a finished one.
    """
    session = Session.start(device_id="046d:c31c:abc123")

    assert isinstance(session.id, UUID)
    assert session.connected_at > 0
    assert session.disconnected_at is None


def test_session_end_sets_disconnected_at():
    """end() closes the session with a timestamp at or after connected_at.

    The ordering guarantee is what makes the duration reported on disconnect
    non-negative.
    """
    session = Session.start(device_id="dev-1")

    session.end()

    assert session.disconnected_at is not None
    assert session.disconnected_at >= session.connected_at


def test_input_event_from_evdev():
    """A raw evdev event is copied field-for-field and tagged with its session.

    Covers the one field that is not a plain attribute copy: timestamp comes
    from calling event.timestamp(), not from reading an attribute.
    """
    session = Session.start(device_id="dev-1")
    event = FakeEvdevEvent(type_=1, code=30, value=1)

    input_event = InputEvent.from_evdev(event, session.id)

    assert input_event.session_id == session.id
    assert input_event.type == 1
    assert input_event.code == 30
    assert input_event.value == 1
    assert input_event.timestamp == 1234.5


def test_input_event_from_evdev_invalid_raises():
    """Uncoercible fields raise ValidationError rather than building a bad event.

    Both a non-integer event type and a non-UUID session id are passed, so this
    asserts only that the model rejects the pair; it does not pin down which
    field failed. read_evdev_events() relies on this raising so it can log and
    skip the malformed event instead of recording it.
    """
    event = FakeEvdevEvent(type_="not-an-int", code=30, value=1)

    with pytest.raises(ValidationError):
        InputEvent.from_evdev(event, "not-a-uuid")