from hidguard.collectors.session_manager import SessionManager
from hidguard.collectors.udev_listener import listen
from hidguard.features import keystroke
from hidguard.storage.paths import get_db_path
from hidguard.storage.sqlite_repo import SqliteRepo


def main():
    session_manager = SessionManager()
    db_path = get_db_path()
    repo = SqliteRepo(db_path)

    try:
        listen(session_manager, repo)
    except KeyboardInterrupt:
        print("\nStopped listening.")
        for session in session_manager.unregister_all():
            repo.save_session(keystroke.update_session(repo, session))
        repo.close()


if __name__ == '__main__':
    main()