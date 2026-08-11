

from pydantic import BaseModel
from uuid import UUID

class InputEvent(BaseModel):
    session_id: UUID
    type: int
    code: int
    value: int
    timestamp: float