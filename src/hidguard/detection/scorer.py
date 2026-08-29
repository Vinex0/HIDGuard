"""Periodic re-scoring of open sessions, so an attack shows up mid-session.

handle_remove already scores a session once, when its device is unplugged. That
is too late to be interesting: a payload finishes typing in well under a second
and the verdict only appears when the attacker pulls the device. This loop runs
in a daemon thread and re-evaluates every open session on a fixed interval, so
the detection lands while the session is still live.

It writes only the detections table, never sessions -- see score_active_sessions
for why that separation matters.
"""

import threading

from hidguard.collectors.session_manager import SessionManager
from hidguard.detection.engine import evaluate
from hidguard.features import keystroke
from hidguard.storage.sqlite_repo import SqliteRepo

# How often open sessions are re-scored. Short enough that a verdict appears
# while someone is still watching the device type, long enough not to re-read
# every session's events in a tight spin.
SCORE_INTERVAL_S = 2.0


def score_active_sessions(session_manager: SessionManager, repo: SqliteRepo) -> None:
    """Re-evaluate every open session once, updating its detection row.

    Deliberately does not write the sessions table. active_sessions() hands back
    the live in-memory Session, whose feature columns are still at their start
    defaults; saving it would race handle_remove, whose final write is the one
    authoritative record of the session, and could resurrect a just-closed
    session by blanking its disconnected_at. update_session returns a scored
    copy from the stored events without touching that row, and only the
    detections upsert is persisted.
    """
    for session in session_manager.active_sessions():
        scored = keystroke.update_session(repo, session)
        repo.save_detection(evaluate(scored))


def run(
    session_manager: SessionManager, repo: SqliteRepo, stop_event: threading.Event
) -> None:
    """Score open sessions every SCORE_INTERVAL_S until stop_event is set.

    Waits on the event rather than sleeping, so shutdown is immediate instead of
    blocking out the rest of the current interval.
    """
    while not stop_event.is_set():
        score_active_sessions(session_manager, repo)
        stop_event.wait(SCORE_INTERVAL_S)
