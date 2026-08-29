import threading

from hidguard.collectors.session_manager import SessionManager
from hidguard.collectors.udev_listener import listen
from hidguard.detection import scorer
from hidguard.detection.engine import evaluate
from hidguard.features import keystroke
from hidguard.storage.paths import get_db_path
from hidguard.storage.sqlite_repo import SqliteRepo


def main():
    session_manager = SessionManager()
    db_path = get_db_path()
    repo = SqliteRepo(db_path)

    stop_event = threading.Event()
    scorer_thread = threading.Thread(
        target=scorer.run,
        args=(session_manager, repo, stop_event),
        daemon=True,
    )
    scorer_thread.start()

    try:
        listen(session_manager, repo)
    except KeyboardInterrupt:
        print("\nStopped listening.")
    finally:
        stop_event.set()
        for session in session_manager.unregister_all():
            session = keystroke.update_session(repo, session)
            repo.save_session(session)
            repo.save_detection(evaluate(session))
        repo.close()


if __name__ == '__main__':
    main()
