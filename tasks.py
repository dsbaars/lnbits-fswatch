import asyncio

from loguru import logger

from lnbits.settings import settings

from .models import (
    EVENT_CHANGED,
    EVENT_HEALTHY,
    EVENT_UNHEALTHY,
    FundingSourceState,
)
from .services import dispatch_event, get_watch_settings, read_funding_source_state

VOID_FALLBACK_ERROR = "LNbits switched to VoidWallet, payments are disabled"


def _still_on_void_fallback(
    state: FundingSourceState, last_source: str, arrived_on_void: bool
) -> bool:
    """
    Whether LNbits is on VoidWallet because it *arrived* there, as opposed to
    being deliberately configured for it.

    Arriving on VoidWallet is a fallback whatever the settings say by now: the
    watchdog rewrites `lnbits_backend_wallet_class` to VoidWallet as well, so
    only the transition itself reveals what happened. It stays a fallback until
    the funding source changes again -- a later check has no transition left to
    look at and would otherwise read as perfectly healthy.

    A watcher that starts up already on VoidWallet has no transition to go on
    and cannot tell a fallback from a deliberate choice. The caller seeds the
    latch for that case, so being on VoidWallet is reported as unhealthy from
    the very first check without alerting on it.
    """
    if state.funding_source != "VoidWallet":
        return False
    return arrived_on_void or last_source != "VoidWallet"


async def watch_funding_source() -> None:
    """
    Poll the runtime funding source and fire a webhook when it changes.

    The baseline is the *configured* funding source, so a server that booted
    straight into the VoidWallet fallback reports on the first check.
    """
    last_source: str | None = None
    last_healthy = True
    failures = 0
    arrived_on_void = False

    while settings.lnbits_running:
        interval = 60
        try:
            config = await get_watch_settings()
            interval = config.interval_seconds

            if not config.enabled:
                # re-baseline when the watcher is switched back on
                last_source, last_healthy, failures = None, True, 0
                arrived_on_void = False
            else:
                state = await read_funding_source_state(config.probe_status)

                if last_source is None:
                    last_source = state.configured_funding_source
                    # Baselining onto VoidWallet is ambiguous: a deliberate
                    # VoidWallet install and a watchdog switch this watcher
                    # arrived too late to witness look identical. Alerting is
                    # therefore wrong -- but so is claiming health, because
                    # payments are disabled either way. Start unhealthy AND
                    # start quiet, by baselining last_healthy to match.
                    arrived_on_void = state.funding_source == "VoidWallet"
                    last_healthy = not arrived_on_void

                arrived_on_void = _still_on_void_fallback(
                    state, last_source, arrived_on_void
                )
                if arrived_on_void:
                    state.healthy = False
                    state.error = state.error or VOID_FALLBACK_ERROR

                if state.healthy:
                    failures = 0
                    healthy = True
                else:
                    failures += 1
                    # a single failed probe is not enough to call it unhealthy,
                    # but once it IS unhealthy only a successful probe clears
                    # it again -- raising the threshold mid-outage must not
                    # look like a recovery
                    healthy = last_healthy and failures < config.failure_threshold

                event_type = None
                if state.funding_source != last_source:
                    event_type = EVENT_CHANGED
                    # a new funding source starts from a clean health baseline,
                    # so its state is reported as-is and never alerted on twice
                    healthy = state.healthy
                    failures = 0 if state.healthy else config.failure_threshold
                elif healthy != last_healthy:
                    event_type = EVENT_HEALTHY if healthy else EVENT_UNHEALTHY

                # commit the new state BEFORE dispatching: a dispatch that
                # raises must not re-fire the same event on every poll
                previous_source = last_source
                last_source = state.funding_source
                last_healthy = healthy

                if event_type:
                    await dispatch_event(event_type, state, previous_source, config)

        except Exception as exc:
            logger.error(f"fswatch: error while checking the funding source: {exc}")

        await asyncio.sleep(interval)
