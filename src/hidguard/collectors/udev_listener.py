import threading

import pyudev

from hidguard.collectors.event_reader import read_evdev_events
from hidguard.collectors.session_manager import SessionManager
from hidguard.models.device_model import Device
from hidguard.models.session import Session
from hidguard.storage.sqlite_repo import SqliteRepo


def handle_add(udev_device, session_manager: SessionManager, repo: SqliteRepo) -> None:
    node = udev_device.device_node
    if not node or 'event' not in node:
        return  # skip non-event nodes (e.g. js0 joystick nodes, etc.)

    device = Device.from_udev(udev_device)
    repo.save_device(device)

    session = Session.start(device_id=device.id)
    repo.save_session(session)

    print(f"New device: {device}")
    print(f"Session started: {session}")

    stop_event = threading.Event()
    thread = threading.Thread(
        target=read_evdev_events,
        args=(node, stop_event, session.id, repo),
        daemon=True,
    )
    session_manager.register(node, session, thread, stop_event)
    thread.start()


def handle_remove(udev_device, session_manager: SessionManager, repo: SqliteRepo) -> None:
    node = udev_device.device_node
    session = session_manager.unregister(node)
    if session:
        repo.save_session(session)
        print(f"Session ended: {session.id}")


def listen(session_manager: SessionManager, repo: SqliteRepo) -> None:
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='input')

    print("Listening for input device connections... (Ctrl+C to stop)\n")

    try:
        for udev_device in iter(monitor.poll, None):
            if udev_device.action == 'add':
                handle_add(udev_device, session_manager, repo)
            elif udev_device.action == 'remove':
                handle_remove(udev_device, session_manager, repo)
    except KeyboardInterrupt:
        print("\nStopped listening.")