"""
Listens for new input device connections via pyudev, then reads
and prints live events from each device using evdev.
"""

import threading
import time
from uuid import uuid4

import pyudev
from evdev import InputDevice
from pydantic import ValidationError

from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session

# Track running readers so we can stop them on device removal
active_readers = {}  # device_node -> (InputDevice, threading.Event)
active_sessions = {}

def format_udev_info(device):
    lines = [
        f"Action:        {device.action}",
        f"Device Node:   {device.device_node}",
        f"Subsystem:     {device.subsystem}",
        f"Sys Path:      {device.sys_path}",
        f"Children:      {[child for child in device.children]}",
    ]
    for prop in ('ID_VENDOR_ID', 'ID_MODEL_ID', 'ID_VENDOR', 'ID_MODEL', 'ID_SERIAL', 'ID_BUS', 'ID_INPUT',
                 'ID_INPUT_KEYBOARD', 'ID_INPUT_MOUSE', 'ID_INPUT_TOUCHPAD', 'ID_USB_INTERFACES'):
        value = device.properties.get(prop)
        if value:
            lines.append(f"{prop:<20} {value}")

    return "\n".join(lines)






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
            print(InputEvent.from_evdev(event=event, session_id=session_id))
            if stop_event.is_set():
                break

    except OSError:
        # Device was unplugged mid-read
        pass
    finally:
        dev.close()

def handle_add(device):
    node = device.device_node
    if not node or 'event' not in node:
        return  # skip non-event nodes (e.g. js0 joystick nodes, etc.)

    print("=" * 60)
    print("New input device connected:")
    print(format_udev_info(device))
    device_model = Device.from_udev(device)
    print("\n")
    print(device_model)
    session = Session.start(device_model.id)
    print(session)
    active_sessions[node] = session
    

    print("=" * 60)

    stop_event = threading.Event()
    thread = threading.Thread(
        target=read_evdev_events, args=(node, stop_event, session.id), daemon=True
    )
    active_readers[node] = (thread, stop_event)
    thread.start()


def handle_remove(device):
    node = device.device_node
    if node in active_readers:
        print(f"Device removed: {node}")
        _, stop_event = active_readers.pop(node)
        stop_event.set()

    if node in active_sessions:
        session = active_sessions.pop(node)
        session.end()
        print(f"Session ended: {session.id}, ",
        f"duration={session.disconnected_at-session.connected_at}")


def main():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='input')

    print("Listening for input device connections... (Ctrl+C to stop)\n")

    try:
        for device in iter(monitor.poll, None):
            if device.action == 'add':
                handle_add(device)
            elif device.action == 'remove':
                handle_remove(device)
    except KeyboardInterrupt:
        print("\nStopped listening.")


if __name__ == '__main__':
    main()