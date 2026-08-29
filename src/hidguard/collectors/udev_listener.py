import threading

import pyudev

from hidguard.collectors.event_reader import read_evdev_events
from hidguard.collectors.session_manager import SessionManager
from hidguard.detection.engine import evaluate
from hidguard.errors import DaemonError
from hidguard.features import keystroke
from hidguard.models.device_model import Device
from hidguard.models.session import Session
from hidguard.storage.sqlite_repo import SqliteRepo

# The daemon's status lines. Silenced by the combined dashboard mode, which owns
# the terminal with a live view and would be corrupted by stray prints.
VERBOSE = True


def _log(*args: object) -> None:
    """Prints a status line unless the dashboard has claimed the terminal."""
    if VERBOSE:
        print(*args)


def handle_add(udev_device, session_manager: SessionManager, repo: SqliteRepo) -> None:
    """Starts a session and a reader thread for a newly plugged-in keyboard.

    udev announces one event node per capability a device exposes, so most of
    what arrives here is not a keyboard at all and is filtered out below.
    """
    node = udev_device.device_node
    if not node or "event" not in node:
        return  # skip non-event nodes (e.g. js0 joystick nodes, etc.)

    if udev_device.properties.get("ID_INPUT_KEYBOARD") != "1":
        return  # skip mice, touchpads, and the non-keyboard event nodes a keyboard also exposes

    device = Device.from_udev(udev_device)
    repo.save_device(device)

    session = Session.start(device_id=device.id)
    repo.save_session(session)

    _log(f"New device: {device}")
    _log(f"Session started: {session}")

    stop_event = threading.Event()
    thread = threading.Thread(
        target=read_evdev_events,
        args=(node, stop_event, session.id, repo),
        daemon=True,
    )
    session_manager.register(node, session, thread, stop_event)
    thread.start()


def handle_remove(udev_device, session_manager: SessionManager, repo: SqliteRepo) -> None:
    """Ends the session for an unplugged device and writes its final verdict.

    Does nothing for nodes no session was ever opened for, which is every
    removal whose matching 'add' the keyboard filter rejected.
    """
    node = udev_device.device_node
    session = session_manager.unregister(node)
    if session:
        session = keystroke.update_session(repo, session)
        repo.save_session(session)
        detection = evaluate(session)
        repo.save_detection(detection)
        _log(f"Session ended: {session.id}")
        _log(f"Verdict: {detection.verdict} (score {detection.score})")
        for hit in detection.hits:
            _log(f"  - {hit.rule}: {hit.reason}")


def listen(session_manager: SessionManager, repo: SqliteRepo) -> None:
    """Opens and closes a session for every keyboard as udev announces it.

    Blocks until interrupted. Setting up the netlink monitor is the one step
    that fails outright without privileges, so it is reported as a DaemonError
    the CLI prints as a single line; everything after it concerns one device and
    is handled where it happens.
    """
    try:
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="input")
    except OSError as error:
        raise DaemonError(
            f"Could not subscribe to udev device events: {error}. "
            "Watching input devices needs root -- try 'sudo .venv/bin/hidguard'."
        ) from error

    _log("Listening for input device connections... (Ctrl+C to stop)\n")

    for udev_device in iter(monitor.poll, None):
        if udev_device.action == "add":
            handle_add(udev_device, session_manager, repo)
        elif udev_device.action == "remove":
            handle_remove(udev_device, session_manager, repo)
