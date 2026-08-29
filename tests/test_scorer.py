"""Unit tests for the periodic scorer.

score_active_sessions is driven against a real in-memory repo and a real
SessionManager with one registered session; the reader thread is never started,
so the events are the ones the test writes directly. run is checked only for its
stop contract -- that a set event returns it promptly.
"""

import threading
import time

from evdev.ecodes import EV_KEY, KEY_A

from hidguard.collectors.session_manager import SessionManager
from hidguard.detection import scorer
from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session


def _register_session(manager: SessionManager, repo, node="/dev/input/event5") -> Session:
    """Puts a saved session into the manager the way handle_add would.

    A dummy thread and stop event stand in for the reader: the scorer only reads
    active_sessions() and the stored events, never the thread, so nothing needs
    to run.
    """
    repo.save_device(Device(id="dev-1"))  # sessions.device_id is a foreign key
    session = Session.start(device_id="dev-1")
    repo.save_session(session)
    manager.register(node, session, threading.Thread(target=lambda: None), threading.Event())
    return session


def _write_fast_presses(repo, session: Session, count: int) -> None:
    """count key-downs 12ms apart from the session's connect time.

    Machine cadence on purpose, so the scored session comes out malicious and a
    changed verdict is easy to assert on.
    """
    for index in range(count):
        pressed_at = session.connected_at + 0.6 + index * 0.012
        for value, timestamp in ((1, pressed_at), (0, pressed_at + 0.001)):
            repo.save_event(
                InputEvent(
                    session_id=session.id,
                    type=EV_KEY,
                    code=KEY_A,
                    value=value,
                    timestamp=timestamp,
                )
            )


def test_scoring_an_active_session_writes_a_detection(repo):
    """A session with events on file gets a detection row while still open."""
    manager = SessionManager()
    session = _register_session(manager, repo)
    _write_fast_presses(repo, session, count=15)

    scorer.score_active_sessions(manager, repo)

    detection = repo.get_detection(session.id)
    assert detection is not None
    assert detection.verdict == "malicious"


def test_rescoring_updates_the_detection_rather_than_duplicating(repo):
    """A second pass over the same session updates its one row, not a new one.

    This is the whole reason the detection table is keyed by session_id: the
    scorer runs every couple of seconds and must converge on one verdict per
    session, not accumulate one per tick.
    """
    manager = SessionManager()
    session = _register_session(manager, repo)
    _write_fast_presses(repo, session, count=15)

    scorer.score_active_sessions(manager, repo)
    scorer.score_active_sessions(manager, repo)

    assert len(repo.list_detections()) == 1


def test_scoring_leaves_the_session_row_untouched(repo):
    """The scorer writes detections only, never the sessions row.

    active_sessions() hands back the live Session whose feature columns are still
    at their start defaults. Writing it would race handle_remove's authoritative
    final save and could blank a just-set disconnected_at, resurrecting a closed
    session. So the stored row must stay exactly as save_session left it.
    """
    manager = SessionManager()
    session = _register_session(manager, repo)
    _write_fast_presses(repo, session, count=15)

    scorer.score_active_sessions(manager, repo)

    stored = repo.get_session(session.id)
    assert stored.event_count == 0  # scorer never wrote the extracted features back
    assert stored.disconnected_at is None


def test_run_scores_then_stops_when_the_event_is_set(repo):
    """run keeps scoring until stopped, and returns promptly once it is.

    Started in a thread: it scores on the first pass, then waits out the
    interval on the stop event rather than sleeping, so setting the event has to
    return it well inside that interval instead of blocking it out.
    """
    manager = SessionManager()
    session = _register_session(manager, repo)
    _write_fast_presses(repo, session, count=15)
    stop_event = threading.Event()

    thread = threading.Thread(target=scorer.run, args=(manager, repo, stop_event))
    thread.start()
    try:
        deadline = time.monotonic() + 2
        while repo.get_detection(session.id) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert repo.get_detection(session.id) is not None, "run never scored the session"
    finally:
        stop_event.set()
        thread.join(timeout=2)

    assert not thread.is_alive(), "run did not return after stop_event was set"
