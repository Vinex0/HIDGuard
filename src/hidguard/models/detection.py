import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Detection(BaseModel):
    session_id: UUID
    score: int
    verdict: Literal["insufficient_data", "benign", "suspicious", "malicious"]
    hits: list[RuleHit] = Field(default_factory=list)
    evaluated_at: float = Field(default_factory=time.time)


class RuleHit(BaseModel):
    rule: str
    score: int
    reason: str
