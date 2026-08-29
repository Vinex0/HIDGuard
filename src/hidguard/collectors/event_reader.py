from evdev import InputDevice
from pydantic import ValidationError

from hidguard.errors import StorageError
from hidguard.models.input_event import InputEvent
from hidguard.storage.sqlite_repo import SqliteRepo

EV_KEY = 1


def read_evdev_events(device_node, stop_event, session_id, repo: SqliteRepo):
    """Runs in its own thread, recording events until stopped or unplugged.

    Nothing here may raise. It is a daemon thread with no one to catch for it,
    so every failure that is not this thread's fault -- a node it may not open,
    a device pulled mid-read, a database that has gone away -- is reported on
    the terminal and ends this reader alone, leaving the rest of the daemon and
    the other keyboards' sessions running.
    """
    try:
        dev = InputDevice(device_node)
    except (OSError, PermissionError) as e:
        print(f"  [!] Could not open {device_node}: {e}")
        return

    print(f"  -> Now reading events from {device_node} ({dev.name})")

    try:
        for event in dev.read_loop():
            if stop_event.is_set():
                break
            if event.type != EV_KEY:
                continue  # drop EV_SYN/EV_MSC noise; only keystrokes are ever analysed
            try:
                input_event = InputEvent.from_evdev(event=event, session_id=session_id)
                repo.save_event(input_event)
            except ValidationError as e:
                print(f"[{device_node}] Invalid event: {e.errors()}")

    except OSError:
        # Device was unplugged mid-read
        pass
    except StorageError as e:
        # Nothing this reader can do about it, and nothing to be gained from
        # spinning on a database that is not accepting writes.
        print(f"  [!] Stopped reading {device_node}: {e}")
    finally:
        dev.close()
