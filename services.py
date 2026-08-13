import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from time import time

import httpx
from loguru import logger

from lnbits import wallets
from lnbits.core.services.notifications import send_admin_notification
from lnbits.helpers import check_callback_url, urlsafe_short_hash
from lnbits.settings import settings
from lnbits.wallets import get_funding_source

from .crud import (
    create_event,
    create_settings,
    get_settings,
    prune_events,
    update_event,
)
from .crud import update_settings as update_stored_settings
from .models import (
    SETTINGS_ID,
    FundingSourceState,
    StoredWatchSettings,
    WatchEvent,
    WatchSettings,
)

WEBHOOK_ATTEMPTS = 3
WEBHOOK_TIMEOUT = 20
PROBE_TIMEOUT = 15

# VoidWallet has nothing to probe. CoreLightning and Cliche call blocking code
# inside status() (`self.ln.listfunds()` / `create_connection()`), which would
# stall the shared LNbits event loop -- and asyncio.wait_for cannot interrupt a
# synchronous call, so the only safe option is not to probe them at all.
NO_PROBE_WALLETS = {"VoidWallet", "CoreLightningWallet", "ClicheWallet"}


async def get_watch_settings() -> StoredWatchSettings:
    stored = await get_settings()
    if stored:
        return stored
    return await create_settings(StoredWatchSettings(id=SETTINGS_ID))


async def save_watch_settings(data: WatchSettings) -> StoredWatchSettings:
    if data.webhook_url:
        # respects LNBITS_CALLBACK_URL_RULES, raises ValueError if not allowed
        check_callback_url(data.webhook_url)
    values = {**data.dict(), "updated_at": datetime.now(timezone.utc)}
    # `data` may already be a StoredWatchSettings, which carries an id
    values.pop("id", None)
    new_settings = StoredWatchSettings(**values, id=SETTINGS_ID)
    if await get_settings():
        return await update_stored_settings(new_settings)
    return await create_settings(new_settings)


def _configured_funding_source_name() -> str:
    """
    The class name of the configured backend. Resolved through the wallets
    module because settings may hold a legacy alias (`CLightningWallet`), which
    would otherwise never equal the runtime `CoreLightningWallet`.
    """
    name = settings.lnbits_backend_wallet_class
    wallet_class = getattr(wallets, name, None)
    return wallet_class.__name__ if wallet_class else name


async def read_funding_source_state(probe: bool = True) -> FundingSourceState:
    """
    The runtime funding source, which is not always the configured one:
    a failed backend connection at startup silently swaps in VoidWallet.
    """
    funding_source = get_funding_source()
    state = FundingSourceState(
        funding_source=funding_source.__class__.__name__,
        configured_funding_source=_configured_funding_source_name(),
    )

    if (
        state.funding_source == "VoidWallet"
        and state.configured_funding_source != "VoidWallet"
    ):
        # running on the fallback IS the failure; there is nothing left to probe
        state.healthy = False
        state.error = "LNbits fell back to VoidWallet, payments are disabled"
        return state

    if not probe or state.funding_source in NO_PROBE_WALLETS:
        return state

    try:
        status = await asyncio.wait_for(funding_source.status(), PROBE_TIMEOUT)
        state.balance_msat = status.balance_msat
        state.error = status.error_message or None
        state.healthy = not status.error_message
    except asyncio.TimeoutError:
        state.healthy = False
        state.error = f"status() did not answer within {PROBE_TIMEOUT}s"
    except Exception as exc:
        state.healthy = False
        state.error = str(exc)

    return state


async def dispatch_event(
    event_type: str,
    state: FundingSourceState,
    previous_funding_source: str | None = None,
    config: StoredWatchSettings | None = None,
) -> WatchEvent:
    config = config or await get_watch_settings()
    event = WatchEvent(
        id=urlsafe_short_hash(),
        event_type=event_type,
        funding_source=state.funding_source,
        previous_funding_source=previous_funding_source,
        configured_funding_source=state.configured_funding_source,
        healthy=state.healthy,
        error=state.error,
        balance_msat=state.balance_msat,
    )
    logger.warning(
        f"fswatch: {event_type} "
        f"({previous_funding_source} -> {state.funding_source}, "
        f"healthy: {state.healthy})"
    )

    # persist before delivering: if the write fails after a successful POST,
    # the caller would otherwise re-detect the same change and send it again
    # on every single poll
    await create_event(event)
    await prune_events()

    if config.webhook_url:
        event.webhook_status = await _post_webhook(config, _payload(event))
    else:
        event.webhook_status = "no webhook url"

    if config.notify_admin:
        try:
            await send_admin_notification(_notification_text(event), event_type)
        except Exception as exc:
            logger.error(f"fswatch: could not send admin notification: {exc}")

    try:
        await update_event(event)
    except Exception as exc:
        logger.error(f"fswatch: could not store the delivery status: {exc}")

    return event


def _payload(event: WatchEvent) -> dict:
    return {
        "event": event.event_type,
        "timestamp": int(time()),
        "site_title": settings.lnbits_site_title,
        "lnbits_version": settings.version,
        "funding_source": event.funding_source,
        "previous_funding_source": event.previous_funding_source,
        "configured_funding_source": event.configured_funding_source,
        "healthy": event.healthy,
        "error": event.error,
        "balance_msat": event.balance_msat,
    }


async def _post_webhook(config: StoredWatchSettings, payload: dict) -> str:
    try:
        check_callback_url(config.webhook_url)
    except ValueError as exc:
        logger.warning(f"fswatch: {exc}")
        return f"not allowed: {exc}"

    # sign the exact bytes that go over the wire
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": settings.user_agent,
        "X-LNbits-Event": payload["event"],
    }
    if config.webhook_secret:
        signature = hmac.new(
            config.webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        headers["X-LNbits-Signature"] = f"sha256={signature}"

    last_error = "unknown error"
    async with httpx.AsyncClient(headers=headers) as client:
        for attempt in range(WEBHOOK_ATTEMPTS):
            try:
                response = await client.post(
                    config.webhook_url, content=body, timeout=WEBHOOK_TIMEOUT
                )
                if 300 <= response.status_code < 400:
                    # redirects are not followed, so the body never arrived;
                    # retrying the same URL cannot help
                    location = response.headers.get("location", "?")
                    return (
                        f"failed: redirect {response.status_code} to {location} "
                        "(use the final URL)"
                    )
                response.raise_for_status()
                return str(response.status_code)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                last_error = f"status {status_code}"
                if 400 <= status_code < 500 and status_code not in (408, 429):
                    # the receiver rejected it; retrying will be rejected too
                    return f"failed: {last_error}"
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
            logger.warning(
                f"fswatch: webhook attempt {attempt + 1}/{WEBHOOK_ATTEMPTS} "
                f"failed: {last_error}"
            )
            if attempt + 1 < WEBHOOK_ATTEMPTS:
                await asyncio.sleep(2**attempt)

    return f"failed: {last_error}"


def _notification_text(event: WatchEvent) -> str:
    return (
        "*FUNDING SOURCE WATCH*\n"
        f"        *Event*: `{event.event_type}`.\n"
        f"        *Funding source*: `{event.funding_source}`.\n"
        f"        *Previous*: `{event.previous_funding_source}`.\n"
        f"        *Configured*: `{event.configured_funding_source}`.\n"
        f"        *Healthy*: `{event.healthy}`.\n"
        f"        *Error*: `{event.error}`."
    )
