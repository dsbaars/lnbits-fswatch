from datetime import datetime, timezone

from pydantic import BaseModel, Field

SETTINGS_ID = "admin"

EVENT_CHANGED = "funding_source_changed"
EVENT_UNHEALTHY = "funding_source_unhealthy"
EVENT_HEALTHY = "funding_source_healthy"
EVENT_TEST = "test"


class FundingSourceState(BaseModel):
    """Runtime snapshot of the funding source."""

    funding_source: str
    configured_funding_source: str
    healthy: bool = True
    error: str | None = None
    balance_msat: int | None = None


class WatchSettings(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    webhook_secret: str = ""
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    probe_status: bool = True
    failure_threshold: int = Field(default=2, ge=1, le=20)
    notify_admin: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StoredWatchSettings(WatchSettings):
    id: str


class WatchEvent(BaseModel):
    id: str
    event_type: str
    funding_source: str
    previous_funding_source: str | None = None
    configured_funding_source: str | None = None
    healthy: bool = True
    error: str | None = None
    balance_msat: int | None = None
    webhook_status: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
