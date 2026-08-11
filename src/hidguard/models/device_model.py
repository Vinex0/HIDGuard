from pydantic import BaseModel


class Device(BaseModel):
    id: str
    vendor_id: str | None = None
    model_id: str | None = None
    vendor_name: str | None = None
    model_name: str | None = None
    serial: str | None = None
    interfaces: str | None = None

    @classmethod
    def from_udev(cls, udev_device) -> Device:
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