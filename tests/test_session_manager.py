"""Unit tests for SessionManager's bookkeeping of device nodes.

The threads here are never started -- SessionManager only stores them and
sets their stop event, so a dummy Thread is enough to exercise it without
any real device or background work.
"""

import threading

from hidguard.collectors.session_manager import SessionManager
from hidguard.models.session import Session


def test_register_and_unregister_stops_thread_and_ends_session():
    """Unregistering a tracked node signals its reader and closes its session.

    This is the unplug path: it must both set the stop event, so the reader
    thread leaves its read loop, and stamp disconnected_at on the session it
    returns to the caller for reporting.
    """
    manager = SessionManager()
    session = Session.start(device_id="dev-1")
    stop_event = threading.Event()
    thread = threading.Thread(target=lambda: None)

    manager.register("/dev/input/event5", session, thread, stop_event)
    ended_session = manager.unregister("/dev/input/event5")

    assert stop_event.is_set()
    assert ended_session is session
    assert ended_session.disconnected_at is not None


def test_register_same_node_twice_closes_out_the_previous_session():
    """Re-registering a node retires the registration it replaces.

    Device nodes get reused: unplug/replug fast enough and a new device lands
    on the same /dev/input/eventN, and udev can announce an add for a node
    already tracked. Without this, the previous reader thread would be stranded
    with its stop event never set -- still running against a stale node -- and
    its session dropped without a disconnected_at.
    """
    manager = SessionManager()
    first_session = Session.start(device_id="dev-1")
    first_stop_event = threading.Event()

    manager.register(
        "/dev/input/event5",
        first_session,
        threading.Thread(target=lambda: None),
        first_stop_event,
    )
    second_session = Session.start(device_id="dev-2")
    manager.register(
        "/dev/input/event5",
        second_session,
        threading.Thread(target=lambda: None),
        threading.Event(),
    )

    assert first_stop_event.is_set(), "previous reader was never told to stop"
    assert first_session.disconnected_at is not None, "previous session never ended"
    # Retiring the old registration must not take the new one with it.
    assert manager.session_id_for("/dev/input/event5") == second_session.id


def test_unregister_unknown_node_returns_none():
    """Unregistering an untracked node returns None instead of raising.

    udev emits 'remove' for nodes we never registered (non-event nodes are
    filtered out on add), so handle_remove() calls this routinely and uses the
    None to decide not to print a session summary.
    """
    manager = SessionManager()

    result = manager.unregister("/dev/input/event99")

    assert result is None


def test_unregister_all_stops_every_thread_and_ends_every_session():
    """Shutdown drains the whole registry at once, not node by node.

    Every reader thread must be told to stop and every open session must get
    a disconnected_at, so nothing is left dangling when the process exits.
    """
    manager = SessionManager()
    sessions = {}
    stop_events = {}
    for i, node in enumerate(["/dev/input/event5", "/dev/input/event6"]):
        session = Session.start(device_id=f"dev-{i}")
        stop_event = threading.Event()
        manager.register(node, session, threading.Thread(target=lambda: None), stop_event)
        sessions[node] = session
        stop_events[node] = stop_event

    ended = manager.unregister_all()

    assert {s.id for s in ended} == {s.id for s in sessions.values()}
    assert all(stop_event.is_set() for stop_event in stop_events.values())
    assert all(session.disconnected_at is not None for session in ended)
    assert manager.active_sessions() == []


def test_unregister_all_on_empty_manager_returns_empty_list():
    assert SessionManager().unregister_all() == []


def test_session_id_for_known_node():
    """A registered node maps back to its session id.

    This is the lookup that lets events read off a device node be tagged with
    the session they belong to.
    """
    manager = SessionManager()
    session = Session.start(device_id="dev-1")
    stop_event = threading.Event()
    thread = threading.Thread(target=lambda: None)
    manager.register("/dev/input/event5", session, thread, stop_event)

    assert manager.session_id_for("/dev/input/event5") == session.id