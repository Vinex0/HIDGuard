

from uuid import UUID

from pydantic import BaseModel


class InputEvent(BaseModel):
    session_id: UUID
    type: int
    code: int
    value: int
    timestamp: float

    @classmethod
    def from_evdev(cls, event, session_id: UUID) -> "InputEvent":
        return cls(
            session_id=session_id,
            type=event.type,
            code=event.code,
            value=event.value,
            timestamp=event.timestamp()
        )