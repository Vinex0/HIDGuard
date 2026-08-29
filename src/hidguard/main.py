import threading

from hidguard import dashboard
from hidguard.collectors import udev_listener
from hidguard.collectors.session_manager import SessionManager
from hidguard.collectors.udev_listener import listen
from hidguard.detection import scorer
from hidguard.detection.engine import evaluate
from hidguard.features import keystroke
from hidguard.storage.paths import get_db_path
from hidguard.storage.sqlite_repo import SqliteRepo


def _finalize(session_manager: SessionManager, repo: SqliteRepo) -> None:
    """Score and persist every still-open session, then close the database.

    Shared by both run modes: whichever way the daemon is stopped, each live
    session gets its authoritative final row before shutdown.
    """
    for session in session_manager.unregister_all():
        session = keystroke.update_session(repo, session)
        repo.save_session(session)
        repo.save_detection(evaluate(session))
    repo.close()


def run(limit: int = dashboard.DEFAULT_LIMIT, interval: float = dashboard.REFRESH_INTERVAL_S) -> None:
    """Start the daemon and the live dashboard together in this terminal.

    The udev listener and the periodic scorer run in background threads while the
    dashboard owns the screen; the listener's status prints are silenced so they
    don't tear the live view. This is the single-command demo: one terminal shows
    verdicts landing as sessions come and go.
    """
    session_manager = SessionManager()
    repo = SqliteRepo(get_db_path())
    stop_event = threading.Event()

    udev_listener.VERBOSE = False  # the dashboard is the UI now
    threading.Thread(
        target=scorer.run, args=(session_manager, repo, stop_event), daemon=True
    ).start()
    threading.Thread(target=listen, args=(session_manager, repo), daemon=True).start()

    try:
        dashboard.run(get_db_path(), limit, interval)  # blocks until Ctrl+C
    finally:
        stop_event.set()
        _finalize(session_manager, repo)


def run_headless() -> None:
    """Run the daemon alone, printing status to the terminal (no dashboard)."""
    session_manager = SessionManager()
    repo = SqliteRepo(get_db_path())
    stop_event = threading.Event()

    threading.Thread(
        target=scorer.run, args=(session_manager, repo, stop_event), daemon=True
    ).start()

    try:
        listen(session_manager, repo)
    except KeyboardInterrupt:
        print("\nStopped listening.")
    finally:
        stop_event.set()
        _finalize(session_manager, repo)


def main():
    run()


if __name__ == '__main__':
    main()
