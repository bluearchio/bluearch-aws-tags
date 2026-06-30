"""Pydantic schemas for event tracking endpoints."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class EventTrackingDeployRequest(BaseModel):
    """Request to deploy event tracking to account-region pairs."""

    targets: Dict[str, List[str]] = Field(
        ...,
        description='Map of account_id -> list of regions. '
                    'e.g. {"111111111111": ["us-east-1", "us-west-2"]}',
    )


class EventTrackingRemoveRequest(BaseModel):
    """Request to remove event tracking from account-region pairs."""

    targets: Dict[str, List[str]] = Field(
        ...,
        description='Map of account_id -> list of regions to remove.',
    )


class EventTrackingInstanceStatus(BaseModel):
    """Status of a single event tracking instance (account-region pair)."""

    account_id: str
    region: str
    status: str = "unknown"
    queue_url: str = ""
    queue_arn: str = ""
    stack_id: str = ""
    last_polled_at: Optional[str] = None
    last_event_at: Optional[str] = None
    messages_processed: int = 0
    events_today: int = 0
    error_message: Optional[str] = None


class EventTrackingStatusResponse(BaseModel):
    """Full event tracking status."""

    stackset_exists: bool = False
    stackset_status: str = ""
    instances: List[EventTrackingInstanceStatus] = []
    service_running: bool = False
    service_paused: bool = False
    total_queues: int = 0
    active_queues: int = 0


class EventTrackingSyncAction(BaseModel):
    """Request to pause, resume, or sync the event sync service."""

    action: str = Field(
        ...,
        description="Action to perform: 'pause', 'resume', 'start', 'stop', 'sync', 'poll'",
    )


class EventTrackingPollRequest(BaseModel):
    """Request to poll active event queues once."""

    max_messages: int = 10
    wait_time_seconds: int = 0
    visibility_timeout: int = 60
