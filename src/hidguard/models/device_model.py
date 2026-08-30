"""The USB device a session belongs to, as udev describes it.

from_udev is annotated with the class it lives in, which Python 3.14 accepts
without `from __future__ import annotations` because PEP 649 defers evaluation.
See 'Why 3.14' in the README.
"""

from pydantic import BaseModel


class Device(BaseModel):
    """What udev reports about a keyboard -- none of it trusted for scoring.

    Recorded so a verdict can be attributed to a device and shown by name in
    the dashboard. Every field here is what the device claims about itself,
    which is precisely what an injection tool forges; the detection reads only
    the keystroke timing in Session.
    """

    id: str
    vendor_id: str | None = None
    model_id: str | None = None
    vendor_name: str | None = None
    model_name: str | None = None
    serial: str | None = None
    interfaces: str | None = None

    @classmethod
    def from_udev(cls, udev_device) -> Device:
        """Builds a Device from a pyudev device, deriving a stable id.

        Vendor and model alone do not identify a device -- two identical
        keyboards share them -- so the serial joins them, and the sysfs path
        stands in when a device reports no serial at all.
        """
        vendor_id = udev_device.properties.get("ID_VENDOR_ID")
        model_id = udev_device.properties.get("ID_MODEL_ID")
        vendor_name = udev_device.properties.get("ID_VENDOR")
        model_name = udev_device.properties.get("ID_MODEL")
        serial = udev_device.properties.get("ID_SERIAL")
        interfaces = udev_device.properties.get("ID_USB_INTERFACES")

        id_parts = [p for p in (vendor_id, model_id, serial or udev_device.sys_path) if p]
        device_id = ":".join(id_parts)

        return cls(
            id=device_id,
            vendor_id=vendor_id,
            model_id=model_id,
            vendor_name=vendor_name,
            model_name=model_name,
            serial=serial,
            interfaces=interfaces,
        )
