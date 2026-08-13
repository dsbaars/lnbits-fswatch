from http import HTTPStatus

from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException

from lnbits.core.models import SimpleStatus
from lnbits.decorators import check_admin

from .crud import delete_events, get_events
from .models import EVENT_TEST, FundingSourceState, WatchEvent, WatchSettings
from .services import (
    dispatch_event,
    get_watch_settings,
    read_funding_source_state,
    save_watch_settings,
)

fswatch_api_router = APIRouter()


@fswatch_api_router.get(
    "/api/v1/state",
    name="Funding Source State",
    summary="The funding source LNbits is running on right now.",
    dependencies=[Depends(check_admin)],
)
async def api_get_state() -> FundingSourceState:
    config = await get_watch_settings()
    return await read_funding_source_state(config.probe_status)


@fswatch_api_router.get(
    "/api/v1/settings",
    name="Get Settings",
    dependencies=[Depends(check_admin)],
)
async def api_get_settings() -> WatchSettings:
    return await get_watch_settings()


@fswatch_api_router.put(
    "/api/v1/settings",
    name="Update Settings",
    dependencies=[Depends(check_admin)],
)
async def api_update_settings(data: WatchSettings) -> WatchSettings:
    try:
        return await save_watch_settings(data)
    except ValueError as exc:
        raise HTTPException(HTTPStatus.BAD_REQUEST, str(exc)) from exc


@fswatch_api_router.get(
    "/api/v1/events",
    name="Event Log",
    dependencies=[Depends(check_admin)],
)
async def api_get_events(limit: int = 100) -> list[WatchEvent]:
    return await get_events(min(max(limit, 1), 500))


@fswatch_api_router.delete(
    "/api/v1/events",
    name="Clear Event Log",
    dependencies=[Depends(check_admin)],
)
async def api_delete_events() -> SimpleStatus:
    await delete_events()
    return SimpleStatus(success=True, message="Event log cleared.")


@fswatch_api_router.post(
    "/api/v1/test",
    name="Test Webhook",
    summary="Send a test event to the configured webhook URL.",
    dependencies=[Depends(check_admin)],
)
async def api_test_webhook() -> WatchEvent:
    config = await get_watch_settings()
    if not config.webhook_url:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "No webhook URL configured.")
    state = await read_funding_source_state()
    return await dispatch_event(EVENT_TEST, state, config=config)
