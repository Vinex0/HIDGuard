from evdev import InputDevice
from hidguard.models.input_event import InputEvent
from pydantic import ValidationError


def read_evdev_events(device_node, stop_event, session_id):
    """Runs in its own thread, printing events until stopped or unplugged."""
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
            try:
                input_event = InputEvent.from_evdev(event=event, session_id=session_id)
                print(input_event)
            except ValidationError as e:
                print(f"[{device_node}] Invalid event: {e.errors()}")

    except OSError:
        # Device was unplugged mid-read
        pass
    finally:
        dev.close()