from hidguard.collectors.session_manager import SessionManager
from hidguard.collectors.udev_listener import listen


def main():
    session_manager = SessionManager()
    listen(session_manager)


if __name__ == '__main__':
    main()