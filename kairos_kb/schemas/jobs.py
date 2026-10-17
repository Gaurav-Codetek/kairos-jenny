"""Job and run response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TaskResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    task_key: str
    task_type: str
    depends_on: Optional[list]
    notebook_path: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    source_native_id: str
    name: str
    owner: Optional[str]
    schedule: Optional[dict]
    tags: Optional[dict]
    max_concurrent_runs: int
    first_seen_at: datetime
    last_seen_at: datetime
    tasks: List[TaskResponse] = []

    model_config = {"from_attributes": True}


class TaskRunResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    task_key: str
    state: str
    result_state: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    error_message: Optional[str]
    attempt_number: int

    model_config = {"from_attributes": True}


class RunResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    source_native_id: str
    run_name: Optional[str]
    state: str
    result_state: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    error_message: Optional[str]
    trigger: str
    execution_duration_ms: Optional[int]
    run_page_url: Optional[str]
    task_runs: List[TaskRunResponse] = []

    model_config = {"from_attributes": True}
