from pydantic import BaseModel


class Device(BaseModel):
    id: str
    vendor_id: str | None = None
    model_id: str | None = None
    vendor_name: str | None = None
    model_name: str | None = None
    serial: str | None = None
    interfaces: str | None = None