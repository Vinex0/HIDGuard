import threading
import time

import pytest
from evdev import UInput
from evdev import ecodes as e

from hidguard.collectors.session_manager import SessionManager
from hidguard.collectors.udev_listener import listen


@pytest.mark.integration
def test_virtual_keyboard_triggers_add_and_remove(capsys):
    """End-to-end check of the udev -> session -> event-reader pipeline.

    Creates a real virtual keyboard via /dev/uinput and asserts the listener
    reacts to the full device lifecycle: the kernel's 'add' event opens a
    session and starts a reader thread, and destroying the device on context
    exit fires 'remove', which ends that session. Unlike the other tests this
    exercises the actual pyudev monitor and evdev reader rather than fakes.

    Requires write access to /dev/uinput. Deselected by default (see addopts in
    pyproject.toml); run explicitly as root:

        sudo .venv/bin/python -m pytest -m integration

    Timing-sensitive: the sleeps below are fixed waits for udev to deliver
    events, so this can flake on a loaded machine.
    """
    session_manager = SessionManager()

    listener_thread = threading.Thread(
        target=listen, args=(session_manager,), daemon=True
    )
    listener_thread.start()
    time.sleep(0.5)  # give the udev monitor time to start polling

    capabilities = {e.EV_KEY: [e.KEY_A, e.KEY_ENTER]}
    with UInput(capabilities, name="hidguard-test-keyboard") as virtual_kb:
        time.sleep(1)  # give udev time to register the new device

        # simulate typing 'a' then Enter
        virtual_kb.write(e.EV_KEY, e.KEY_A, 1)
        virtual_kb.write(e.EV_KEY, e.KEY_A, 0)
        virtual_kb.syn()
        virtual_kb.write(e.EV_KEY, e.KEY_ENTER, 1)
        virtual_kb.write(e.EV_KEY, e.KEY_ENTER, 0)
        virtual_kb.syn()

        time.sleep(0.5)  # give the reader thread time to process events

    # UInput context exit removes the device -> triggers 'remove' event
    time.sleep(0.5)

    output = capsys.readouterr().out
    assert "New device" in output
    assert "Session started" in output
    assert "Session ended" in output