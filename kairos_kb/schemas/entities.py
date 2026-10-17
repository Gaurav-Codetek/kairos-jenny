"""Entity and lineage response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChangeEventResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    entity_type: str
    change_type: str
    field_name: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    detected_at: datetime

    model_config = {"from_attributes": True}


class EvidenceResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    source_type: str
    source_id: Optional[str]
    content: str
    observed_at: datetime

    model_config = {"from_attributes": True}


class LineageEdgeResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    source_entity_id: str
    target_entity_id: str
    transformation: Optional[str]
    observed_at: datetime
    confidence: float

    model_config = {"from_attributes": True}
