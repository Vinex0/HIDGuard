from hidguard.collectors.session_manager import SessionManager
from hidguard.collectors.udev_listener import listen
from hidguard.storage.paths import get_db_path
from hidguard.storage.sqlite_repo import SqliteRepo


def main():
    session_manager = SessionManager()
    db_path = get_db_path()
    repo = SqliteRepo(db_path)
    listen(session_manager, repo)


if __name__ == '__main__':
    main()