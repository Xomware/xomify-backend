"""
Pydantic request models for the Broadcasts/Admin service.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BroadcastCreateRequest(BaseModel):
    """Body for POST /admin/broadcasts-create."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    activeUntil: Optional[str] = None
