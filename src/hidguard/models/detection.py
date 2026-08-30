"""What the rule engine concluded about one session.

Detection is annotated with RuleHit before RuleHit exists, which is legal only
because PEP 649 made annotation evaluation lazy in Python 3.14 -- the version
this project requires. Reading the whole verdict top-down beats defining the
detail type first, and pydantic resolves the reference when the model is built.
On 3.13 this file raises NameError at import; see 'Why 3.14' in the README.
"""

import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Detection(BaseModel):
    """A session's score and the rules that produced it."""

    session_id: UUID
    score: int
    verdict: Literal["insufficient_data", "benign", "suspicious", "malicious"]
    hits: list[RuleHit] = Field(default_factory=list)
    evaluated_at: float = Field(default_factory=time.time)


class RuleHit(BaseModel):
    """One rule that fired, with the measurement that tripped it."""

    rule: str
    score: int
    reason: str
