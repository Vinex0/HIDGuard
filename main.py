"""
Listens for new input device connections via pyudev, then reads
and prints live events from each device using evdev.
"""

import threading

import pyudev
from evdev import InputDevice, categorize, ecodes
from pydantic import BaseModel, ValidationError

# Track running readers so we can stop them on device removal
active_readers = {}  # device_node -> (InputDevice, threading.Event)

class Device(BaseModel):
    id: str
    vendor_id: str | None = None
    model_id: str | None = None
    vendor_name: str | None = None
    model_name: str | None = None
    serial: str | None = None
    interfaces: str | None = None

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

def create_device(device):
    vendor_id = device.properties.get("ID_VENDOR_ID")
    model_id = device.properties.get("ID_MODEL_ID")
    vendor_name = device.properties.get("ID_VENDOR")
    model_name = device.properties.get("ID_MODEL")
    serial = device.properties.get("ID_SERIAL")
    interfaces = device.properties.get("ID_USB_INTERFACES")

    id_parts = [p for p in (vendor_id, model_id, serial or device.sys_path) if p]
    device_id = ":".join(id_parts)

    try:
        pd_device = Device(
        id= device_id,
        vendor_id=vendor_id, 
        model_id=model_id, 
        vendor_name=vendor_name,
        model_name=model_name,
        serial=serial,
        interfaces=interfaces)
        return pd_device

    except ValidationError as e:
        print(e.errors())



def read_evdev_events(device_node, stop_event):
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

            if event.type == ecodes.EV_KEY:
                key_event = categorize(event)
                print(f"[{device_node}] {key_event}")
            elif event.type == ecodes.EV_REL:
                print(f"[{device_node}] REL code={event.code} value={event.value}")
            elif event.type == ecodes.EV_ABS:
                print(f"[{device_node}] ABS code={event.code} value={event.value}")
            # EV_SYN events are just sync markers, skip printing them
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
    print(create_device(device))
    print("=" * 60)

    stop_event = threading.Event()
    thread = threading.Thread(
        target=read_evdev_events, args=(node, stop_event), daemon=True
    )
    active_readers[node] = (thread, stop_event)
    thread.start()


def handle_remove(device):
    node = device.device_node
    if node in active_readers:
        print(f"Device removed: {node}")
        _, stop_event = active_readers.pop(node)
        stop_event.set()


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