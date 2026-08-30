"""One raw kernel input event, as read from an evdev device node.

from_evdev is annotated with the class it lives in, which Python 3.14 accepts
without `from __future__ import annotations` because PEP 649 defers evaluation.
See 'Why 3.14' in the README.
"""

from uuid import UUID

from pydantic import BaseModel


class InputEvent(BaseModel):
    """A single EV_KEY event: which key, pressed or released, and when."""

    session_id: UUID
    type: int
    code: int
    value: int
    timestamp: float

    @classmethod
    def from_evdev(cls, event, session_id: UUID) -> InputEvent:
        """Builds an event from evdev's own, tagging it with its session.

        evdev hands back its timestamp through a method rather than an
        attribute, which is the only reason this cannot be a model_validate.
        """
        return cls(
            session_id=session_id,
            type=event.type,
            code=event.code,
            value=event.value,
            timestamp=event.timestamp(),
        )
