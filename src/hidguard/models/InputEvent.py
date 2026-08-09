from datetime import datetime

from pydantic import BaseModel


class InputEvent(BaseModel):
    session_id: str
    type: int
    code: int
    value: int
    timestamp: datetime